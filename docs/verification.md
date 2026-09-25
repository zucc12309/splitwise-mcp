# Verification record

Environment: macOS arm64, Python 3.14.3, official MCP SDK 1.30.0. No Splitwise credentials were loaded and no real records were modified. Tool and HTTP protocol tests used synthetic upstream responses. PostgreSQL tests used an isolated local PostgreSQL 17.9 cluster created for the test and stopped afterward; no deployed database was accessed.

Commands below were run from `/Users/priyanshupatel/Documents/GitHub/splitwise-mcp` unless otherwise stated.

| Command | Result |
|---|---|
| `.venv/bin/pytest -q` | 90 passed in 1.99 seconds (final full-suite run) |
| `.venv/bin/ruff check src tests tools examples` | Passed |
| `.venv/bin/ruff format --check src tests tools examples` | Passed; 25 files already formatted |
| `.venv/bin/mypy src` | No issues in 14 source files |
| `.venv/bin/python -m pip check` | No broken requirements |
| `.venv/bin/pip-audit --format json --output /tmp/splitwise-mcp-audit.json` | No known vulnerabilities after project-local pip update |
| `.venv/bin/python -m build` | Wheel and source distribution built |
| `.venv/bin/python examples/fixture_client.py` | Real stdio client discovered 10 tools and invoked reads/preview |
| `.venv/bin/python examples/synthetic_write.py` | Two create invocations, one mocked POST, zero network calls |

Initial development failures were fixed: display-name trailing whitespace; a temporary PostgreSQL Unix-socket path exceeding macOS's limit (test cluster now uses loopback TCP only); and a concurrency test exceeding the newly added four-call cap. These were new implementation/test issues, not pre-existing repository failures.

The first dependency audit reported eight advisory entries affecting the virtual environment's pip 26.0. Only the project-local pip was updated to 26.2.1; a repeat audit passed. No global tooling was installed.

Regression checks in existing repositories (no source changes):

```sh
# /Users/priyanshupatel/Documents/GitHub/lifepilot
.venv/bin/pytest tests/test_approval_gate.py tests/test_schemas.py tests/test_security_fixes.py -q
# 12 passed; one existing Starlette TestClient deprecation warning.

# /Users/priyanshupatel/Documents/GitHub/AI Life Admin OS/Lifeadmin0s/lifeadmin-backend
npm test -- --runTestsByPath tests/util/inr.test.js tests/services/piiRedaction.test.js
# 2 suites passed; 19 tests passed, 1 existing TODO.
```

These are selected relevant regression checks, not full existing-repository test suites. No pre-existing failures were observed in the selected checks.

Coverage includes integer money conservation and deterministic remainder; equal/explicit/multiple-payer cases; rejected precision, totals, duplicates and unverified currencies; upstream status/application/schema errors, redirects, body bounds and read retry limits; owner/account/cross-draft access; forged/expired/wrong-owner approvals; immutable payload conflict; SQLite/PostgreSQL migrations and concurrent reservation; restart after approval; timeout, cancellation and crash-after-success recovery with no second POST; clean stdio initialization/discovery/invocation/shutdown; HTTP bearer, host, origin, request-size and identity-header enforcement; tool schema rejection, secret canaries and untrusted text remaining data.

Unverified: real-account connectivity, Splitwise account-specific permissions/Pro conditions, a real human's independently hosted signer, real create responses, Render provisioning/TLS/cold-start behavior, and third-party MCP host compatibility. Mocked protocol tests do not establish live E2E behavior.

Final repository status checks remained clean in both LifePilot and LifeAdmin. Live credential availability was checked by presence only: required environment values were absent and no local `.env` existed. Therefore the live read-only smoke test was not run.
