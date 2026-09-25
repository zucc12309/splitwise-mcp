import base64
import time
from dataclasses import replace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from splitwise_mcp.config import Settings
from splitwise_mcp.fixtures import handler
from splitwise_mcp.service import Service
from splitwise_mcp.store import Store, canonical
from splitwise_mcp.upstream import Splitwise


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def settings(tmp_path, key):
    return Settings(
        owner="owner",
        account_id=1,
        api_key="SECRET_UPSTREAM_CANARY",
        database=str(tmp_path / "state.sqlite"),
        writes=True,
        approval_public_key=b64(key.public_key().public_bytes_raw()),
    )


@pytest.fixture
def store(settings):
    store = Store(settings.database)
    store.migrate()
    return store


@pytest.fixture
def make_service(settings, store):
    created = []

    def make(responder=handler, **changes):
        upstream = Splitwise(settings.api_key, httpx.MockTransport(responder))
        created.append(upstream)
        return Service(replace(settings, **changes), upstream, store)

    return make


@pytest.fixture
def sign(key):
    def issue(preview, **changes):
        claims = {
            "version": 1,
            "owner": preview.owner,
            "account_id": preview.account.id,
            "draft_id": preview.draft_id,
            "draft_hash": preview.draft_hash,
            "operation": "create_expense",
            "expires_at": int(time.time()) + 300,
            "nonce": "synthetic-nonce-123456789",
        }
        claims.update(changes)
        message = canonical(claims).encode()
        return b64(message) + "." + b64(key.sign(message))

    return issue
