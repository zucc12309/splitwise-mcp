import argparse
import asyncio
import json
import logging
import os
import sys

import httpx
from mcp.server.stdio import stdio_server

from .config import Settings
from .errors import AppError
from .models import Empty
from .server import build_server, principal
from .service import Service
from .store import Store
from .upstream import Splitwise


def configure_logging():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(message)s")
    logging.getLogger("splitwise_mcp.operations").setLevel(logging.INFO)
    # Do not let dependency loggers expose requests, response bodies or credentials.
    for name in ("httpx", "httpcore", "mcp", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


async def run_stdio(server, owner, upstream):
    token = principal.set(owner)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        principal.reset(token)
        await upstream.close()


def main():
    os.umask(0o077)
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", nargs="?", default="serve", choices=["serve", "migrate", "smoke", "prune"]
    )
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        store = Store(settings.database)
        if args.command == "migrate":
            store.migrate()
            print("Schema version 1 ready.")
            return
        if store.postgres:
            store.check_schema()
        else:
            store.migrate()
        if args.command == "prune":
            print(
                f"Removed old draft details from {store.prune()} operations; duplicate-prevention ledger retained."
            )
            return
        if settings.fixture:
            from .fixtures import handler

            transport = httpx.MockTransport(handler)
        else:
            transport = None
        upstream = Splitwise(settings.api_key, transport)
        service = Service(settings, upstream, store)
        if args.command == "smoke":

            async def smoke():
                try:
                    result = await service.call("get_current_user", Empty(), settings.owner)
                    print(json.dumps(result.model_dump(mode="json")))
                finally:
                    await upstream.close()

            asyncio.run(smoke())
        elif settings.remote:
            import uvicorn

            from .remote import build_remote

            uvicorn.run(
                build_remote(build_server(service), settings, upstream),
                host="0.0.0.0",
                port=settings.port,
                access_log=False,
                proxy_headers=False,
                limit_concurrency=16,
                timeout_graceful_shutdown=30,
            )
        else:
            asyncio.run(run_stdio(build_server(service), settings.owner, upstream))
    except AppError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        pass
    except Exception:
        print(
            "startup_failure: Check configuration and database availability; details suppressed to protect credentials.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
