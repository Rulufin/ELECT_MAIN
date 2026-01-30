from discord import (
    Guild, Member, PermissionOverwrite,
    TextChannel, VoiceChannel,
    HTTPException,
)
from discord.abc import Snowflake

import logging
from typing import Optional

from firestores.fs_vc_tc_sync import FS_VC_TC_SYNC
from services.voice_channel.embeds import VC_Menu_Embed, VC_Knock_Disconnect_Embed
from services.voice_channel.views import Group_Knock_Menu_View

from .configs import MAIN_CATEGORIES, MAIN_CHANNELS, FILENAME
from .context import VoiceStateContext

from utils.ids import MAIN_ROLES

logger = logging.getLogger(__name__)


class KnockService:
    def __init__(self, fs_vc_tc_sync: Optional[FS_VC_TC_SYNC] = None) -> None:
        # 外から渡せるようにしておくとテストしやすい + デフォルトは自前生成
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
        tc: Optional[TextChannel] = await self.get_knock_text_channel(guild, vc_id)
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
                # overwrite=None で個人権限を削除
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

        # テンプレの待機VC（KNOCK_ROOM）は消さない
        if before_ch.id == MAIN_CHANNELS.KNOCK_ROOM:
            return

        # 最新のチャンネル状態を取得
        vc = guild.get_channel(before_ch.id)
        if not isinstance(vc, VoiceChannel):
            return

        # bot を除いたメンバーがいるなら削除しない
        human_members = [m for m in vc.members if not m.bot]
        if human_members:
            return

        # 紐づくTCを取得
        tc = await self.get_knock_text_channel(guild, vc.id)

        # Firestoreの紐づけ削除（delete_ids があれば）
        try:
            if hasattr(self.fs_vc_tc_sync, "delete_ids"):
                await self.fs_vc_tc_sync.delete_ids(vc_id=vc.id)
        except Exception as e:
            logger.warning(
                f"[{FILENAME}] failed to delete vc-tc mapping for vc={vc.id}: {e}",
                exc_info=True,
            )

        # 先にTC → 後にVC を削除
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
        # ノック専用カテゴリを取得
        knock_category = (
            guild.get_channel(MAIN_CATEGORIES.KNOCK_CATEGORY)
            or await guild.fetch_channel(MAIN_CATEGORIES.KNOCK_CATEGORY)
        )

        # まずロールを先に解決（TC/VC 両方で使う）
        everyone_role = guild.default_role
        member_role = (
            guild.get_role(MAIN_ROLES.MEMBER)
            or await guild.fetch_role(MAIN_ROLES.MEMBER)
        )
        p_member_role = (
            guild.get_role(MAIN_ROLES.P_MEMBER)
            or await guild.fetch_role(MAIN_ROLES.P_MEMBER)
        )

        # 専用VC作成
        new_vc = await guild.create_voice_channel(
            name=f"🚪{member.display_name}の部屋",
            category=knock_category,
            user_limit=0,
        )

        # 専用TC作成（最初は本人だけ見える想定）
        tc_overwrites: dict[Snowflake, PermissionOverwrite] = {
            everyone_role: PermissionOverwrite(view_channel=False, send_messages=False),
            member: PermissionOverwrite(view_channel=True, send_messages=True),
        }

        new_tc = await guild.create_text_channel(
            name="💬チャット",
            category=knock_category,
            overwrites=tc_overwrites,
        )

        # VC-TCの紐づけを Firestore に保存
        await self.fs_vc_tc_sync.add_ids(vc_id=new_vc.id, tc_id=new_tc.id)

        # メニュー設置
        knock_embed = VC_Menu_Embed(vc_type="Knock_Room", user_id=member.id)
        knock_view = Group_Knock_Menu_View()
        try:
            await new_vc.send(embed=knock_embed, view=knock_view)
        except Exception as e:
            logger.warning(
                f"[{FILENAME}] failed to send knock menu to VC {new_vc.id}: {e}",
                exc_info=True,
            )

        # VC 側の権限設定
        overwrites: dict[Snowflake, PermissionOverwrite] = {
            everyone_role: PermissionOverwrite(view_channel=False, connect=False),
            member_role: PermissionOverwrite(view_channel=True, connect=True),
            p_member_role: PermissionOverwrite(view_channel=True, connect=True),
            member: PermissionOverwrite(view_channel=True, connect=True, speak=True),
        }

        await new_vc.edit(overwrites=overwrites)

        # ユーザーを新VCへ移動
        await member.move_to(channel=new_vc)

    async def handle_knock_category_connect(self, ctx: VoiceStateContext) -> bool:
        """
        ノック用カテゴリ内のVCに接続したときの処理。

        - 個人権限がなければ → 不正入室: VCから切断し、警告Embedを送信して True を返す
        - 個人権限があれば → 正規入室: 対応TCに個人権限を付与し、False を返す（以降のログ処理へ）
        """
        after_ch = ctx.after_ch
        if after_ch is None:
            return False

        # テンプレの待機VCはここでは触らない
        if after_ch.id == MAIN_CHANNELS.KNOCK_ROOM:
            return True

        guild = ctx.guild
        member = ctx.member

        # VoiceChannel.overwrites は {Role or Member: PermissionOverwrite} の dict
        overwrites = after_ch.overwrites

        # 個人権限（Member をキーにした overwrite）があるか確認
        po: Optional[PermissionOverwrite] = overwrites.get(member)

        # 個人権限がない or connect/view が明示的に False なら不正入室扱いにする
        if po is None or po.connect is False or po.view_channel is False:
            try:
                await member.move_to(None)  # VCから切断
            except HTTPException as e:
                logger.warning(
                    f"[{FILENAME}] failed to disconnect member {member.id} from knock VC: {e}",
                    exc_info=True,
                )

            # VC側にメッセージ送信
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

            # 不正入室 → TC権限はそもそも無い想定なので何もしない
            return True

        # ここまで来たら「正規入室」扱い → 対応TCに個人権限を付与
        await self.set_knock_text_permission(guild, after_ch.id, member, allow=True)

        # この後は通常ログ処理を続けたいので False
        return False

    async def handle_knock_flow(self, ctx: VoiceStateContext) -> bool:
        """
        ノック部屋 / ノックカテゴリ用の特別処理まとめ。
        - True を返した場合: ここで完結しており、以降のログ処理をスキップする（不正入室など）。
        - False を返した場合: 通常どおりログ処理へ進む。
        """
        member = ctx.member
        guild = ctx.guild

        # 1) ノックVCから離れた場合 → 対応TCから個人権限を剥奪 & 無人なら部屋を削除
        if ctx.left_knock_vc and ctx.before_ch:
            await self.set_knock_text_permission(
                guild,
                ctx.before_ch.id,
                member,
                allow=False,
            )
            # bot を除いて 0 人になっていれば VC/TC 削除
            await self._cleanup_knock_room_if_empty(ctx)

        # 2) ノック待機VC (KNOCK_ROOM) に入ったら専用VC/TCを作成して移動
        if ctx.to_knock_waiting and ctx.transition in ("JOIN", "MOVE"):
            await self.create_knock_room_vc_and_tc(guild, member)
            # このイベント自体は NOT_CONNECT_VC_IDS に含まれているのでログ対象外。
            # ここでは False を返しておき、後続ログ処理側でスキップされる。

        # 3) ノックカテゴリ内のVCに入ったときの処理
        if ctx.to_knock_category and ctx.after_ch is not None:
            handled = await self.handle_knock_category_connect(ctx)
            if handled:
                # 不正入室でここで完結させたい
                return True

        return False
