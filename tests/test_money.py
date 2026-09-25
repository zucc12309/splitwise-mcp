from copy import deepcopy

import pytest
from pydantic import ValidationError

from splitwise_mcp.errors import AppError
from splitwise_mcp.fixtures import PROPOSAL
from splitwise_mcp.models import ExpenseQuery, Proposal
from splitwise_mcp.money import allocate, minor


def proposal(total="100.00", **changes):
    raw = deepcopy(PROPOSAL)
    raw["total"] = total
    raw["participants"][0]["paid"] = total
    raw.update(changes)
    return Proposal.model_validate(raw)


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        ("1200", ["400.00"] * 3),
        ("100", ["33.34", "33.33", "33.33"]),
        ("0.01", ["0.01", "0.00", "0.00"]),
    ],
)
def test_equal(total, expected):
    normalized, allocations = allocate(proposal(total))
    assert [p.owed for p in normalized.participants] == expected
    assert sum(minor(p.owed) for p in normalized.participants) == minor(total)
    assert sum(a.extra_minor_units for a in allocations) == minor(total) % 3


def test_remainder_independent_of_input_order():
    p = proposal()
    p.participants.reverse()
    normalized, _ = allocate(p)
    assert normalized.participants[0].user_id == 1
    assert normalized.participants[0].owed == "33.34"


def test_multiple_payers_explicit():
    p = proposal(
        split="explicit",
        participants=[
            {"user_id": 1, "paid": "60", "owed": "20"},
            {"user_id": 2, "paid": "40", "owed": "80"},
        ],
    )
    normalized, _ = allocate(p)
    assert normalized.participants[1].owed == "80.00"


@pytest.mark.parametrize("value", ["0", "-1", "1.001", "nan", "1e2", 1.2, "1000000000", "01.00"])
def test_invalid_money(value):
    with pytest.raises((AppError, ValidationError)):
        allocate(proposal(value))


@pytest.mark.parametrize("currency", ["JPY", "KWD", "BTC", "ZZZ"])
def test_unverified_currency_rejected(currency):
    with pytest.raises(AppError, match="unsupported_currency"):
        allocate(proposal(currency=currency))


def test_duplicate_and_mismatches():
    p = proposal()
    p.participants[1].user_id = 1
    with pytest.raises(AppError):
        allocate(p)
    p = proposal()
    p.participants[0].paid = "1"
    with pytest.raises(AppError):
        allocate(p)
    p = proposal(split="explicit")
    with pytest.raises(AppError):
        allocate(p)
    p = proposal()
    p.participants[0].owed = "1"
    with pytest.raises(AppError):
        allocate(p)


@pytest.mark.parametrize(
    "changes",
    [
        {"owner": "attacker"},
        {"date": "2026-01-01"},
        {"date": "1900-01-01T00:00:00Z"},
        {"group_id": True},
        {"description": "\n"},
    ],
)
def test_strict_inputs(changes):
    with pytest.raises(ValidationError):
        proposal(**changes)


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 51},
        {"offset": 10001},
        {"group_id": 1, "friend_id": 2},
        {"dated_after": "2026-01-01"},
        {"dated_after": "2026-02-01T00:00:00Z", "dated_before": "2026-01-01T00:00:00Z"},
        {"url": "http://localhost"},
    ],
)
def test_query_validation(query):
    with pytest.raises(ValidationError):
        ExpenseQuery.model_validate(query)
