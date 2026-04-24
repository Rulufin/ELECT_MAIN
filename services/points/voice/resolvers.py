from typing import Optional

from utils.enum import Points_Type
from .enums import VCType
from .rules import VC_POINT_RULES

def resolve_vc_type_from_category(category_id: Optional[int]) -> Optional[VCType]:
    if category_id is None:
        return None

    for vc_type, rule in VC_POINT_RULES.items():
        if category_id in (rule.category_ids or ()):
            return vc_type

    return None


def resolve_points_type_for_connect(vc_type: VCType) -> Points_Type:
    if vc_type == VCType.NORMAL:
        return Points_Type.NORMAL_VC_CONNECT
    if vc_type == VCType.PUBLIC_ROOM:
        return Points_Type.PUBLIC_VC_CONNECT
    if vc_type == VCType.SECRET_ROOM:
        return Points_Type.PUBLIC_VC_CONNECT
    raise ValueError(f"Unhandled VCType for connect event: {vc_type}")


def resolve_points_type_for_owner(vc_type: VCType) -> Points_Type:
    if vc_type == VCType.NORMAL:
        return Points_Type.NORMAL_VC_OWNER
    if vc_type == VCType.PUBLIC_ROOM:
        return Points_Type.PUBLIC_VC_OWNER
    if vc_type == VCType.SECRET_ROOM:
        return Points_Type.PUBLIC_VC_OWNER
    raise ValueError(f"Unhandled VCType for owner event: {vc_type}")