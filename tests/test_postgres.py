"""Private, ephemeral local PostgreSQL cluster; never reads production configuration."""

import os
import shutil
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from splitwise_mcp.store import Store


@pytest.fixture(scope="module")
def pg_store(tmp_path_factory):
    postgres = shutil.which("postgres")
    if postgres is None:
        pytest.skip(
            "Local PostgreSQL binaries unavailable; never fall back to an external database"
        )
    bindir = os.path.dirname(os.path.realpath(postgres))
    root = tmp_path_factory.mktemp("isolated-postgres")
    data = root / "data"
    env = {"PATH": os.environ["PATH"], "LC_ALL": "C", "HOME": str(root)}
    subprocess.run(
        [bindir + "/initdb", "-D", str(data), "-A", "trust", "--no-locale", "--encoding=UTF8"],
        env=env,
        check=True,
        capture_output=True,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    subprocess.run(
        [
            bindir + "/pg_ctl",
            "-D",
            str(data),
            "-l",
            str(root / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {port} -c unix_socket_directories=''",
            "-w",
            "start",
        ],
        env=env,
        check=True,
        capture_output=True,
    )
    try:
        store = Store(f"postgresql://127.0.0.1:{port}/postgres")
        yield store
    finally:
        subprocess.run(
            [bindir + "/pg_ctl", "-D", str(data), "-m", "fast", "-w", "stop"],
            env=env,
            check=True,
            capture_output=True,
        )


def test_postgres_migration_concurrent_reservation_and_restart(pg_store):
    store = pg_store
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: store.migrate(), range(3)))
    store.check_schema()
    row = store.put("owner", 1, "operation-001", "hash", {"synthetic": True})
    assert Store(store.database).get("owner", 1, row["id"])["state"] == "pending_approval"
    store.approve("owner", 1, row["id"], "approval-hash", row["expires"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: store.reserve("owner", 1, row["id"], "approval-hash", row["expires"]),
                range(8),
            )
        )
    assert results.count(True) == 1
    store.finish("owner", 1, row["id"], "succeeded", 42)
    assert store.get("owner", 1, row["id"])["expense_id"] == 42
    store.migrate()
    assert store.get("owner", 1, row["id"])["state"] == "succeeded"
