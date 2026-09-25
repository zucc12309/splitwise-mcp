"""Integer minor units only. Narrow currency scope is intentional."""

from .errors import AppError
from .models import Allocation, Proposal

# All are two-decimal ISO currencies. JPY and KWD are deliberately outside v1.
CURRENCIES = frozenset({"INR", "USD", "EUR", "GBP", "CAD", "AUD", "SGD"})


def minor(value: str) -> int:
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0"))


def decimal(value: int) -> str:
    return f"{value // 100}.{value % 100:02d}"


def allocate(proposal: Proposal) -> tuple[Proposal, list[Allocation]]:
    if proposal.currency not in CURRENCIES:
        raise AppError(
            "unsupported_currency",
            "v1 supports INR/USD/EUR/GBP/CAD/AUD/SGD only; zero- and three-decimal currencies are rejected.",
        )
    total = minor(proposal.total)
    people = sorted(proposal.participants, key=lambda p: p.user_id)
    if total <= 0 or len({p.user_id for p in people}) != len(people):
        raise AppError("invalid_input", "Total must be positive and participant IDs unique.")
    if sum(minor(p.paid) for p in people) != total:
        raise AppError("invalid_input", "Paid shares must equal the total.")
    allocations = []
    if proposal.split == "equal":
        if any(p.owed is not None for p in people):
            raise AppError("invalid_input", "Equal splits cannot specify owed shares.")
        quotient, remainder = divmod(total, len(people))
        for index, person in enumerate(people):
            extra = int(index < remainder)
            people[index] = person.model_copy(update={"owed": decimal(quotient + extra)})
            allocations.append(Allocation(user_id=person.user_id, extra_minor_units=extra))
    elif any(p.owed is None for p in people) or sum(minor(p.owed or "0") for p in people) != total:
        raise AppError(
            "invalid_input", "Explicit owed shares must all be supplied and equal the total."
        )
    people = [
        p.model_copy(update={"paid": decimal(minor(p.paid)), "owed": decimal(minor(p.owed or "0"))})
        for p in people
    ]
    return proposal.model_copy(
        update={"participants": people, "total": decimal(total)}
    ), allocations


def payload(proposal: Proposal) -> dict[str, str | int]:
    result: dict[str, str | int] = {
        "group_id": proposal.group_id,
        "description": proposal.description,
        "date": proposal.date.isoformat(),
        "currency_code": proposal.currency,
        "cost": proposal.total,
        "repeat_interval": "never",
    }
    for index, person in enumerate(proposal.participants):
        result[f"users__{index}__user_id"] = person.user_id
        result[f"users__{index}__paid_share"] = person.paid
        result[f"users__{index}__owed_share"] = person.owed or "0.00"
    return result
