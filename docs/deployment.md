# Deployment record — 2026-09-25

The audit fixes are verified locally: 118 tests passed, including SQLite/PostgreSQL migration and concurrency, actual SDK protocol clients, six audit regressions, and locked setup-mode checks. Ruff lint/format, mypy (15 modules), pip check, pip-audit (no known vulnerabilities), wheel/sdist build, and both synthetic demonstrations passed. The blueprint is validated against Render's official JSON schema.

Initial deployment uses a free Singapore web service with SW_SETUP_ONLY=true and SW_ENABLE_WRITES=false. It is a registration homepage/privacy page only. MCP requests return 503; no Splitwise credential or database is opened. This is intentional until the owner registers the Splitwise app and privately configures the required credentials and durable database. No existing backend, production secret or deployed database has been modified.

Activation prerequisites: SW_OWNER, SW_ACCOUNT_ID, SW_API_KEY, SW_DATABASE with TLS-verified PostgreSQL, SW_CALLER_TOKEN_SHA256, SW_ALLOWED_HOST; an explicitly authorized schema-v2 migration; then SW_SETUP_ONLY=false. Keep writes disabled until an independent human-controlled approval signer is configured.

The callback URL on Splitwise app registration should remain blank because personal API-key authentication does not implement OAuth callbacks. Support can use https://github.com/zucc12309/splitwise-mcp/issues. Never post API keys or financial data to public issues.

Render deployment URL and live-check results will be added after verification.
