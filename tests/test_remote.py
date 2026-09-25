import asyncio
import hashlib
import socket
from dataclasses import replace

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from splitwise_mcp.errors import AppError
from splitwise_mcp.remote import build_remote
from splitwise_mcp.server import build_server

TOKEN = "independent-caller-token-256-bit-synthetic-fixture"


@pytest.fixture
async def remote(make_service, settings):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    options = dict(
        remote=True,
        database="postgresql://unused-test?sslmode=verify-full",
        host=f"127.0.0.1:{port}",
        caller_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(),
    )
    service = make_service(**options)
    app = build_remote(build_server(service), replace(settings, **options), service.upstream)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", access_log=False)
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}", service
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()


async def test_remote_protocol_and_auth(remote):
    base, service = remote
    async with httpx.AsyncClient() as http:
        assert (await http.get(base + "/health")).json() == {"status": "ok"}
        for method in ("GET", "POST", "DELETE", "OPTIONS"):
            for headers in (
                {},
                {"Authorization": "Bearer wrong"},
                {"Authorization": "Bearer SECRET_UPSTREAM_CANARY"},
                {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.wrong-audience.signature"},
            ):
                response = await http.request(
                    method,
                    base + "/mcp",
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )
                assert response.status_code == 401
        for extra in (
            {"Host": "evil.invalid"},
            {"Origin": "https://evil.invalid"},
            {"X-User-ID": "attacker"},
        ):
            response = await http.post(
                base + "/mcp", headers={"Authorization": "Bearer " + TOKEN, **extra}, json={}
            )
            assert response.status_code == 403
    async with (
        httpx.AsyncClient(headers={"Authorization": "Bearer " + TOKEN}) as http,
        streamable_http_client(base + "/mcp", http_client=http) as (read, write, _),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        assert len((await client.list_tools()).tools) == 10
        result = await client.call_tool("splitwise_get_current_user", {})
        assert not result.isError, result
        assert result.structuredContent["id"] == 1
        invalid = await client.call_tool("splitwise_get_current_user", {"owner": "other"})
        assert invalid.isError
    async with httpx.AsyncClient() as http:
        response = await http.post(
            base + "/mcp",
            headers={
                "Authorization": "Bearer " + TOKEN,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            content=b"x" * 40000,
        )
        assert response.status_code == 413


@pytest.mark.parametrize(
    "changes",
    [
        {"remote": True},
        {"remote": True, "database": "postgresql://test", "host": "example.com"},
        {
            "remote": True,
            "database": "postgresql://test",
            "host": "example.com",
            "caller_token_hash": "a" * 64,
            "fixture": True,
        },
        {"owner": ""},
        {"account_id": 0},
        {"api_key": ""},
        {"writes": True, "approval_public_key": ""},
    ],
)
def test_fail_closed(settings, changes):
    with pytest.raises(AppError, match="configuration"):
        replace(settings, **changes).validate()
