import discord 
from discord import Embed, User, Message

import textwrap


from utils.emojis import DEFAULT, CUSTOM

from typing import Optional

class Judging_Entry_Embed(Embed):
    def __init__(self):
        super().__init__(
            title=f"{DEFAULT.MEMO}__プロフ審査 - 受付__",
            description=textwrap.dedent(
                '''
                プロフ審査を受け付けました。
                結果が出るまでしばらくお待ち下さい。
                '''
            )
        )

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

class Judging_Profile_Embed(Embed):
    def __init__(self, author: User, message: Message, formatted_date: str) -> None:
        super().__init__(
            description=message.content
        )

        fake_url = f"https://dummy.local/?uid={author.id}"

        self.set_author(
            name=f"{author.name}",
            url=fake_url,
        )

        self.add_field(
            name="__審査について__",
            value=textwrap.dedent(
                '''
                プロフィールを見て、入ってほしいかどうかで投票をお願いします。
                注意情報は管理にしか見えません。
                '''
            )
        )


        self.set_footer(text=f"{formatted_date}")
        self.set_thumbnail(url=author.display_avatar.url)

class Judging_Prof_Pass_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="ELECTプロフ審査 - 合格",
            description=textwrap.dedent(
                '''
                ELECTのプロフ審査に合格しました。
                おめでとうございます。

                [こちら](https://discord.com/channels/1421436016442740749/1424994909370323056)で面接日程の調整をお願いします。
                '''
            )
        )

class Judging_Interview_Pass_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="ELECT面接 - 合格",
            description=textwrap.dedent(
                '''
                ELECTの面接に合格しました。
                おめでとうございます。

                [こちら](https://ptb.discord.com/channels/1421436016442740749/1451824654560923748)でサーバー案内日程の調整をお願いします。
                '''
            )
        )

class Judging_Guide_Panel_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__案内人用パネル__",
            description=textwrap.dedent(
                '''
                VC接続者に仮メンバーロールを付与できます。
                '''
            )
        )