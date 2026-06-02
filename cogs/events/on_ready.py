import asyncio
import logging
import discord
from discord.ext import commands

from services.judging.profile.ui.views import (
    Judging_Panel_View, Judging_Result_View,
    Interview_Panel_View, Server_Guidance_View,
    Guide_Panel_View,
)
from services.judging.temp.ui.views import (
    JT_User_View, JT_Result_View,
)
from services.recruit.ui.views import (
    Recruit_Panel_View, Recruit_Main_Setting_View,
    Recruit_Filter_Panel_View, Recruit_Filter_Setting_View,
    Recruit_Post_View, Recruit_Check_View, Recruit_User_View, Receive_View, Stand_View,
)
from services.list_manager.ui.views import (
    Blacklist_Manage_View, Blacklist_Add_View,
)
from services.voice.ui.views import (
    Group_Knock_Menu_View, VC_Knock_Receive_View,
    VC_Create_QM_Panel_View, QM_Menu_View,
)
from services.points.ui.views import (
    Point_Manage_Panel_View,
    Point_Request_Public_View,
    Point_Request_Public_Thread_View,
    Point_Thread_Close_View,
    Point_Exchange_View,
    Point_Exchange_Thread_View,
)
from services.voice.talk_history.rules import resolve_countable_state

logger = logging.getLogger(__name__)
FILENAME = "on_ready_main"


async def _register_views(bot: commands.Bot) -> None:
    views = [
        # 審査
        Judging_Panel_View(), Judging_Result_View(),
        Interview_Panel_View(), Server_Guidance_View(),
        Guide_Panel_View(),

        JT_User_View(), JT_Result_View(),

        # 裏募集
        Recruit_Panel_View(), Recruit_Main_Setting_View(),
        Recruit_Filter_Panel_View(), Recruit_Filter_Setting_View(),
        Recruit_Post_View(), Recruit_Check_View(), Recruit_User_View(), Receive_View(), Stand_View(),

        # ブラックリスト
        Blacklist_Manage_View(), Blacklist_Add_View(),

        # VC系
        Group_Knock_Menu_View(), VC_Knock_Receive_View(),
        VC_Create_QM_Panel_View(), QM_Menu_View(),

        # ポイント系
        Point_Manage_Panel_View(),
        Point_Request_Public_View(),
        Point_Request_Public_Thread_View(),
        Point_Thread_Close_View(),
        Point_Exchange_View(),
        Point_Exchange_Thread_View(),
    ]

    for view in views:
        bot.add_view(view)


async def _recover_talk_history(bot: commands.Bot) -> None:
    talk_history_service = getattr(bot, "talk_history_service", None)
    if talk_history_service is None:
        logger.warning("[%s] talk_history_service is None", FILENAME)
        return

    recovered_users = 0
    recovered_vcs = 0

    try:
        for guild in bot.guilds:
            channels = list(guild.voice_channels) + list(guild.stage_channels)

            for channel in channels:
                if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    continue

                members = getattr(channel, "members", [])
                if not members:
                    continue

                recovered_vcs += 1
                category_id = getattr(channel, "category_id", None)

                for member in members:
                    voice_state = getattr(member, "voice", None)
                    if voice_state is None:
                        continue

                    countable = resolve_countable_state(member, voice_state)

                    await talk_history_service.tracker.on_join(
                        vc_id=int(channel.id),
                        category_id=int(category_id) if category_id is not None else None,
                        user_id=int(member.id),
                        countable=bool(countable),
                    )
                    recovered_users += 1

        logger.info(
            "[%s] talk_history recovered done vcs=%s users=%s",
            FILENAME,
            recovered_vcs,
            recovered_users,
        )

    except Exception:
        logger.exception("[%s] on_ready_recover failed", FILENAME)


class On_Ready_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.change_presence(
            activity=discord.CustomActivity(name="わさびの刺激とビーフの旨み")
        )

        await _register_views(self.bot)
        await _recover_talk_history(self.bot)

        retries = 3
        delay = 5
        for attempt in range(retries):
            try:
                await self.bot.tree.sync()
                print("コマンド同期成功")
                break
            except Exception as e:
                print(f"コマンド同期失敗: {e}")
                if attempt < retries - 1:
                    print(f"{delay}秒後に再試行します... ({attempt + 1}/{retries})")
                    await asyncio.sleep(delay)
                else:
                    print("コマンド同期を再試行できませんでした。")


async def setup(bot: commands.Bot):
    await bot.add_cog(On_Ready_Cog(bot))
