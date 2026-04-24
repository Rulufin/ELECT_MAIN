import discord 
from discord import Embed, Member

import textwrap

from utils.emojis import DEFAULT, CUSTOM

from typing import Optional

# --------------------
# コード分類: 9〜
# --------------------

class Error_Wait_Embed(Embed):
    def __init__(self):
        super().__init__(
            title=f"{DEFAULT.WARNING}__システムエラー__",
            description=textwrap.dedent(
                '''
                システムエラーが発生しました。
                しばらく待ってから再度お確かめください。
                '''
            )
        )
        self.set_footer(text="code : 9001")

class System_Profile_NotFoud_Embed(Embed):
    def __init__(self):
        super().__init__(
            description=textwrap.dedent(
                '''
                プロフィールが見つかりませんでした。
                '''
            )
        )

class System_Error_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__システムエラー__",
            description=textwrap.dedent(
                '''
                システム内部でエラーが発生しました。
                '''
            )
        )

class Profile_Embed(Embed):
    def __init__(self, target: Member, profile_url: str, thread_url: Optional[str]):
        super().__init__(
            description=textwrap.dedent(
                f'''
                {target.display_name} ({target.mention})
                '''
            )
        )
        self.set_thumbnail(url=target.display_avatar)
        self.add_field(name="プロフィールURL", value=f"{profile_url}", inline=False)
        if thread_url:
            self.add_field(name="仮免審査スレッド", value=f"{thread_url}", inline=False)