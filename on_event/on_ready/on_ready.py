import discord
from discord.ext import commands

import logging

from services.judging.profile.ui.views import (
    Judging_Panel_View, Judging_Result_View,
    Interview_Panel_View, Server_Guidance_View,
    Guide_Panel_View,
)
from services.judging.temp.ui.views import (
    JT_User_View, JT_Result_View
)
from services.recruit.views import (
    Recruit_Panel_View, Recruit_Main_Setting_View, 
    Recruit_Filter_Panel_View, Recruit_Filter_Setting_View,
    Recruit_Post_View, Recruit_Check_View, Recruit_User_View, Receive_View, Stand_View
)
from services.list_manager.views import (
    Blacklist_Manage_View, Blacklist_Add_View, 
)
from services.voice.ui.views import (
    Group_Knock_Menu_View, VC_Knock_Receive_View,
    VC_Create_QM_Panel_View, QM_Menu_View
)

from services.points.ui.views import (
    ThreadCloseConfirmView,
    PublicRequestUserSelectView,
    PublicRequestThreadView,
    PointsThreadView,
    Point_Panel_View,
)

from services.voice.talk_history.rules import resolve_countable_state

logger = logging.getLogger(__name__)
FILENAME = "on_ready_main"

async def on_ready_view(bot: commands.Bot):
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
        ThreadCloseConfirmView(), PublicRequestUserSelectView(),
        PublicRequestThreadView(),
        PointsThreadView(), Point_Panel_View(),
    ]

    for view in views:
        bot.add_view(view)

async def on_ready_recover(bot: commands.Bot):
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