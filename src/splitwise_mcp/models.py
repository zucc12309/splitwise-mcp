from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Id = Annotated[int, Field(strict=True, gt=0, le=2**53 - 1)]
GroupId = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
Money = Annotated[
    str, StringConstraints(pattern=r"^(0|[1-9][0-9]{0,8})(\.[0-9]{1,2})?$", max_length=12)
]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Key = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{8,80}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "date",
        "dated_after",
        "dated_before",
        "updated_after",
        "updated_before",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def timestamps_are_strings(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("Timestamps must be ISO 8601 strings")
        return value


class Empty(Strict):
    pass


class ById(Strict):
    id: Id


class ByGroup(Strict):
    group_id: GroupId


class Page(Strict):
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20
    offset: Annotated[int, Field(strict=True, ge=0, le=10000)] = 0


class ExpenseQuery(Page):
    group_id: GroupId | None = None
    friend_id: Id | None = None
    dated_after: datetime | None = None
    dated_before: datetime | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None

    @model_validator(mode="after")
    def filters(self):
        if self.group_id is not None and self.friend_id is not None:
            raise ValueError("Use group_id OR friend_id; upstream ignores friend_id with a group")
        for prefix in ("dated", "updated"):
            start, end = getattr(self, prefix + "_after"), getattr(self, prefix + "_before")
            for value in (start, end):
                if value and (not value.tzinfo or value.year < 2000 or value.year > 2100):
                    raise ValueError("Use timezone-qualified timestamps between 2000 and 2100")
            if start and end and start >= end:
                raise ValueError("after must precede before")
        return self


class Participant(Strict):
    user_id: Id
    paid: Money
    owed: Money | None = None


class Proposal(Strict):
    operation_key: Key
    group_id: GroupId
    description: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    date: datetime
    currency: Currency
    total: Money
    split: Literal["equal", "explicit"]
    participants: Annotated[list[Participant], Field(min_length=1, max_length=30)]

    @model_validator(mode="after")
    def clean(self):
        if not self.description.strip() or any(ord(c) < 32 for c in self.description):
            raise ValueError("Description must be printable")
        if not self.date.tzinfo or not 2000 <= self.date.year <= 2100:
            raise ValueError("Use a timezone-qualified timestamp between 2000 and 2100")
        return self


class DraftRef(Strict):
    draft_id: Key


class Execute(DraftRef):
    approval: Annotated[str, StringConstraints(min_length=10, max_length=4096)]


# Output models are closed. Upstream objects are projected into these shapes.
class Person(Strict):
    id: Id
    name: Annotated[str, StringConstraints(max_length=200)]


class Group(Strict):
    id: GroupId
    name: Annotated[str, StringConstraints(max_length=200)]
    members: Annotated[list[Person], Field(max_length=200)]


class Expense(Strict):
    id: Id
    group_id: GroupId | None
    description: Annotated[str, StringConstraints(max_length=200)]
    date: str
    currency: Currency
    total: str
    participants: Annotated[list[Participant], Field(max_length=200)]
    deleted: bool


class Groups(Strict):
    items: list[Group]
    next_offset: int | None
    truncated: bool
    pagination: str = (
        "Local slice of one bounded upstream response; upstream has no list pagination."
    )


class Friends(Strict):
    items: list[Person]
    next_offset: int | None
    truncated: bool
    pagination: str = (
        "Local slice of one bounded upstream response; upstream has no list pagination."
    )


class Expenses(Strict):
    items: list[Expense]
    next_offset: int | None
    has_more: Literal["unknown", "no"]
    pagination: str = "One upstream page only; a full page does not prove another page exists."


class Debt(Strict):
    debtor_id: Id
    creditor_id: Id
    currency: Currency
    amount: str


class Balances(Strict):
    group_id: GroupId
    debts: list[Debt]
    direction: str = "Each debtor_id owes amount in currency to creditor_id."
    source: str = "Splitwise original_debts; currencies remain separate. No history-derived totals."


class Allocation(Strict):
    user_id: Id
    extra_minor_units: int


OperationState = Literal[
    "pending_approval", "approved", "submitting", "succeeded", "failed", "unknown_outcome"
]


class Preview(Strict):
    draft_id: str
    expires_at: int
    owner: str
    account: Person
    group: Group
    proposal: Proposal
    allocations: list[Allocation]
    draft_hash: str
    warnings: list[str]
    operation_state: OperationState
    expense_id: int | None
    posted: bool | None
    notice: str


class Operation(Strict):
    draft_id: str
    state: Literal[
        "pending_approval", "approved", "submitting", "succeeded", "failed", "unknown_outcome"
    ]
    expense_id: int | None
    error_code: str | None
    guidance: str
