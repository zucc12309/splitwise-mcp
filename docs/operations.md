# Storage, Render and recovery

## Local persistence

SQLite is created/migrated automatically on local startup. Set `SW_DATABASE` to a private absolute path on durable local storage. Schema v1 adds only `sw_schema` and `sw_operations`; additive schema v2 adds the approval expiry column. Existing v1 records are retained. Migration is idempotent and tested on both SQLite and PostgreSQL, including preservation of unrelated SQLite tables. Business logic uses neither LifePilot's fact-store tables nor LifeAdmin's database.

For PostgreSQL, install the locked dependencies (including psycopg), provision a dedicated schema/database role out of band and supply a connection URI. Remote startup checks schema version but **never runs migrations automatically**. When you have explicitly authorized a migration on the target database, run:

```sh
.venv/bin/splitwise-mcp migrate
```

This command uses `SW_DATABASE`; verify that target privately first. It was run only against temporary local databases during development. Use a migration role with DDL permissions and a runtime role with access limited to these two tables. PostgreSQL transactions use a five-second connect/statement timeout; local SQLite uses short transactions with a five-second busy timeout. Database operations run in worker threads, not the async event loop.

Back up SQLite with its online backup API, or stop the process before copying all database files; copying a live main file without its WAL is unsafe. Keep encrypted, access-controlled PostgreSQL backups using your provider's supported method. Test restoration to a separate local/test target. Never restore a stale ledger and re-enable writes without reconciling expenses created since the backup—this can defeat duplicate prevention.

## Optional Render setup (configuration prepared, not deployed)

`render.yaml` defines a **separate free web service**, without provisioning a database. Its initial `SW_SETUP_ONLY=true` deployment opens no database and serves a registration homepage, privacy page and setup health status. All MCP requests are rejected with HTTP 503. This is a setup deployment, not a connected Splitwise service. Auto-deploy is off so pushed changes require an intentional deployment. The new-folder decision keeps its upstream credential and approval keys away from existing app users and preserves existing startup behavior. Costs are an extra service's resource usage and deployment setup. Mounting into the existing FastAPI service could avoid another process, but would require a deliberate authenticated integration and lifecycle review; it is not wired through `/commerce` or testing OTP authentication.

Before deployment:

1. Choose an existing suitable durable PostgreSQL database or external provider. Use a dedicated role/schema and backups. Never point `SW_DATABASE` at Render's ephemeral filesystem. Do not rely on a temporary/free database's expiry lifecycle for financial execution state.
2. Set `SW_DATABASE=postgresql://...?...` with `sslmode=verify-full`; configure the provider's trusted CA (for example via `sslrootcert` or appropriate libpq environment). The URI and password are secret. Verify DNS/certificates instead of disabling certificate validation.
3. Review and explicitly run the additive migration on that database; this remains a user-authorized deployment step, not something performed here.
4. Configure `SW_OWNER`, `SW_ACCOUNT_ID`, and `SW_API_KEY` privately. Set `SW_REMOTE=true`, `SW_ENABLE_WRITES=false`, and `SW_ALLOWED_HOST` to the exact assigned hostname (no scheme/path).
5. Generate a unique random caller bearer token of at least 32 random bytes using your secret manager. Put its SHA-256 hex digest in `SW_CALLER_TOKEN_SHA256`, and inject the original token only into your MCP client's `Authorization: Bearer ...` header. Do not use a password, Splitwise key or existing application JWT. Server configuration cannot measure entropy from a hash; token generation is the operator's responsibility.
6. Build/start commands are in the blueprint. The process binds `0.0.0.0` and uses Render's assigned `PORT`. `/health` is a static, secret-free liveness response. It is not a database readiness or Splitwise account check.
7. Set `SW_SETUP_ONLY=false` only after all the preceding configuration and migration steps. Restart and use an HTTP MCP client that supports explicit bearer headers at `https://<host>/mcp`. Check initialization, discovery and read-only invocation. Browser CORS and automatic OAuth discovery are intentionally unsupported.
8. Keep writes disabled until independent human approval signing and durable state/backups are configured and reviewed. Do not run a real expense test without explicit approval for that draft.

Render's free web instances sleep after 15 idle minutes and may take about a minute to wake. Their filesystem is ephemeral, and free instance hours are shared within a workspace (currently 750 per month). No keep-alive traffic is added to evade these limits. Account for the existing backends sharing that budget. [Official free-instance guidance](https://render.com/docs/free).

