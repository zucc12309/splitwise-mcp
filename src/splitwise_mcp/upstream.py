"""Fixed-origin, bounded Splitwise v3 adapter. Mutations are NEVER retried."""

import asyncio
import json
import random
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import ValidationError

from .errors import AppError
from .models import Debt, Expense, ExpenseQuery, Group, Participant, Person

ORIGIN = "https://secure.splitwise.com/api/v3.0/"
MAX_BYTES = 2_000_000


def person(raw: dict[str, Any]) -> Person:
    return Person(
        id=raw["id"],
        name=" ".join(
            v for v in (raw.get("first_name"), raw.get("last_name")) if isinstance(v, str) and v
        ),
    )


def group(raw: dict[str, Any]) -> Group:
    return Group(id=raw["id"], name=raw["name"], members=[person(p) for p in raw["members"]])


def expense(raw: dict[str, Any]) -> Expense:
    return Expense(
        id=raw["id"],
        group_id=raw["group_id"],
        description=raw["description"],
        date=raw["date"],
        currency=raw["currency_code"],
        total=raw["cost"],
        participants=[
            Participant(user_id=p["user_id"], paid=p["paid_share"], owed=p["owed_share"])
            for p in raw["users"]
        ],
        deleted=raw.get("deleted_at") is not None,
    )


def retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = -1
        if 0 <= delay <= 5:
            return delay
        if delay > 5:
            # Do not retry sooner than requested; caller should try later.
            raise AppError("rate_limited", "Retry-After exceeds this tool's bounded retry budget.")
    return min(2.0, 0.25 * 2**attempt) + random.uniform(0, 0.1)


class Splitwise:
    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self.client = httpx.AsyncClient(
            headers={"Authorization": "Bearer " + api_key, "Accept": "application/json"},
            timeout=httpx.Timeout(10, connect=5, pool=5),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            trust_env=False,
            transport=transport,
        )
        self.slots = asyncio.Semaphore(4)

    async def close(self):
        await self.client.aclose()

    async def _request(self, endpoint: str, key: str, *, params=None, data=None) -> Any:
        mutation = data is not None
        for attempt in range(3 if not mutation else 1):
            try:
                async with self.slots, asyncio.timeout(20):
                    async with self.client.stream(
                        "POST" if mutation else "GET", ORIGIN + endpoint, params=params, json=data
                    ) as response:
                        status = response.status_code
                        if status == 429 or status >= 500:
                            if not mutation and attempt < 2:
                                delay = retry_delay(response.headers.get("retry-after"), attempt)
                            else:
                                raise AppError(
                                    "unknown_outcome"
                                    if mutation and status >= 500
                                    else "rate_limited"
                                    if status == 429
                                    else "upstream_failure"
                                )
                        else:
                            delay = None
                        if delay is None:
                            if 300 <= status < 400:
                                raise AppError(
                                    "unknown_outcome" if mutation else "redirect_rejected"
                                )
                            if status in (401, 403, 404, 400, 422):
                                raise AppError(
                                    {
                                        401: "invalid_credentials",
                                        403: "access_denied",
                                        404: "unavailable",
                                        400: "upstream_rejected",
                                        422: "upstream_rejected",
                                    }[status]
                                )
                            if status != 200:
                                raise AppError(
                                    "unknown_outcome" if mutation else "upstream_failure"
                                )
                            body = bytearray()
                            async for chunk in response.aiter_bytes():
                                body.extend(chunk)
                                if len(body) > MAX_BYTES:
                                    raise AppError(
                                        "unknown_outcome" if mutation else "response_too_large"
                                    )
                            try:
                                result = json.loads(body)
                                if not isinstance(result, dict):
                                    raise ValueError
                                if mutation and not isinstance(result.get("errors"), dict):
                                    raise AppError("unknown_outcome")
                                if result.get("errors"):
                                    # A mutation containing both errors and records is ambiguous.
                                    raise AppError(
                                        "unknown_outcome"
                                        if mutation and result.get("expenses")
                                        else "upstream_rejected"
                                    )
                                value = result[key]
                                if not isinstance(value, (dict, list)):
                                    raise ValueError
                                return value
                            except (ValueError, KeyError, TypeError):
                                raise AppError(
                                    "unknown_outcome" if mutation else "upstream_schema"
                                ) from None
                if delay is not None:
                    await asyncio.sleep(delay)
            except (httpx.RequestError, TimeoutError):
                if mutation:
                    raise AppError(
                        "unknown_outcome", "Submission may have reached Splitwise; do not retry."
                    ) from None
                if attempt == 2:
                    raise AppError("network_timeout") from None
                await asyncio.sleep(retry_delay(None, attempt))
        raise AppError("upstream_failure")

    @staticmethod
    def _parse(fn, value):
        try:
            return fn(value)
        except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
            raise AppError("upstream_schema") from None

    async def current_user(self) -> Person:
        return self._parse(person, await self._request("get_current_user", "user"))

    async def groups(self) -> list[Group]:
        return self._parse(
            lambda rows: [group(x) for x in rows], await self._request("get_groups", "groups")
        )

    async def get_group(self, group_id: int) -> Group:
        result = self._parse(group, await self._request(f"get_group/{group_id}", "group"))
        if result.id != group_id:
            raise AppError("upstream_schema")
        return result

    async def friends(self) -> list[Person]:
        return self._parse(
            lambda rows: [person(x) for x in rows], await self._request("get_friends", "friends")
        )

    async def expenses(self, query: ExpenseQuery) -> list[Expense]:
        rows = await self._request(
            "get_expenses", "expenses", params=query.model_dump(mode="json", exclude_none=True)
        )
        if not isinstance(rows, list) or len(rows) > query.limit:
            raise AppError("upstream_schema")
        return self._parse(lambda values: [expense(x) for x in values], rows)

    async def get_expense(self, expense_id: int) -> Expense:
        result = self._parse(expense, await self._request(f"get_expense/{expense_id}", "expense"))
        if result.id != expense_id:
            raise AppError("upstream_schema")
        if result.deleted:
            raise AppError("unavailable", "Expense was deleted.")
        return result

    async def currencies(self) -> set[str]:
        return self._parse(
            lambda rows: {x["currency_code"] for x in rows},
            await self._request("get_currencies", "currencies"),
        )

    async def balances(self, group_id: int) -> list[Debt]:
        # original_debts gives explicit parties, without interpreting ambiguous net signs.
        raw = await self._request(f"get_group/{group_id}", "group")
        try:
            if raw["id"] != group_id:
                raise ValueError
            debts = []
            for item in raw["original_debts"]:
                amount = Decimal(item["amount"])
                if not isinstance(item["amount"], str) or not amount.is_finite() or amount < 0:
                    raise ValueError
                debts.append(
                    Debt(
                        debtor_id=item["from"],
                        creditor_id=item["to"],
                        currency=item["currency_code"],
                        amount=item["amount"],
                    )
                )
            return debts
        except (ValueError, KeyError, TypeError, InvalidOperation):
            raise AppError("upstream_schema") from None

    async def create(self, data: dict[str, str | int]) -> int:
        rows = await self._request("create_expense", "expenses", data=data)
        try:
            if len(rows) != 1 or type(rows[0]["id"]) is not int or rows[0]["id"] <= 0:
                raise ValueError
            return rows[0]["id"]
        except (KeyError, TypeError, ValueError):
            raise AppError("unknown_outcome") from None
