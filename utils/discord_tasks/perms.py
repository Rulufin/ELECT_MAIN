# utils/discord/perms.py
from __future__ import annotations

import discord


def can_send(channel: discord.abc.GuildChannel, me: discord.Member) -> bool:
    perms = channel.permissions_for(me)
    return perms.view_channel and perms.send_messages


def can_manage_messages(channel: discord.abc.GuildChannel, me: discord.Member) -> bool:
    perms = channel.permissions_for(me)
    return perms.manage_messages


def can_manage_roles(guild: discord.Guild, me: discord.Member) -> bool:
    return me.guild_permissions.manage_roles


def role_is_editable(me: discord.Member, role: discord.Role) -> bool:
    # bot can edit roles lower than its top role, and not managed roles
    if role.managed:
        return False
    return me.top_role > role
