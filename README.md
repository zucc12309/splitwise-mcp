# Personal Splitwise MCP

A standalone prototype in `/Users/priyanshupatel/Documents/GitHub/splitwise-mcp`, created at the user's requested location. Local stdio is the default. Reads and immutable expense previews work without enabling writes. Optional Streamable HTTP has separate owner authentication and requires PostgreSQL.

**Live Splitwise connectivity and expense creation have not been verified. All development calls used synthetic fixtures. No service was deployed or production database migrated.**

## Run the safe demonstration

Python 3.11+ is declared; Python 3.14.3 was tested. Dependencies are project-local. The lock files capture the tested versions; they are version pins, not a hash-verified supply-chain lock.

```sh
cd /Users/priyanshupatel/Documents/GitHub/splitwise-mcp
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python examples/fixture_client.py
.venv/bin/python examples/synthetic_write.py
```

The first demo launches a real SDK stdio client, discovers ten tools and invokes reads and a preview. The second signs a **synthetic** draft with an in-memory test key, executes against HTTPX MockTransport, and proves repeated execution creates one mocked expense. Neither opens a connection to Splitwise. The synthetic key is not a human approval mechanism.

To run a fixture MCP server directly:

```sh
SW_FIXTURE=true SW_OWNER=demo-owner SW_ACCOUNT_ID=1 \
SW_API_KEY=synthetic SW_DATABASE=/tmp/splitwise-demo.sqlite \
.venv/bin/splitwise-mcp serve
```

The server waits for MCP protocol input; it is not an interactive shell. stdout is protocol-only and sanitized operation logs go to stderr.

## Connect your account, read-only

1. Sign in to [Splitwise app registration](https://secure.splitwise.com/apps), register your personal integration and generate your own personal API key on its details page. Personal API keys use bearer authentication; upstream also documents OAuth 2 authorization-code flow, which this prototype does not implement. [Official authentication definition](https://github.com/splitwise/api-docs/blob/main/splitwise.yaml).
2. Review Splitwise's conditions. Personal/prototype access **may require Splitwise Pro**, and access/rate restrictions can change. Free API access is not promised. [Splitwise terms and API documentation](https://dev.splitwise.com/).
3. Use `.env.example` as a placeholder reference. Supply `SW_API_KEY` via your secret manager or a private shell environment; the program intentionally does not auto-load repository `.env` files. Do not paste credentials into chat or commit them. Obtain your numeric account ID through your authenticated account details or a one-time private read of `/api/v3.0/get_current_user`; never guess another person's ID. Set `SW_OWNER` to a private stable owner label and `SW_ACCOUNT_ID` to that ID.
4. Set `SW_DATABASE` to a private absolute SQLite path; leave `SW_REMOTE=false` and `SW_ENABLE_WRITES=false`.
5. Run the opt-in read-only smoke command from the environment containing those variables:

```sh
.venv/bin/splitwise-mcp smoke
.venv/bin/splitwise-mcp serve
```

`smoke` makes only the account-verification read and prints the minimal account ID/name. It never creates expenses. There is deliberately no live expense-creation smoke test.

MCP host stdio configuration (use your host's secret injection; don't put real credentials in this example):

```json
{
  "mcpServers": {
    "personal-splitwise": {
      "command": "/Users/priyanshupatel/Documents/GitHub/splitwise-mcp/.venv/bin/splitwise-mcp",
      "args": ["serve"],
      "env": {
        "SW_OWNER": "your-private-owner-label",
        "SW_ACCOUNT_ID": "123456",
        "SW_DATABASE": "/absolute/private/path/state.sqlite",
        "SW_REMOTE": "false",
        "SW_ENABLE_WRITES": "false"
      }
    }
  }
}
```

`SW_API_KEY` must be injected separately into the spawned process. Hosts differ in inherited environment handling; verify yours supplies it. Tested compatibility is the official MCP Python SDK 1.30.0 client, over stdio and Streamable HTTP. No specific desktop-host end-to-end compatibility is claimed. Remote clients must support a caller-supplied bearer header; OAuth-only clients are outside this prototype.

## Architecture and limits

- `config.py`: explicit environment configuration, fail-closed defaults.
- `upstream.py`: fixed Splitwise origin, typed projections, JSON POST, bounded responses/timeouts, read-only retry policy.
- `models.py` / `money.py`: closed schemas, verified IDs, integer minor units, deterministic allocation. Supports INR, USD, EUR, GBP, CAD, AUD, SGD; explicitly rejects JPY/KWD and all other currencies for draft creation.
- `service.py` / `approval.py`: owner/account checks, immutable preview, access revalidation, external Ed25519 approval verification and execution. Reusable without MCP objects.
- `store.py`: SQLite and PostgreSQL adapters with additive version-1 schema, transactions, unique operation keys and durable outcomes.
- `server.py` / `remote.py`: official SDK tools and optional authenticated ASGI transport.

No Redis, LLM, analytics, proxy, Flutter, or LifeAdmin/LifePilot startup changes. Dependencies of substance are the official MCP SDK, HTTPX/Pydantic, cryptography for approval verification, and optional psycopg for PostgreSQL. SDK 1.30.0 is on the supported 1.x maintenance line, pinned deliberately; v2 is the current stable line. [Official SDK release-line guidance](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x).

The same operation key must identify the same proposal. Account, group, currency, payer and participant IDs are explicit. Names never resolve identity: two Alexes remain two IDs for the human to disambiguate. v1 requires the owner among expense participants. All equal shares are sent explicitly so upstream equal-split defaults cannot change payer or rounding choices.

Boundaries: one expense page (1–50 items, offset ≤10,000), at most 30 draft participants, 200 members per returned group, 2 MB upstream body, 256 KB tool result, 32 KB tool arguments/HTTP request, four active tool calls and four upstream connections. Each read has at most three attempts; each attempt has a 20-second whole-response deadline and 5-second connect / 10-second I/O timeouts. A tool has a 90-second deadline. Oversized responses fail rather than silently returning partial authoritative data.

See [tool contracts and examples](docs/tools.md), [security and approval](docs/security.md), [Render/storage/recovery runbook](docs/operations.md), [documentation verification](docs/research.md), and [test results](docs/verification.md).

## Develop

```sh
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/pytest -q
.venv/bin/ruff check src tests tools examples
.venv/bin/ruff format --check src tests tools examples
.venv/bin/mypy src
.venv/bin/python -m pip check
.venv/bin/pip-audit
.venv/bin/python -m build
```

The PostgreSQL test starts and stops a new loopback-only cluster using already-installed PostgreSQL binaries. It never uses environment database credentials. If those binaries aren't installed, that one test is skipped; install no global tooling just to run the rest. Tests do not need Splitwise credentials or a paid account.

Deferred: multi-user linking, OAuth UI, settlements/payments, expense edits/deletes, group creation/invites, recurring/background posting, receipts, Flutter screens, exchange rates, automatic reconciliation, and integrated LifePilot authentication.
