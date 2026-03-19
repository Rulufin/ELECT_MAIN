import discord
import time
from discord.ext import commands
from discord import Embed, Member
import textwrap

from utils.ids import MAIN_ROLES

class Point_Panel_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ポイント管理__",
            description=textwrap.dedent(
                '''
                ポイントの確認/利用ができます。
                '''
            )
        )

class Point_Request_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ポイント申請__",
            description=textwrap.dedent(
                '''
                申請するコンテンツをえらんでください。
                '''
            )
        )

class Point_Request_Public_UserSelect_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__公開ポイント - ユーザー選択__",
            description=textwrap.dedent(
                '''
                一緒に公開したユーザーを自分含めて選択してください。
                '''
            )
        )

class Point_Request_Public_Embed(Embed):
    def __init__(self, use_point, pt_type):
        super().__init__(
            title="__公開ポイント - 申請__",
            description=textwrap.dedent(
                '''
                公開ポイントの申請を行います。

                公開ログのリンクを教えて下さい。
                -# ※間違えて申請した場合は『閉じる』を押してください。
                '''
            )
        )

class Point_Check_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ポイント確認__",
            description=textwrap.dedent(
                '''
                確認する期間をえらんでください。
                '''
            )
        )

class Point_Use_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ポイント仕様__",
            description=textwrap.dedent(
                '''
                使用したいコンテンツを選択してください。
                '''
            )
        )

class Points_Shortage_Embed(Embed):
    def __init__(self, user: Member, total, use_points):
        super().__init__(
            title="__ポイント不足__",
            description=textwrap.dedent(
                f'''
                {user.display_name} ({user.mention})
                のポイントが不足しています。
                # ――――――――――――――――――――
                必要ポイント: {use_points}
                現ポイント: {total}
                '''
            )
        )

class Points_Thread_Embed(Embed):
    def __init__(self, user: Member, title, selected, use_points, op_value, pt_type):
        super().__init__(
            title=f"__{title}__",
            description=textwrap.dedent(
                f'''
                あなたが選んだのは
                『{selected}』

                使用ポイントは
                『{use_points}』

                間違いなければこのままやりとりを続けてください。
                -# アイコン、絵文字、ロールに関しては希望をお伝えください。
                -# ※間違えて申請した場合は『閉じる』を押してください。
                '''
            )
        )
        self.set_author(name=f"{user.id}")
        self.set_footer(name=f"{MAIN_ROLES.ADMINISTRATOR_ONE} / {MAIN_ROLES.ADMINISTRATOR_TWO} / {op_value} / {pt_type}")

class Create_Channel_Embed(Embed):
    def __init__(self, jump_url):
        super().__init__(
            description=textwrap.dedent(
                f'''
                チャンネル/スレッドを作成しました。
                {jump_url}
                '''
            )
        )

class Channel_Information_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__個人TC__",
            description=textwrap.dedent(
                '''
                個人TCを作成しました。
                チャンネル/メッセージの管理権限があります。
                準備ができましたらチャンネルの閲覧可能ロールの設定をしてください。
                -# 質問事項があれば管理にご連絡ください。
                '''
            )
        )

class Thread_Close_Embed(Embed):
    def __init__(self):
        super().__init__(
            description="このスレッドを閉じます。よいですか？"
        )