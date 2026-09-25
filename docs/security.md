# Authentication, approval and privacy

The default is read-only plus stored previews. `SW_ENABLE_WRITES=false` is independent of whether an approval token is supplied. No MCP tool can approve, sign, edit drafts, change owner, fetch arbitrary URLs, execute shell commands or bypass the write flag.

## Owner boundary

Local stdio trusts the operating-system process launching it. Every tool call verifies the configured Splitwise account; the application service also requires its principal to equal `SW_OWNER`. The principal comes from the transport, never tool arguments. Local access to the owner's process/environment is privileged; this prototype is not a sandbox against an attacker with that access.

Remote mode uses a separate, high-entropy static bearer token whose SHA-256 hash is configured as `SW_CALLER_TOKEN_SHA256`. The exact token authenticates exactly one configured owner. It is **not OAuth or a JWT verifier**: there is no issuer/audience claim to parse, OAuth discovery, scope delegation, automatic token expiry or multi-user onboarding. Never reuse a token from another application, and rotate it manually. JWTs, LifeAdmin tokens, testing OTPs and the Splitwise key itself are not accepted as alternate caller authentication. Only explicit configuration of this dedicated token grants access.

The guard authenticates every request to `/mcp`, including initialize, notifications, discovery, calls, GET, DELETE and OPTIONS. Stateless transport has no reusable bearer session that bypasses authentication. `Host` must match exactly; browser Origin headers and injected identity headers are rejected. There is no CORS grant. `/health` returns only a static status without upstream calls. TLS terminates at Render; do not expose this HTTP process directly to an untrusted network outside a TLS reverse proxy. PostgreSQL requires `sslmode=verify-full` for remote configuration.

## Human-controlled approval

`approval.py` verifies Ed25519 evidence signed by a **separate human-controlled device/service inaccessible to the model and MCP host**. The private key must never be placed in this repository, the server's filesystem/environment, Render secrets, or any workspace the assistant can read. Only the public key belongs in `SW_APPROVAL_PUBLIC_KEY`. Without that independent signer, leave writes disabled. No signer or real key was configured during development.

A terminal prompt by itself is not trusted evidence: an agent with terminal access can answer it. The trust boundary below is private-key isolation plus a human review on the independent device. A malicious/compromised signing device, server administrator or MCP host with arbitrary server write access is outside this protection.

`tools/human_approve.py` is an optional standalone human interface, deliberately excluded from the installed server package and MCP command surface. On your **independent device**, install cryptography in a local environment, copy the reviewed script, then:

```sh
python human_approve.py keygen --key human-private.pem --out human-public.txt
```

It encrypts the private key with an interactively entered passphrase. Transfer only the public-key text to the server's `SW_APPROVAL_PUBLIC_KEY`. Enable writes only after verifying this separation and durable persistence.

After obtaining a preview through your trusted MCP host, save its complete `structuredContent` JSON as `preview.json` and review it independently. On the signing device:

```sh
python human_approve.py approve --key human-private.pem \
  --preview preview.json --owner your-private-owner-label \
  --account 123456 --out approval.approval
```

The interface checks the owner/account and canonical draft hash, displays escaped JSON (so names cannot inject terminal controls), requires typing `APPROVE` plus the full draft ID, then signs for at most five minutes. Transfer the resulting evidence through the host's protected input to `splitwise_create_expense`; don't publish it or put it in logs. Signing itself does not post. An operator must explicitly approve each exact real expense; no real operation is approved by this setup guide.

Evidence binds protocol version, owner, Splitwise account, draft ID, canonical draft hash, operation `create_expense`, expiry and nonce. The server verifies the signature before reserving, and rechecks access, group/member identity and currency availability. Material changes require a new preview. A changed proposal requires a new operation key and approval. Acceptance of verified approval and reservation are one atomic conditional update. The approval deadline is enforced in that transaction and immediately before the HTTP request. A fresh grant can replace an old one only for a draft not yet submitted; signature reuse cannot produce a second submission.

## Privacy and secret handling

Reads return IDs, display names, group membership, expense descriptions/dates, currency and paid/owed shares as requested. These data become visible to the calling assistant and its host; their retention/privacy policies apply. No emails, photos, contact lists beyond requested friend IDs/names, raw upstream bodies, comments or unnecessary user metadata are returned. Descriptions and names are data, never executed instructions.

The server has no analytics or internal LLM calls. Upstream credentials are sent only to the fixed HTTPS Splitwise API origin, not to the MCP client. Caller Authorization headers are never forwarded. Redirects and environment HTTP proxies are disabled; TLS verification remains enabled.

SQLite files are mode 0600, with new parent directories mode 0700 and restrictive process umask. Use OS disk encryption and private directories; these permissions are not database encryption. PostgreSQL storage and backups need the operator's access controls. Logs contain only known tool name, duration, status code and random correlation ID—not inputs, bodies, credentials or approval evidence.

Drafts expire after 15 minutes. Run `splitwise-mcp prune` as an operator maintenance command to scrub financial draft details older than 30 days while preserving the minimal duplicate-prevention ledger. Unknown/in-flight records are retained for reconciliation. There is no automatic background job. See the operations guide before resetting or restoring a database.
