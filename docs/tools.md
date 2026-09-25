# Tool contracts and examples

The server publishes closed input and output JSON schemas. See `tool-schemas.json` for the exact generated contracts. Unknown fields are rejected, including owner, confirmed, URL and payload fields on creation. Tool failures use MCP `isError=true` with a stable `code`, sanitized `message` and random correlation ID; they are never successful empty lists.

| Tool | Example input | Output / source |
|---|---|---|
| `splitwise_get_current_user` | `{}` | `{ "id": 1, "name": "Demo Owner" }` from `GET get_current_user` |
| `splitwise_list_groups` | `{"limit":20,"offset":0}` | `items`, `next_offset`, `truncated`; `GET get_groups` |
| `splitwise_get_group` | `{"group_id":10}` | Group ID/name and member IDs/names; `GET get_group/10` |
| `splitwise_list_friends` | `{"limit":20}` | Friend slice with `next_offset`, `truncated`; `GET get_friends` |
| `splitwise_list_expenses` | `{"group_id":10,"limit":20,"offset":0}` | One page, `next_offset`, `has_more`; `GET get_expenses` |
| `splitwise_get_expense` | `{"id":42}` | Description, date, currency, total and paid/owed shares; `GET get_expense/42` |
| `splitwise_get_balances` | `{"group_id":10}` | `debts` with `debtor_id`, `creditor_id`, currency, amount; group's `original_debts` |
| `splitwise_preview_expense` | Full proposal below | Immutable draft and financial preview; local persistence only |
| `splitwise_create_expense` | `{"draft_id":"stored-id","approval":"externally-signed-evidence"}` | State and expense ID; `POST create_expense` at most once per operation |
| `splitwise_get_operation_status` | `{"draft_id":"stored-id"}` | Owner/account-bound durable state, failure category, guidance |

Endpoint mapping follows the [official API reference](https://dev.splitwise.com/). Draft/status/approval are this package's concepts, not invented upstream endpoints.

Expenses support `group_id` OR `friend_id` and timezone-qualified `dated_after`, `dated_before`, `updated_after`, `updated_before`. An after/before pair must be ordered. A full page returns `has_more: "unknown"`; the caller may explicitly request the next page. At the offset cap, `next_offset` is null even if more records might exist. Groups/friends are local slices of one size-bounded upstream response; no upstream pagination is claimed for them. Empty lists are valid only after successful, validated upstream responses. Deleted single expenses report `unavailable`; history rows retain a `deleted` flag.

Balances are group-specific original debts, including parties who may be netted differently by Splitwise's simplified view. No account-wide net total is claimed. `group_id=0` is rejected for balances; the tool does not infer nongroup direction from ambiguous net signs or partially fetched history. It never sums across currencies.

Example preview:

```json
{
  "operation_key": "synthetic-lunch-001",
  "group_id": 10,
  "description": "Synthetic lunch",
  "date": "2026-09-24T12:00:00Z",
  "currency": "INR",
  "total": "100.00",
  "split": "equal",
  "participants": [
    {"user_id":1,"paid":"100.00"},
    {"user_id":2,"paid":"0.00"},
    {"user_id":3,"paid":"0.00"}
  ]
}
```

The output has `draft_id`, `expires_at` (Unix seconds, 15-minute TTL), `owner`, `account`, `group`, normalized `proposal`, `allocations`, `draft_hash`, warnings and `posted:false`. The normalized paid shares are `100.00 / 0.00 / 0.00`; owed shares are `33.34 / 33.33 / 33.33`. Allocations show one extra paise assigned to ID 1. ₹1,200 splits into ₹400 each. Participant ordering is normalized by ID, and integer arithmetic preserves every paise.

An explicit split with two payers uses `split:"explicit"` and participants `[{"user_id":1,"paid":"60.00","owed":"20.00"},{"user_id":2,"paid":"40.00","owed":"80.00"}]` for a `100.00` total. Equal mode rejects caller-supplied owed amounts; explicit mode requires them all.

Successful synthetic creation:

```json
{
  "draft_id": "generated-draft-id",
  "state": "succeeded",
  "expense_id": 999,
  "error_code": null,
  "guidance": "Previously confirmed success; this operation will never submit again."
}
```

A repeated approved request returns the persisted success while evidence is valid; after evidence expires, use the status tool. An in-flight call returns `submitting`. `unknown_outcome` and definitive failures are tool errors on creation and are visible as explicit states through status.
