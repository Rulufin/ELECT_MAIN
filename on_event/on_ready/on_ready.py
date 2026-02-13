import discord
from discord.ext import commands

from services.judging.views import (
    Judging_Panel_View, Judging_Result_View,
    Interview_Panel_View, Server_Guidance_View,
    Guide_Panel_View,
)
from services.recruit.views import (
    Recruit_Panel_View, Recruit_Main_Setting_View, 
    Recruit_Filter_Panel_View, Recruit_Filter_Setting_View,
    Recruit_Post_View, Recruit_Check_View, Recruit_User_View, Receive_View, Stand_View
)
from services.list_manager.views import (
    Blacklist_Manage_View, Blacklist_Add_View, 
)
from services.voice_channel.views import (
    Group_Knock_Menu_View, VC_Knock_Receive_View,
    VC_Create_QM_Panel_View, QM_Menu_View
)

async def on_ready_view(bot: commands.Bot):
    views = [
        # 審査
        Judging_Panel_View(), Judging_Result_View(),
        Interview_Panel_View(), Server_Guidance_View(),
        Guide_Panel_View(),

        # 裏募集
        Recruit_Panel_View(), Recruit_Main_Setting_View(),
        Recruit_Filter_Panel_View(), Recruit_Filter_Setting_View(),
        Recruit_Post_View(), Recruit_Check_View(), Recruit_User_View(), Receive_View(), Stand_View(),

        # ブラックリスト
        Blacklist_Manage_View(), Blacklist_Add_View(),

        # VC系
        Group_Knock_Menu_View(), VC_Knock_Receive_View(),
        VC_Create_QM_Panel_View(), QM_Menu_View()
    ]

    for view in views:
        bot.add_view(view)