from __future__ import annotations

import logging
from typing import Optional

from discord import (
    Guild,
    Member,
    PermissionOverwrite,
    TextChannel,
    VoiceChannel,
    HTTPException,
)
from discord.abc import Snowflake

from firestores.fs_vc_tc_sync import FS_VC_TC_SYNC
from services.voice.ui.embeds import VC_Menu_Embed, VC_Knock_Disconnect_Embed
from services.voice.ui.views import Group_Knock_Menu_View

from services.voice.state.configs import FILENAME
from services.voice.state.event import VoiceStateContext

from utils.ids import MAIN_CATEGORIES, MAIN_CHANNELS, MAIN_ROLES

logger = logging.getLogger(__name__)


class KnockService:
    def __init__(self, fs_vc_tc_sync: Optional[FS_VC_TC_SYNC] = None) -> None:
        self.fs_vc_tc_sync = fs_vc_tc_sync or FS_VC_TC_SYNC()

    # =========================
    # VC → TC 解決 & 個人権限
    # =========================

    async def get_knock_text_channel(
        self,
        guild: Guild,
        vc_id: int,
    ) -> Optional[TextChannel]:
        """
        VC に対応するノック用 TC を FS_VC_TC_SYNC から解決する。
        """
        try:
            result = await self.fs_vc_tc_sync.get_ids(vc_id=vc_id)
        except Exception as e:
            logger.warning(f"[{FILENAME}] get_ids({vc_id}) error: {e}", exc_info=True)
            return None

        if result is None:
            return None

        tc_id: Optional[int] = None

        if isinstance(result, int):
            tc_id = result
        elif isinstance(result, dict):
            raw = result.get("TC_ID") or result.get("tc_id")
            if raw is not None:
                try:
                    tc_id = int(raw)
                except (TypeError, ValueError):
                    tc_id = None

        if tc_id is None:
            return None

        ch = guild.get_channel(tc_id)
        if ch is None:
            try:
                ch = await guild.fetch_channel(tc_id)
            except HTTPException:
                return None

        if isinstance(ch, TextChannel):
            return ch

        return None

    async def set_knock_text_permission(
        self,
        guild: Guild,
        vc_id: int,
        member: Member,
        allow: bool,
    ) -> None:
        """
        ノック部屋に紐づくTCの個人権限を付与/剥奪する。

        allow=True  -> view/send 権限を付与
        allow=False -> 個人overwriteを削除（ロールに委ねる）
        """
        tc = await self.get_knock_text_channel(guild, vc_id)
        if tc is None:
            return

        try:
            if allow:
                await tc.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            else:
                await tc.set_permissions(member, overwrite=None)
        except HTTPException as e:
            logger.warning(
                f"[{FILENAME}] failed to set knock TC permission "
                f"(vc={vc_id}, tc={tc.id}, user={member.id}, allow={allow}): {e}",
                exc_info=True,
            )

    # =========================
    # クリーンアップ（部屋が空になったら削除）
    # =========================

    async def _cleanup_knock_room_if_empty(self, ctx: VoiceStateContext) -> None:
        """
        ノックVCから誰かが抜けたあと、そのVCが
        - bot を除いたメンバー数 0
        になっていれば VC / TC / Firestore 紐付きを削除する。
        """
        before_ch = ctx.before_ch
        guild = ctx.guild

        if before_ch is None:
            return

        if before_ch.id == MAIN_CHANNELS.KNOCK_ROOM:
            return

        vc = guild.get_channel(before_ch.id)
        if not isinstance(vc, VoiceChannel):
            return

        human_members = [m for m in vc.members if not m.bot]
        if human_members:
            return

        tc = await self.get_knock_text_channel(guild, vc.id)

        try:
            if hasattr(self.fs_vc_tc_sync, "delete_ids"):
                await self.fs_vc_tc_sync.delete_ids(vc_id=vc.id)
        except Exception as e:
            logger.warning(
                f"[{FILENAME}] failed to delete vc-tc mapping for vc={vc.id}: {e}",
                exc_info=True,
            )

        if tc is not None:
            try:
                await tc.delete(reason="Knock VC became empty (no human members)")
            except HTTPException as e:
                logger.warning(
                    f"[{FILENAME}] failed to delete knock TC {tc.id}: {e}",
                    exc_info=True,
                )

        try:
            await vc.delete(reason="Knock VC became empty (no human members)")
        except HTTPException as e:
            logger.warning(
                f"[{FILENAME}] failed to delete knock VC {vc.id}: {e}",
                exc_info=True,
            )

    # =========================
    # ノック関連: VC/TC 作成 & 入退出制御
    # =========================

    async def create_knock_room_vc_and_tc(
        self,
        guild: Guild,
        member: Member,
    ) -> None:
        """
        KNOCK_ROOM に入ったユーザー専用の VC / TC を作成し、
        Firestore に紐づけを保存して、メニューを設置し、ユーザーを移動させる。
        """
        knock_category = (
            guild.get_channel(MAIN_CATEGORIES.KNOCK_CATEGORY)
            or await guild.fetch_channel(MAIN_CATEGORIES.KNOCK_CATEGORY)
        )

        everyone_role = guild.default_role
        member_role = (
            guild.get_role(MAIN_ROLES.MEMBER)
            or await guild.fetch_role(MAIN_ROLES.MEMBER)
        )
        p_member_role = (
            guild.get_role(MAIN_ROLES.P_MEMBER)
            or await guild.fetch_role(MAIN_ROLES.P_MEMBER)
        )

        new_vc = await guild.create_voice_channel(
            name=f"🚪{member.display_name}の部屋",
            category=knock_category,
            user_limit=0,
        )

        tc_overwrites: dict[Snowflake, PermissionOverwrite] = {
            everyone_role: PermissionOverwrite(view_channel=False, send_messages=False),
            member: PermissionOverwrite(view_channel=True, send_messages=True),
        }

        new_tc = await guild.create_text_channel(
            name="💬チャット",
            category=knock_category,
            overwrites=tc_overwrites,
        )

        await self.fs_vc_tc_sync.add_ids(vc_id=new_vc.id, tc_id=new_tc.id)

        knock_embed = VC_Menu_Embed(vc_type="Knock_Room", user_id=member.id)
        knock_view = Group_Knock_Menu_View()
        try:
            await new_vc.send(embed=knock_embed, view=knock_view)
        except Exception as e:
            logger.warning(
                f"[{FILENAME}] failed to send knock menu to VC {new_vc.id}: {e}",
                exc_info=True,
            )

        overwrites: dict[Snowflake, PermissionOverwrite] = {
            everyone_role: PermissionOverwrite(view_channel=False, connect=False),
            member_role: PermissionOverwrite(view_channel=True, connect=True),
            p_member_role: PermissionOverwrite(view_channel=True, connect=True),
            member: PermissionOverwrite(view_channel=True, connect=True, speak=True),
        }

        await new_vc.edit(overwrites=overwrites)
        await member.move_to(channel=new_vc)

    async def handle_knock_category_connect(self, ctx: VoiceStateContext) -> bool:
        """
        ノック用カテゴリ内のVCに接続したときの処理。

        - 個人権限がなければ → 不正入室: VCから切断し、警告Embedを送信して True を返す
        - 個人権限があれば → 正規入室: 対応TCに個人権限を付与し、False を返す
        """
        after_ch = ctx.after_ch
        if after_ch is None:
            return False

        if after_ch.id == MAIN_CHANNELS.KNOCK_ROOM:
            return True

        guild = ctx.guild
        member = ctx.member

        overwrites = after_ch.overwrites
        po = overwrites.get(member)

        if po is None or po.connect is False or po.view_channel is False:
            try:
                await member.move_to(None)
            except HTTPException as e:
                logger.warning(
                    f"[{FILENAME}] failed to disconnect member {member.id} from knock VC: {e}",
                    exc_info=True,
                )

            try:
                await after_ch.send(
                    content=member.mention,
                    embed=VC_Knock_Disconnect_Embed(),
                )
            except Exception as e:
                logger.warning(
                    f"[{FILENAME}] failed to send knock disconnect message in channel {after_ch.id}: {e}",
                    exc_info=True,
                )

            return True

        await self.set_knock_text_permission(guild, after_ch.id, member, allow=True)
        return False

    async def handle_knock_flow(self, ctx: VoiceStateContext) -> bool:
        """
        ノック部屋 / ノックカテゴリ用の特別処理まとめ。
        - True: ここで完結し、以降の処理をスキップ
        - False: 通常どおり後続へ進む
        """
        member = ctx.member
        guild = ctx.guild

        if ctx.left_knock_vc and ctx.before_ch:
            await self.set_knock_text_permission(
                guild,
                ctx.before_ch.id,
                member,
                allow=False,
            )
            await self._cleanup_knock_room_if_empty(ctx)

        if ctx.to_knock_waiting and ctx.transition in ("JOIN", "MOVE"):
            await self.create_knock_room_vc_and_tc(guild, member)

        if ctx.to_knock_category and ctx.after_ch is not None:
            handled = await self.handle_knock_category_connect(ctx)
            if handled:
                return True

        return False