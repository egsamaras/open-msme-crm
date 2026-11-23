"""Who may review an approval item (SPEC 4.1, rule 2)."""

from app.models import ApprovalItem, User
from app.models.enums import FOUR_EYES_ROLES, ApprovalStatus, Role

ROUTINE_ROLES = frozenset({Role.RM, Role.ADMIN})

ROLE_NAMES = {
    Role.RM: "relationship manager",
    Role.CREDIT_OFFICER: "credit officer",
    Role.COMPLIANCE: "compliance officer",
    Role.ADMIN: "admin",
}


def required_roles(item: ApprovalItem) -> frozenset[Role]:
    return FOUR_EYES_ROLES.get(item.action_type, ROUTINE_ROLES)


def is_four_eyes(item: ApprovalItem) -> bool:
    return item.action_type in FOUR_EYES_ROLES


def review_blocker(item: ApprovalItem, user: User) -> str | None:
    """None if `user` may review `item`, otherwise the reason they can't."""
    if item.status != ApprovalStatus.PENDING:
        return "This item has already been resolved."
    roles = required_roles(item)
    if user.role not in roles:
        names = sorted(ROLE_NAMES[r] for r in roles if r != Role.ADMIN)
        return f"Needs a {' or '.join(names)} to review."
    if is_four_eyes(item) and item.initiator_id == user.id:
        return "Four-eyes rule: you started this run, so someone else must review it."
    return None
