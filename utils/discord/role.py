import discord
from discord import (
    Guild, Role
)

# -------------------------
# ロール取得（キャッシュ→API）
# -------------------------
async def resolve_role(guild: Guild, role_id: int) -> Role | None:
    role = guild.get_role(role_id)
    if role is not None:
        return role
    try:
        return await guild.fetch_role(role_id)
    except discord.NotFound:
        return None
    except discord.Forbidden:
        # fetch_role 自体が権限不足のケース
        return None
    except Exception:
        return None