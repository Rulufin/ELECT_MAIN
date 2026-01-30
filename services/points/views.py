import discord
from discord import (
    app_commands, Interaction, Embed,
    ButtonStyle, TextStyle,
    TextChannel, ForumChannel, Thread, SelectOption
)
from discord.ui import (
    View, Button, Modal, Select,
    TextInput
)

import logging

from services.points.embdes import Point_Check_Embed

from utils.emojis import DEFAULT, CUSTOM

from firestores.fs_points import FS_Points

FILENAME = "Points_Views"

logger = logging.getLogger(__name__)

CHECK_OP = [
    SelectOption(label="01. 1周間", value="Weekly", description="月～日でポイント集計"),
    SelectOption(label="02. 今月", value="Monthly", description="今月のポイント集計"),
    SelectOption(label="03. 全体", value="All", description="全体のポイント集計"),
]

USE_OP = [
    SelectOption(label="01. 絵文字作成", value="絵文字", description="")
]

class Point_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Check_Button(label="確認", emoji=DEFAULT.GRAPH, style=ButtonStyle.gray, row=0))
        self.add_item(Point_Use_Button(label="利用", emoji=DEFAULT.CHECK, style=ButtonStyle.gray, row=0))

class Point_Check_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        
        embed = Point_Check_Embed()
        view = Point_Check_View()

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class Point_Check_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Check_Select())

class Point_Check_Select(Select):
    def __init__(self):
        super().__init__(
            placeholder="期間を選択してください。",
            max_values=1, min_values=1,
            options=CHECK_OP, row=1,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
            )
        self.fs_points = FS_Points()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        selected = self.values[0]

        res = await self.fs_points.check_totals_by_period(interaction.user.id, period=selected)

        genreを整形するメソッドを作成したい。　field_name/pointsでdict/list化がいいかな

        embed = Point_Result_Embed()


class Point_Result_Embed(Embed):
    def __init__(self, total, genres, period):
        super().__init__(
            title="__ポイント確認 - 結果__",
            description=textwrap.dedent(
                f'''
                期間：{period}
                '''
            )
        )
        self.add_field(name="__全体__", value=f"{total}", inline=False)

        # genreを個別です。
        for genre in genres:
            self.add_field(name=f"{genre["name"]}", value=f"{genre["points"]}")
        

class 