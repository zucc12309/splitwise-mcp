# Inspection and official-documentation record

Checked on 2026-09-24. These are source observations, not live-account verification.

## Existing repositories

- LifePilot was located and inspected at `/Users/priyanshupatel/Documents/GitHub/lifepilot`. Python ≥3.11, setuptools `pyproject.toml`, FastAPI API, HTTPX/Pydantic, pytest/pytest-asyncio, Ruff/mypy; SQLite fact-store with optional asyncpg backend. Existing auth accepts setup tokens and LifeAdmin JWTs. Its Render blueprint uses Docker and demo SQLite. Existing commerce/MCP code is a Swiggy client, not an appropriate shared personal-credential authorization boundary.
- LifeAdmin was inspected at `/Users/priyanshupatel/Documents/GitHub/AI Life Admin OS/Lifeadmin0s`. Node/Express, npm lockfile, Jest, pg/PostgreSQL, JWT/OTP routes and a commerce proxy. Code and tests were inspected, without reading secret values.
- Both git working trees were clean at initial inspection. No applicable AGENTS.md was found in the inspected ancestors or repositories. No Flutter, OTP, auth, backend or Render files in either repository were edited.
- The initial isolated-LifePilot-module plan was superseded by the user's explicit instruction to create a new folder under GitHub. This package is standalone and not a duplicated deployed LifePilot backend.

## Verified upstream contract

[Official API reference](https://dev.splitwise.com/) and [official OpenAPI security definitions](https://github.com/splitwise/api-docs/blob/main/splitwise.yaml): personal bearer API key; OAuth 2 authorization-code flow also documented. No refresh flow is assumed. App registration requires sign-in at [Splitwise apps](https://secure.splitwise.com/apps).

[Expense creation definition](https://github.com/splitwise/api-docs/blob/main/paths/create_expense.yaml): JSON body, explicit flattened `users__N__user_id/paid_share/owed_share` shares, and response-level `errors` despite HTTP 200. [Share schema](https://github.com/splitwise/api-docs/blob/main/schemas/expense/by_shares.yaml) and API cost documentation limit expense values to two decimals. v1 deliberately narrows currency creation support and checks `get_currencies`; it does not assume all ISO currencies have two digits.

Expense filters use limit/offset, group/friend, dated and updated bounds; upstream ignores friend when group is supplied, so this server rejects that combination. Rates/access limits can change; no fixed request quota or free access is promised. Personal/prototype access may require Pro. No documented upstream idempotency/webhook guarantee is relied upon.

## MCP and Render

[Official MCP server guide](https://modelcontextprotocol.io/docs/develop/build-server), [Python SDK 1.x branch](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x), and [SDK authorization guide](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/docs/authorization.md) were checked. v2 is the current stable SDK; 1.x remains maintained for critical/security fixes. This project pins 1.30.0 and uses its actual installed stdio and Streamable HTTP APIs, with explicit schemas and CallToolResult errors. Compatibility was exercised through its SDK client, not inferred from README text. Static-token remote mode does not claim the full MCP OAuth authorization profile.

[Render free-instance docs](https://render.com/docs/free), [web-service lifecycle/port docs](https://render.com/docs/web-services), [FastAPI deployment](https://render.com/docs/deploy-fastapi), and [PostgreSQL connection guidance](https://render.com/docs/postgresql-creating-connecting) informed the opt-in blueprint. Remote state uses external PostgreSQL; no new service/database has been provisioned.