SIGTERM uses Uvicorn's graceful shutdown with a 30-second limit. Any interrupted reserved write remains blocked and later becomes unknown. Stateless HTTP clients reconnect/reinitialize after a cold start; never automatically rerun a create tool after a connection loss. [Render web-service requirements](https://render.com/docs/web-services).

## Duplicate prevention and unknown outcomes

The durable ledger uniquely constrains `(owner, operation_key)`. The persisted approval deadline is enforced inside the reservation transaction and again immediately before the POST. Fresh valid evidence can replace an earlier grant only before submission. The request hash detects reuse with another proposal/account. Draft contents are canonicalized and hashed, and their hash is checked again when loaded. Signed approval is bound to that draft; a conditional transaction performs the single reservation:

`pending_approval | approved -> submitting -> succeeded | failed | unknown_outcome`

The MCP creation path accepts verified approval and reserves submission atomically. `approved` is retained for interrupted older workflows and trusted external approval interfaces. Status is read locally using caller/owner/account binding, so an upstream outage cannot hide the saved outcome.

After reservation, exactly one POST is attempted. Reads may retry; writes do not. A network timeout, oversized/malformed success response, redirect or server error after POST is treated conservatively as uncertain. A crash after upstream success but before local persistence leaves `submitting`; after its 120-second lease, status/create access transitions it to `unknown_outcome`. Another running process cannot reserve it again. Restart after approval preserves approval and the original draft.

This is **at-most-one local submission attempt per retained operation key, not guaranteed exactly-once delivery**. Splitwise's documented API provides no idempotency guarantee used here. A user deliberately creating another operation key for the same expense can still duplicate it. Restoring/deleting the ledger can also defeat the guarantee. The adapter never tries a search-and-repost heuristic.

For `unknown_outcome`:

1. Stop trying creation. Use `splitwise_get_operation_status` and preserve the draft/operation ledger.
2. Check the real Splitwise app manually, or explicitly read bounded expense pages around the draft's date/group. Compare payer IDs, all owed shares, amount, currency and description; a similar-looking record is not authoritative proof.
3. If a record exists, record its ID in your own reconciliation notes and leave the original operation blocked. No MCP tool can change its state or delete the upstream record.
4. If it is still uncertain, do not create another expense. Resolve with Splitwise or a human operator first. A new draft/key must be an intentional, newly approved action after that review.

There is no automatic or model-controlled reconciliation endpoint in v1. In-flight/unknown drafts are excluded from pruning.

## Rotation, disconnect, reset and troubleshooting

- Rotate the Splitwise API key on the app details page, update the private environment and restart. Account binding remains enforced; changing accounts requires a deliberately configured owner/account pair.
- Rotate the caller token by replacing its configured hash and client secret, then restart. There is no token refresh service.
- Rotate the approval public key after replacing the independent signing key. Existing evidence from the old key will no longer verify; obtain new approval when necessary.
- Disconnect by removing the MCP host entry, stopping the service and revoking the Splitwise key. None of these delete upstream records.
- For complete local erasure, first disconnect and resolve unknown operations, then remove the private SQLite database, WAL/SHM files and private backups. This erases duplicate history: do not re-enable writes using old operation keys or old restored state. Remove any captured previews/approvals from the host as appropriate.
- `configuration`: required settings missing, remote storage not PostgreSQL/TLS-verified, or invalid key/host settings. Values are suppressed; inspect configuration privately.
- `invalid_credentials` / `access_denied` / `account_mismatch`: verify app access conditions, key rotation, expected account ID and group membership. Do not disable owner checks.
- `rate_limited`: read retries are bounded; Retry-After above five seconds returns immediately for a later caller-controlled read. Do not run polling loops.
- `persistence_unavailable`: check credentials, TLS, schema migration and role permissions. Never switch to ephemeral SQLite to make remote startup pass.
- `upstream_schema` / `response_too_large`: upstream shape changed or a bounded response cannot be represented; no empty success is returned. Narrow the page or review the adapter.
- `writes_disabled` / `invalid_approval`: use previews until an independent signer is configured; `confirmed=true` cannot fix this.
- Cold start or interrupted response: reconnect for reads; check operation status before any further create action.
