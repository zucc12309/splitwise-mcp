"""Synthetic HTTP fixtures. No networking or real credentials."""

import httpx

PEOPLE = [
    {"id": 1, "first_name": "Demo Owner", "last_name": "", "email": "omit@example.invalid"},
    {"id": 2, "first_name": "Alex", "last_name": ""},
    {"id": 3, "first_name": "Alex", "last_name": ""},
]
GROUP = {
    "id": 10,
    "name": "Synthetic household",
    "members": PEOPLE,
    "original_debts": [{"from": 2, "to": 1, "currency_code": "INR", "amount": "33.33"}],
}
EXPENSE = {
    "id": 42,
    "group_id": 10,
    "description": "Synthetic lunch",
    "date": "2026-09-24T12:00:00Z",
    "currency_code": "INR",
    "cost": "100.00",
    "deleted_at": None,
    "users": [
        {
            "user_id": i,
            "paid_share": "100.00" if i == 1 else "0.00",
            "owed_share": "33.34" if i == 1 else "33.33",
        }
        for i in (1, 2, 3)
    ],
}
PROPOSAL = {
    "operation_key": "synthetic-lunch-001",
    "group_id": 10,
    "description": "Synthetic lunch",
    "date": "2026-09-24T12:00:00Z",
    "currency": "INR",
    "total": "100.00",
    "split": "equal",
    "participants": [{"user_id": i, "paid": "100.00" if i == 1 else "0.00"} for i in (1, 2, 3)],
}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.rsplit("/api/v3.0/", 1)[-1]
    responses = {
        "get_current_user": {"user": PEOPLE[0]},
        "get_groups": {"groups": [GROUP]},
        "get_group/10": {"group": GROUP},
        "get_friends": {"friends": PEOPLE[1:]},
        "get_expenses": {"expenses": []},
        "get_expense/42": {"expense": EXPENSE},
        "get_currencies": {"currencies": [{"currency_code": c} for c in ("INR", "USD", "EUR")]},
    }
    if request.method != "GET":
        return httpx.Response(403, json={"errors": ["Fixture CLI is read-only"]})
    return httpx.Response(200, json=responses[path]) if path in responses else httpx.Response(404)
