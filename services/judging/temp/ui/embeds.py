import discord 
from discord import Embed, User, Message

import textwrap

from utils.emojis import DEFAULT, CUSTOM

from typing import Optional

class JT_Panel_Embed(Embed):
    def __init__(self, user: User, profile_url: str, date_ymd: str):
        super().__init__(
            title="__仮メンバー審査__",
            description=textwrap.dedent(
                f'''
                ■対象者
                {user.display_name} ({user.mention})

                ■プロフィール
                {profile_url}
                '''
            )
        )
        fake_url = f"https://dummy.local/?uid={user.id}"
        self.set_author(
            name=f"{user.name}",
            url=fake_url,
        )

        self.add_field(
            name="__審査について__",
            value=textwrap.dedent(
                '''
                ⭕️、❌️の投票は一回でも同席した方だけが投票できます。
                ❌️の投票は理由も記載してください。
                注意情報は同席しなくても投票できます。
                内容は管理にしか見えません。
                '''
            )
        )

        self.set_thumbnail(url=user.display_avatar.url)
        self.set_footer(text=date_ymd)

class Judging_Result_Embed(Embed):
    def __init__(self, label, target: User):
        super().__init__(
            title=f"__プロフ審査 - 投票__",
            description=textwrap.dedent(
                f'''
                {target.display_name} ({target.mention})の審査に『{label}』で投票しました。
                -# 投票内容を変更したい場合は他のボタンを押してください。
                '''
            )
        )

class Judging_Result_Change_Embed(Embed):
    def __init__(self, before, label, target: User):
        super().__init__(
            title="__プロフ審査 - 投票変更__",
            description=textwrap.dedent(
                f'''
                {target.display_name} ({target.mention})の投票を変更しました。
                {before} -> {label}
                -# 投票内容を変更したい場合は他のボタンを押してください。
                '''
            )
        )

class Judging_Result_Clear_Embed(Embed):
    def __init__(self, target: User):
        super().__init__(
            title="__プロフ審査 - 取消__",
            description=textwrap.dedent(
                f'''
                {target.display_name} ({target.mention})の投票を取り消しました。
                '''
            )
        )

class Judging_Caution_Embed(Embed):
    def __init__(self, before: Optional[str], after: Optional[str], target: Optional[User]):
        super().__init__(
            title="__プロフ審査 - 注意情報__",
            description=textwrap.dedent(
                f'''
                {target.display_name} ({target.mention})の注意情報を投稿しました。
                '''
            )
        )
        if before:
            self.add_field(name="__Before__", value=before, inline=False)
        if after:
            self.add_field(name="__After__", value=after, inline=False)

class JT_Pass_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="ELECT仮免審査 - 合格",
            description=textwrap.dedent(
                '''
                ELECTの仮免審査に合格しました。
                おめでとうございます。

                R18写真や裏募集などが使えるようになってます。
                引き続きELECTをお楽しみください。
                '''
            )
        )
