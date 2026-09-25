import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from splitwise_mcp.fixtures import PROPOSAL


async def test_real_stdio_protocol(tmp_path):
    env = {
        "PATH": os.environ["PATH"],
        "SW_OWNER": "fixture-owner",
        "SW_ACCOUNT_ID": "1",
        "SW_API_KEY": "SECRET_PROTOCOL_CANARY",
        "SW_DATABASE": str(tmp_path / "stdio.sqlite"),
        "SW_FIXTURE": "true",
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "splitwise_mcp"], env=env)
    with (tmp_path / "stderr.log").open("w+") as errors:
        async with (
            stdio_client(params, errlog=errors) as (read, write),
            ClientSession(read, write) as client,
        ):
            init = await client.initialize()
            assert init.serverInfo.name == "personal-splitwise"
            tools = (await client.list_tools()).tools
            assert len(tools) == 10
            assert not any("approve" in t.name for t in tools)
            assert all(t.inputSchema.get("additionalProperties") is False for t in tools)
            assert all(t.outputSchema for t in tools)
            result = await client.call_tool("splitwise_get_current_user", {})
            assert not result.isError
            assert result.structuredContent == {"id": 1, "name": "Demo Owner"}
            assert "email" not in str(result)
            p = await client.call_tool("splitwise_preview_expense", PROPOSAL)
            assert not p.isError, p
            assert p.structuredContent["posted"] is False
            draft = p.structuredContent["draft_id"]
            status = await client.call_tool("splitwise_get_operation_status", {"draft_id": draft})
            assert status.structuredContent["state"] == "pending_approval"
            for name, arguments in [
                ("splitwise_get_current_user", {"owner": "attacker"}),
                ("splitwise_list_expenses", {"limit": 500}),
                ("splitwise_create_expense", {"draft_id": draft, "confirmed": True}),
                (
                    "splitwise_create_expense",
                    {"draft_id": draft, "approval": "fake-approval-evidence"},
                ),
                ("splitwise_approve_expense", {"draft_id": draft}),
            ]:
                failure = await client.call_tool(name, arguments)
                assert failure.isError
                assert "SECRET_PROTOCOL_CANARY" not in str(failure)
            for name, args in [
                ("list_groups", {}),
                ("get_group", {"group_id": 10}),
                ("list_friends", {}),
                ("list_expenses", {}),
                ("get_expense", {"id": 42}),
                ("get_balances", {"group_id": 10}),
            ]:
                result = await client.call_tool("splitwise_" + name, args)
                assert not result.isError, result
        errors.seek(0)
        logs = errors.read()
        assert "SECRET_PROTOCOL_CANARY" not in logs
        assert "Synthetic lunch" not in logs
        assert "fake-approval" not in logs
        # Successful SDK parsing through shutdown also proves stdout wasn't contaminated.


@pytest.mark.parametrize(
    "env",
    [{}, {"SW_OWNER": "x", "SW_ACCOUNT_ID": "1", "SW_API_KEY": "secret", "SW_REMOTE": "true"}],
)
def test_startup_fails_closed(env, tmp_path):
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "splitwise_mcp"],
        env={"PATH": os.environ["PATH"], "SW_DATABASE": str(tmp_path / "state.sqlite"), **env},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "configuration" in result.stderr
    assert "secret" not in result.stderr


async def test_sdk_approved_execution_and_errors(make_service, sign):
    import httpx
    from mcp.shared.memory import create_connected_server_and_client_session

    from splitwise_mcp.fixtures import handler
    from splitwise_mcp.models import Preview
    from splitwise_mcp.server import build_server, principal

    posts = []

    def respond(request):
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(200, json={"expenses": [{"id": 555}], "errors": {}})
        return handler(request)

    service = make_service(respond)
    token = principal.set("owner")
    try:
        async with create_connected_server_and_client_session(build_server(service)) as client:
            result = await client.call_tool("splitwise_preview_expense", PROPOSAL)
            assert not result.isError
            preview = Preview.model_validate(result.structuredContent)
            evidence = sign(preview)
            for _ in range(2):
                result = await client.call_tool(
                    "splitwise_create_expense", {"draft_id": preview.draft_id, "approval": evidence}
                )
                assert not result.isError
                assert result.structuredContent["expense_id"] == 555
            assert len(posts) == 1
            invalid = await client.call_tool(
                "splitwise_preview_expense", {**PROPOSAL, "date": 1800000000}
            )
            assert invalid.isError
            invalid = await client.call_tool(
                "splitwise_get_current_user", {"secret": "SECRET_CANARY_DO_NOT_ECHO"}
            )
            assert invalid.isError
            assert "SECRET_CANARY_DO_NOT_ECHO" not in str(invalid)
            invalid = await client.call_tool("splitwise_get_current_user", {"extra": "x" * 33000})
            assert invalid.isError
            assert "request_too_large" in str(invalid)
    finally:
        principal.reset(token)
        await service.upstream.close()
