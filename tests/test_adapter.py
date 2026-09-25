import json

import httpx
import pytest

from splitwise_mcp.errors import AppError
from splitwise_mcp.fixtures import EXPENSE, handler
from splitwise_mcp.models import ExpenseQuery
from splitwise_mcp.upstream import MAX_BYTES, Splitwise, retry_delay


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    async def noop(_):
        pass

    monkeypatch.setattr("splitwise_mcp.upstream.asyncio.sleep", noop)


@pytest.mark.parametrize(
    ("status", "code", "count"),
    [
        (401, "invalid_credentials", 1),
        (403, "access_denied", 1),
        (404, "unavailable", 1),
        (429, "rate_limited", 3),
        (500, "upstream_failure", 3),
        (302, "redirect_rejected", 1),
    ],
)
async def test_http_errors(status, code, count):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"location": "https://evil.invalid", "retry-after": "0"}
        )

    api = Splitwise("secret", httpx.MockTransport(respond))
    with pytest.raises(AppError, match=code):
        await api.current_user()
    assert len(calls) == count
    assert all(r.url.host == "secure.splitwise.com" for r in calls)
    await api.close()


@pytest.mark.parametrize(
    "body", [{"errors": ["SECRET body"]}, {"user": []}, {}, [1], {"user": {"id": "invalid"}}]
)
async def test_application_and_schema_errors(body):
    api = Splitwise("secret", httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    with pytest.raises(AppError) as exc:
        await api.current_user()
    assert "SECRET" not in str(exc.value)
    await api.close()


async def test_timeout_and_no_write_retry():
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret")

    api = Splitwise("secret", httpx.MockTransport(timeout))
    with pytest.raises(AppError, match="network_timeout"):
        await api.current_user()
    assert len(calls) == 3
    calls.clear()
    with pytest.raises(AppError, match="unknown_outcome"):
        await api.create({"cost": "1.00"})
    assert len(calls) == 1
    await api.close()


async def test_encoding_filters_and_projection():
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            assert json.loads(request.content) == {"cost": "1.00", "users__0__user_id": 1}
            return httpx.Response(200, json={"expenses": [{"id": 99}], "errors": {}})
        return handler(request)

    api = Splitwise("secret", httpx.MockTransport(respond))
    user = await api.current_user()
    assert "email" not in user.model_dump()
    assert await api.expenses(ExpenseQuery(group_id=10, limit=2, offset=4)) == []
    assert dict(requests[-1].url.params) == {"group_id": "10", "limit": "2", "offset": "4"}
    assert await api.create({"cost": "1.00", "users__0__user_id": 1}) == 99
    assert requests[-1].headers["content-type"] == "application/json"
    assert requests[-1].headers["authorization"] == "Bearer secret"
    await api.close()


@pytest.mark.parametrize(
    "body",
    [
        {"expenses": [], "errors": ["bad"]},
        {"expenses": [{"id": 9}], "errors": ["partial"]},
        {"expenses": []},
        {"expenses": [{"id": 1}, {"id": 2}]},
    ],
)
async def test_mutation_response_semantics(body):
    api = Splitwise("secret", httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    with pytest.raises(AppError):
        await api.create({"cost": "1"})
    await api.close()


async def test_deleted_and_large_response():
    api = Splitwise(
        "secret",
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"expense": {**EXPENSE, "deleted_at": "today"}})
        ),
    )
    with pytest.raises(AppError, match="unavailable"):
        await api.get_expense(42)
    await api.close()
    api = Splitwise(
        "secret", httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * (MAX_BYTES + 1)))
    )
    with pytest.raises(AppError, match="response_too_large"):
        await api.current_user()
    await api.close()


async def test_empty_groups_and_malformed_json():
    api = Splitwise(
        "secret", httpx.MockTransport(lambda _: httpx.Response(200, json={"groups": []}))
    )
    assert await api.groups() == []
    await api.close()
    api = Splitwise(
        "secret", httpx.MockTransport(lambda _: httpx.Response(200, content=b"{not-json"))
    )
    with pytest.raises(AppError, match="upstream_schema"):
        await api.current_user()
    await api.close()


def test_retry_after():
    assert retry_delay("2", 0) == 2
    with pytest.raises(AppError, match="rate_limited"):
        retry_delay("1000", 0)
    assert 0.25 <= retry_delay("bad", 0) <= 0.35


@pytest.mark.parametrize("errors", [None, [], "", False])
async def test_missing_or_wrong_errors_field_never_confirms_success(errors):
    api = Splitwise(
        "secret",
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"expenses": [{"id": 9}], "errors": errors})
        ),
    )
    with pytest.raises(AppError, match="unknown_outcome"):
        await api.create({"cost": "1.00"})
    await api.close()


async def test_long_description_is_not_silently_truncated():
    api = Splitwise(
        "secret",
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"expense": {**EXPENSE, "description": "x" * 201}})
        ),
    )
    with pytest.raises(AppError, match="upstream_schema"):
        await api.get_expense(42)
    await api.close()
