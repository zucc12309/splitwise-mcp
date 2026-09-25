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


## Audit fixes and setup deployment verification — 2026-09-25

All six audit findings have dedicated regression coverage: nullable nongroup expense responses; approval expiration before reservation and before HTTP submission; locally available owner-bound operation status during upstream outage; truthful previews for succeeded/submitting/unknown/failed operations; renewed approval after persisted older evidence; and malformed collection rejection. Schema v1-to-v2 migration preserves rows and rejects future unknown versions. Balance access and data now use one group snapshot. The locked setup application rejects every tested MCP method/path with HTTP 503 and exposes no secret values.

Final commands and deployment status are recorded in docs/deployment.md. No deployed database migration is part of the setup-page deployment.

## Expanded verification — 2026-09-25

Re-ran the full suite after API-key setup was reported: **130 passed in 2.25 seconds, no skips**. The PostgreSQL fixture used an isolated temporary local cluster; no deployed database was accessed. Added 12 checks covering 1,000 deterministic generated allocations (1–30 participants, one-cent and maximum supported totals, multiple payers, conservation and order independence), malformed/duplicate/missing authentication headers, non-ASCII hosts, null Origin, identity injection, and caller-context cleanup after downstream failure.

Ruff lint and formatting (28 files), mypy (15 modules), dependency consistency, dependency vulnerability audit, and wheel/source build passed. The official SDK stdio demonstration discovered all 10 tools. The synthetic write demonstration made exactly one mocked POST for two execution requests, with zero real upstream network calls.

Live Render checks: `/`, `/privacy`, and `/health` returned 200 with `X-Content-Type-Options: nosniff`. Health explicitly reported `setup_required` and `mcp_enabled: false`. GET/POST/DELETE/OPTIONS/HEAD on `/mcp` and POST on `/mcp/nested` with an invalid synthetic bearer token returned 503. These are setup-lock checks, not proof of live configured-mode authentication. Configured-mode authentication and MCP protocol behavior passed locally against synthetic upstream data.

No new implementation defect was found. No real expense was created. The newly supplied Splitwise key was not retrieved or validated; setup mode deliberately does not use it. Real-account reads, deployed PostgreSQL/TLS, production caller authentication, external approval signing, and LifeAdmin end-to-end integration remain unverified until activation/integration prerequisites are complete. Earlier historical results above describe their original runs, not the current deployment state.
