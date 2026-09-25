"""Additional boundary checks using only synthetic data and local ASGI calls."""

import hashlib
import random
from copy import deepcopy
from dataclasses import replace

import pytest

from splitwise_mcp.fixtures import PROPOSAL
from splitwise_mcp.models import Proposal
from splitwise_mcp.money import allocate, decimal, minor
from splitwise_mcp.remote import Guard
from splitwise_mcp.server import principal


def test_seeded_money_conservation_and_permutation():
    rng = random.Random(20260925)
    for _ in range(1000):
        count = rng.randint(1, 30)
        total = rng.choice([1, 2, 99_999_999_999, rng.randint(1, 99_999_999_999)])
        cuts = sorted([0, total] + [rng.randint(0, total) for _ in range(count - 1)])
        people = [{"user_id": i + 1, "paid": decimal(cuts[i + 1] - cuts[i])} for i in range(count)]
        raw = {**deepcopy(PROPOSAL), "total": decimal(total), "participants": people}
        normalized, _ = allocate(Proposal.model_validate(raw))
        owed = [minor(p.owed) for p in normalized.participants]
        assert sum(owed) == sum(minor(p.paid) for p in normalized.participants) == total
        assert max(owed) - min(owed) <= 1
        assert owed == sorted(owed, reverse=True)
        rng.shuffle(people)
        shuffled, _ = allocate(Proposal.model_validate(raw))
        assert normalized == shuffled


@pytest.mark.parametrize(
    "headers,status",
    [
        ([(b"host", b"test.local")], 401),
        ([(b"authorization", b"Bearer token")], 401),
        ([(b"host", b"test.local")] * 2, 401),
        ([(b"authorization", b"Bearer token")] * 2, 403),
        ([(b"host", b"test.local"), (b"authorization", b"Bearer token")] * 2, 401),
        ([(b"host", b"\xff"), (b"authorization", b"Bearer token")], 403),
        ([(b"host", b"test.local"), (b"authorization", b"Bearer ")], 401),
        ([(b"host", b"test.local"), (b"authorization", b"Basic token")], 401),
        (
            [(b"host", b"test.local"), (b"authorization", b"Bearer token"), (b"origin", b"null")],
            403,
        ),
        (
            [
                (b"host", b"test.local"),
                (b"authorization", b"Bearer token"),
                (b"x-owner-id", b"owner"),
            ],
            403,
        ),
    ],
)
async def test_guard_malformed_headers_never_dispatch(settings, headers, status):
    async def forbidden(*args):
        pytest.fail("Invalid authentication reached MCP")

    messages = []

    async def send(message):
        messages.append(message)

    guard = Guard(
        forbidden,
        replace(
            settings, host="test.local", caller_token_hash=hashlib.sha256(b"token").hexdigest()
        ),
    )
    await guard({"type": "http", "headers": headers}, forbidden, send)
    assert messages[0]["status"] == status


async def test_guard_resets_identity_after_downstream_failure(settings):
    before = principal.get()

    async def failing(*args):
        assert principal.get() == settings.owner
        raise RuntimeError("synthetic downstream failure")

    guard = Guard(
        failing,
        replace(
            settings, host="test.local", caller_token_hash=hashlib.sha256(b"token").hexdigest()
        ),
    )
    with pytest.raises(RuntimeError, match="synthetic"):
        await guard(
            {
                "type": "http",
                "headers": [(b"host", b"test.local"), (b"authorization", b"Bearer token")],
            },
            None,
            None,
        )
    assert principal.get() == before
