import hashlib
import time
from copy import deepcopy

import httpx
import pytest

from splitwise_mcp.errors import AppError
from splitwise_mcp.fixtures import EXPENSE, PROPOSAL, handler
from splitwise_mcp.models import DraftRef, Execute, ExpenseQuery, Proposal
from splitwise_mcp.public import setup_app
from splitwise_mcp.store import DDL, Store
from splitwise_mcp.upstream import Splitwise


async def preview(service, key="audit-case-001"):
    return await service.call(
        "preview_expense",
        Proposal.model_validate({**deepcopy(PROPOSAL), "operation_key": key}),
        "owner",
    )


async def test_nongroup_single_and_mixed_history():
    def respond(request):
        nongroup = {**EXPENSE, "group_id": None}
        return httpx.Response(
            200,
            json={"expenses": [EXPENSE, nongroup]}
            if request.url.path.endswith("get_expenses")
            else {"expense": nongroup},
        )

    api = Splitwise("synthetic", httpx.MockTransport(respond))
    try:
        assert (await api.get_expense(42)).group_id is None
        assert [e.group_id for e in await api.expenses(ExpenseQuery())] == [10, None]
    finally:
        await api.close()


@pytest.mark.parametrize(
    "field,method", [("groups", "groups"), ("friends", "friends"), ("currencies", "currencies")]
)
@pytest.mark.parametrize("wrong", [{}, {"id": 1}, None, "", 1])
async def test_collection_shapes_fail_closed(field, method, wrong):
    api = Splitwise(
        "synthetic", httpx.MockTransport(lambda _: httpx.Response(200, json={field: wrong}))
    )
    try:
        with pytest.raises(AppError, match="upstream_schema"):
            await getattr(api, method)()
    finally:
        await api.close()


@pytest.mark.parametrize(
    "state,posted",
    [("succeeded", True), ("submitting", None), ("unknown_outcome", None), ("failed", False)],
)
async def test_repeated_preview_reports_saved_outcome(make_service, store, state, posted):
    service = make_service()
    p = await preview(service)
    with store.transaction() as conn:
        conn.execute(
            "UPDATE sw_operations SET state=?,expense_id=?,lease_until=? WHERE id=?",
            (state, 999 if state == "succeeded" else None, int(time.time()) + 120, p.draft_id),
        )
    repeated = await preview(service)
    assert repeated.operation_state == state
    assert repeated.posted is posted
    assert "Nothing has been posted" not in repeated.notice
    if state == "succeeded":
        assert repeated.expense_id == 999


async def test_status_is_local_and_owner_bound_during_outage(make_service, store):
    service = make_service()
    p = await preview(service)
    calls = []

    def outage(request):
        calls.append(request)
        return httpx.Response(503)

    broken = make_service(outage)
    status = await broken.call("get_operation_status", DraftRef(draft_id=p.draft_id), "owner")
    assert status.state == "pending_approval"
    assert calls == []
    with pytest.raises(AppError, match="access_denied"):
        await broken.call("get_operation_status", DraftRef(draft_id=p.draft_id), "other")
    mismatched = make_service(outage, account_id=2)
    with pytest.raises(AppError, match="unavailable"):
        await mismatched.call("get_operation_status", DraftRef(draft_id=p.draft_id), "owner")
    assert calls == []


async def test_fresh_approval_recovers_expired_persisted_grant(make_service, store, sign):
    posts = []

    def respond(request):
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(200, json={"expenses": [{"id": 777}], "errors": {}})
        return handler(request)

    service = make_service(respond)
    p = await preview(service)
    old = sign(p)
    assert store.approve(
        "owner", 1, p.draft_id, hashlib.sha256(old.encode()).hexdigest(), int(time.time()) + 100
    )
    with store.transaction() as conn:
        conn.execute("UPDATE sw_operations SET approval_expires=1 WHERE id=?", (p.draft_id,))
    result = await service.call(
        "create_expense",
        Execute(draft_id=p.draft_id, approval=sign(p, nonce="renewed-human-evidence-001")),
        "owner",
    )
    assert result.state == "succeeded"
    assert result.expense_id == 777
    assert len(posts) == 1


async def test_expiry_between_verification_and_reservation(make_service, sign, store, monkeypatch):
    service = make_service()
    p = await preview(service)
    now = int(time.time())
    evidence = sign(p, expires_at=now + 1)
    reserve = store.reserve

    def delayed_reserve(*args):
        monkeypatch.setattr(time, "time", lambda: now + 2)
        return reserve(*args)

    monkeypatch.setattr(store, "reserve", delayed_reserve)
    with pytest.raises(AppError, match="invalid_approval"):
        await service.call(
            "create_expense", Execute(draft_id=p.draft_id, approval=evidence), "owner"
        )
    assert store.get("owner", 1, p.draft_id)["state"] == "pending_approval"


async def test_expiry_after_reservation_sends_no_post(make_service, sign, store, monkeypatch):
    posts = []

    def respond(request):
        if request.method == "POST":
            posts.append(request)
        return handler(request)

    service = make_service(respond)
    p = await preview(service)
    now = int(time.time())
    evidence = sign(p, expires_at=now + 1)
    reserve = store.reserve

    def delayed_return(*args):
        result = reserve(*args)
        monkeypatch.setattr(time, "time", lambda: now + 2)
        return result

    monkeypatch.setattr(store, "reserve", delayed_return)
    with pytest.raises(AppError, match="invalid_approval"):
        await service.call(
            "create_expense", Execute(draft_id=p.draft_id, approval=evidence), "owner"
        )
    assert posts == []
    assert store.get("owner", 1, p.draft_id)["state"] == "failed"


def test_version_one_migrates_without_losing_rows(tmp_path):
    store = Store(str(tmp_path / "v1.sqlite"))
    with store.transaction() as conn:
        for statement in DDL.split(";"):
            if statement.strip():
                conn.execute(statement)
    row = store.put("owner", 1, "migration-key-001", "hash", {"synthetic": True})
    store.migrate()
    store.migrate()
    store.check_schema()
    assert store.get("owner", 1, row["id"])["draft"] == {"synthetic": True}
    assert store.get("owner", 1, row["id"])["approval_expires"] is None


async def test_setup_mode_cannot_expose_mcp_or_secrets():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=setup_app()), base_url="http://test"
    ) as client:
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/privacy")).status_code == 200
        health = await client.get("/health")
        assert health.json() == {"status": "setup_required", "mcp_enabled": False}
        for method in ("GET", "POST", "DELETE", "OPTIONS"):
            for path in ("/mcp", "/mcp/session"):
                response = await client.request(
                    method, path, headers={"Authorization": "Bearer SECRET_CANARY"}
                )
                assert response.status_code == 503
                assert "SECRET_CANARY" not in response.text


async def test_balances_reuses_one_group_snapshot(make_service):
    from splitwise_mcp.models import ByGroup

    reads = []

    def respond(request):
        reads.append(request.url.path)
        return handler(request)

    result = await make_service(respond).call("get_balances", ByGroup(group_id=10), "owner")
    assert result.debts[0].debtor_id == 2
    assert reads.count("/api/v3.0/get_group/10") == 1


def test_future_migration_version_is_rejected(store):
    with store.transaction() as conn:
        conn.execute("INSERT INTO sw_schema(version) VALUES (99)")
    with pytest.raises(AppError, match="persistence_unavailable"):
        store.migrate()
