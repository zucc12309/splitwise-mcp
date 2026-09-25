"""Synthetic approval/execution demonstration. MockTransport NEVER opens a socket.

The in-memory signing key here is test-only, not a trusted human approval setup.
"""

import asyncio
import base64
import json
import tempfile
import time

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from splitwise_mcp.config import Settings
from splitwise_mcp.fixtures import PROPOSAL, handler
from splitwise_mcp.models import Execute, Proposal
from splitwise_mcp.service import Service
from splitwise_mcp.store import Store, canonical
from splitwise_mcp.upstream import Splitwise


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


async def main():
    posts = []

    def respond(request):
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(200, json={"expenses": [{"id": 999}], "errors": {}})
        return handler(request)

    with tempfile.TemporaryDirectory() as directory:
        key = Ed25519PrivateKey.generate()
        settings = Settings(
            owner="synthetic-owner",
            account_id=1,
            api_key="synthetic",
            database=directory + "/state.sqlite",
            writes=True,
            approval_public_key=b64(key.public_key().public_bytes_raw()),
        )
        store = Store(settings.database)
        store.migrate()
        api = Splitwise("synthetic", httpx.MockTransport(respond))
        try:
            service = Service(settings, api, store)
            preview = await service.call(
                "preview_expense", Proposal.model_validate(PROPOSAL), settings.owner
            )
            print("Preview posted:", preview.posted)
            message = canonical(
                {
                    "version": 1,
                    "owner": settings.owner,
                    "account_id": 1,
                    "draft_id": preview.draft_id,
                    "draft_hash": preview.draft_hash,
                    "operation": "create_expense",
                    "expires_at": int(time.time()) + 300,
                    "nonce": "synthetic-demonstration-nonce",
                }
            ).encode()
            evidence = b64(message) + "." + b64(key.sign(message))
            request = Execute(draft_id=preview.draft_id, approval=evidence)
            for _ in range(2):
                result = await service.call("create_expense", request, settings.owner)
                print(json.dumps(result.model_dump()))
            assert len(posts) == 1
            print("Synthetic POST count: 1; network requests: 0")
        finally:
            await api.close()


asyncio.run(main())
