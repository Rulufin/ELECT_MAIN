from typing import Iterable, Optional
from discord import Member


# ─────────────
# Role Checks
# ─────────────

def has_any_role(
    member: Optional[Member],
    role_ids: Iterable[int],
) -> bool:
    if member is None:
        return False

    role_id_set = set(role_ids)
    if not role_id_set:
        return False

    return any(role.id in role_id_set for role in member.roles)


def has_all_roles(
    member: Optional[Member],
    role_ids: Iterable[int],
) -> bool:
    if member is None:
        return False

    role_id_set = set(role_ids)
    if not role_id_set:
        return False

    member_role_ids = {role.id for role in member.roles}
    return role_id_set.issubset(member_role_ids)


def has_no_role(
    member: Optional[Member],
    role_ids: Iterable[int],
) -> bool:
    if member is None:
        return True

    role_id_set = set(role_ids)
    if not role_id_set:
        return True

    return all(role.id not in role_id_set for role in member.roles)