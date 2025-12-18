import discord 
from discord import Embed

import textwrap

from utils.emojis import DEFAULT, CUSTOM

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