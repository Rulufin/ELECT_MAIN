import discord
import time
from discord.ext import commands
from discord import Embed, Member, Container, SelectOption
import textwrap

from utils.ids import MAIN_ROLES
from utils.emojis import DEFAULT, CUSTOM

class Point_Panel_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ELECTOKEN管理__",
            description=textwrap.dedent(
                '''
                ELECTOKENの確認/利用ができます。
                '''
            )
        )

class Point_Request_Public_Select_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__公開ELECTOKEN - ユーザー選択__",
            description=textwrap.dedent(
                '''
                一緒に公開したユーザーを自分含めて選択し、【おっけー】を押してください。
                '''
            )
        )

class Point_Request_Public_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__公開ELECTOKEN - 申請__",
            description=textwrap.dedent(
                '''
                公開ELECTOKENの申請を行います。

                公開ログのリンクを教えて下さい。
                -# ※間違えて申請した場合は『閉じる』を押してください。
                '''
            )
        )

class Point_Request_Confirm_Check_Embed(Embed):
    def __init__(self, mention_list):
        super().__init__(
            title="__公開ELECTOKEN - 申請確認__",
            description=textwrap.dedent(
                f'''
                以下のユーザーに公開ELECTOKENを付与します。
                問題ないですか？
                -# ――――――――――――――――――――
                {mention_list}
                -# ――――――――――――――――――――
                -# ※問題がある場合はこのメッセージを削除してください。
                '''
            )
        )

class Point_Request_Confirm_Result_Embed(Embed):
    def __init__(self, ok_text: str, ng_text: str):
        sections = []
        if ok_text:
            sections.append(f"付与完了\n-# ――――――――――――――――――――\n{ok_text}")
        if ng_text:
            sections.append(f"付与エラー\n-# ――――――――――――――――――――\n{ng_text}")
        body = "\n\n".join(sections) if sections else "対象ユーザーなし"
        super().__init__(
            title="__公開ELECTOKEN - 付与結果__",
            description=body,
        )

class Point_Check_Embed(Embed):
    def __init__(self):
        super().__init__(
            title=f"__{CUSTOM.TOKEN}{DEFAULT.EYES}確認__",
            description=textwrap.dedent(
                '''
                確認する期間をえらんでください。
                '''
            )
        )

class Point_Exchange_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ポイント仕様__",
            description=textwrap.dedent(
                '''
                使用したいコンテンツを選択してください。
                '''
            )
        )

class Point_Exchange_Review_Embed(Embed):
    def __init__(self, op: discord.SelectOption):
        super().__init__(
            title="__ELECTOKEN - 交換__",
            description=textwrap.dedent(
                f'''
                以下の内容で進めます。よろしいですか？
                -# ――――――――――――――――――――
                選択項目：{op.label}
                使用トークン数：{op.description}
                '''
            )
        )

class Point_Shortage_Embed(Embed):
    def __init__(self, user: Member, total, use_points):
        super().__init__(
            title="__ポイント不足__",
            description=textwrap.dedent(
                f'''
                {user.display_name} ({user.mention})
                のポイントが不足しています。
                -# ――――――――――――――――――――
                必要ポイント: {use_points}
                現ポイント: {total}
                '''
            )
        )

class Point_Exchange_Thread_Embed(Embed):
    def __init__(self, user: Member, title, selected, use_points, op_value):
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
        self.set_footer(text=f"{op_value}")

class Point_Exchange_Thread_Review_Embed(Embed):
    def __init__(self, user: Member):
        super().__init__(
            title="__ELECTOKEN交換 - 確認__",
            description=textwrap.dedent(
                f'''
                以下のユーザーのトークン利用を完了します。
                問題ないですか？
                -# ――――――――――――――――――――
                {user.display_name} {user.mention}
                -# ――――――――――――――――――――
                -# ※問題がある場合はこのメッセージを削除してください。
                '''
            )
        )

class Point_Exchange_Thread_Result_Embed(Embed):
    def __init__(self, option: SelectOption, total_point):
        super().__init__(
            title="__ELECTOKEN交換 - 結果__",
            description=textwrap.dedent(
                f'''
                トークンの利用申請が完了しました。
                -# ――――――――――――――――――――
                利用内容：{option.label}
                利用トークン：{option.description}
                -# ――――――――――――――――――――
                現在のトークン：{total_point}
                '''
            )
        )

class Point_Channel_Create_Embed(Embed):
    def __init__(self, jump_url):
        super().__init__(
            description=textwrap.dedent(
                f'''
                チャンネル/スレッドを作成しました。
                {jump_url}
                '''
            )
        )

class Point_Channel_Info_Embed(Embed):
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

class Point_Check_Result_Embed(Embed):
    def __init__(self, *, total: int, genres: list, period_label: str):
        super().__init__(
            title="__ポイント確認 - 結果__",
            description=f"期間：{period_label}",
        )
        self.add_field(name="__全体__", value=f"{int(total):,} pt", inline=False)

        if not genres:
            self.add_field(name="__内訳__", value="（該当なし）", inline=False)
            return

        for g in genres:
            self.add_field(name=f"__{g['name']}__", value=f"{int(g['points']):,} pt", inline=True)

class Point_Thread_Close_Embed(Embed):
    def __init__(self):
        super().__init__(
            description="このスレッドを閉じます。よいですか？"
        )