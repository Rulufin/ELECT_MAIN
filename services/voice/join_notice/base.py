from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import discord
from discord import Embed, Member, VoiceState, VoiceChannel, StageChannel

from services.voice.join_notice.configs import (
    JOIN_NOTICE_HANDLER_CONFIGS,
    JoinNoticeHandlerConfig,
)


class BaseJoinNoticeHandler(ABC):
    @property
    def handler_name(self) -> str:
        return self.__class__.__name__

    @property
    def config(self) -> JoinNoticeHandlerConfig:
        return JOIN_NOTICE_HANDLER_CONFIGS.get(
            self.handler_name,
            JoinNoticeHandlerConfig(),
        )

    def is_enabled(self) -> bool:
        return self.config.enabled

    def is_target_channel(
        self,
        channel: VoiceChannel | StageChannel | None,
    ) -> bool:
        if channel is None:
            return False

        config = self.config

        if channel.id in config.exclude_vc_ids:
            return False

        category_id = getattr(channel, "category_id", None)
        if category_id is not None and category_id in config.exclude_category_ids:
            return False

        has_allow_rules = bool(config.allow_vc_ids or config.allow_category_ids)
        if not has_allow_rules:
            return True

        if channel.id in config.allow_vc_ids:
            return True

        if category_id is not None and category_id in config.allow_category_ids:
            return True

        return False

    @abstractmethod
    async def should_send(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> bool:
        raise NotImplementedError

    async def build_content(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> Optional[str]:
        return None

    async def build_embed(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> Optional[Embed]:
        return None

    async def send(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> bool:
        channel = after.channel
        if channel is None:
            return False

        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return False

        if not self.is_enabled():
            return False

        if not self.is_target_channel(channel):
            return False

        if not await self.should_send(member, before, after):
            return False

        content = await self.build_content(member, before, after)
        embed = await self.build_embed(member, before, after)

        if not content and embed is None:
            return False

        await channel.send(content=content, embed=embed)
        return True