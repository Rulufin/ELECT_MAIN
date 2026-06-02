import discord
from discord import Embed

from utils.colorcodes import *  # 色定義がここにあると仮定

import textwrap
from typing import List

# エラータイプをクラス変数として定義
class ERROR_TYPE:
    API = {"title": "APIエラー", "description": "応答制限エラーが発生しています。\n下記時間経過後に再度お試しください\n復帰時間: {timestamp}", "color": COLORS.YELLOW}
    PERMISSION = {"title": "権限エラー", "description": "この操作を行う権限があなたにありません。", "color": COLORS.RED}

# Error_Embed クラス
class Error_Embed(Embed):
    def __init__(self, error_type=None, **kwargs):
        # デフォルト値
        title = kwargs.get("title", "")
        description = kwargs.get("description", "")
        color = kwargs.get("color", COLORS.RED)

        # エラータイプが指定されている場合は上書き
        if error_type and hasattr(ERROR_TYPE, error_type):
            error_data = getattr(ERROR_TYPE, error_type)
            title = error_data["title"]
            description = error_data["description"].format(**kwargs)  # 動的データを挿入
            color = error_data["color"]

        # Embed 初期化
        super().__init__(title=title, description=description, color=color)

class List_NotFound_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ブラックリスト - 確認__",
            description=textwrap.dedent(
                '''
                登録がありません。
                '''
            )
        )

class Waiting_Embed(Embed):
    def __init__(self):
        super().__init__(
            description=f"現在、リストの取得を行っています。\n少々お待ち下さい。",
            color=COLORS.BLACK
        )

class Blacklist_Manage_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ブラックリスト - 管理__",
            description=textwrap.dedent(
                '''
                ブラックリストの追加、削除、確認を行えます。
                -# 上限 80件
                '''
            )
        )

class Blacklist_Add_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ブラックリスト - 追加__",
            description=textwrap.dedent(
                '''
                追加したいユーザーを選択してください。
                -# 1回に選択できるのは25名です。
                -# すでに登録されているユーザーは二重登録されません。
                '''
            )
        )

class Blacklist_Add_Check_Embed(Embed):
    def __init__(self, user_list: List[str]):
        super().__init__(
            title="__ブラックリスト - 追加確認__",
            description=textwrap.dedent(
                '''
                追加するのは以下のユーザーでよろしいですか？
                '''
            )
        )
        value = "\n".join(user_list) if user_list else "（対象ユーザーが選択されていません）"
        self.add_field(name="__対象ユーザー__", value=value, inline=False)

class Blacklist_Add_Result_Embed(Embed):
    def __init__(self, add_users, existing_users, error_users):
        super().__init__(
            title="__ブラックリスト - 追加結果__",
        )
        if add_users:
            self.add_field(
                name="__追加ユーザー__",
                value="\n".join(add_users),
                inline=False
            )
        if existing_users:
            self.add_field(
                name="__既存ユーザー__",
                value="\n".join(existing_users),
                inline=False
            )
        if error_users:
            self.add_field(
                name="__追加失敗ユーザー__",
                value="\n".join(error_users),
                inline=False
            )

class Blacklist_Delete_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__ブラックリスト - 削除__",
            description=textwrap.dedent(
                '''
                リストから削除したいユーザーを選択してください。
                '''
            )
        )

class Blacklist_Delete_Check_Embed(Embed):
    def __init__(self, user_list: List):
        super().__init__(
            title="__ブラックリスト - 削除確認__",
            description=textwrap.dedent(
                '''
                リストから削除するのは以下のユーザーでよろしいですか？
                '''
            )
        )
        self.add_field(name="__対象ユーザー__", value=user_list, inline=False)

class Blacklist_Delete_Result_Embed(Embed):
    def __init__(self, add_users, error_users):
        super().__init__(
            title="__ブラックリスト - 削除結果__",
            )
        if add_users:
            self.add_field(name="__削除ユーザー__", value=add_users, inline=False)
        if error_users:
            self.add_field(name="__削除失敗ユーザー__", value=error_users, inline=False)

class Blacklist_Check_Embed(Embed):
    def __init__(self, value: str, page: int = 1, total_pages: int = 1):
        super().__init__(
            title="__ブラックリスト - 確認__",
            description=textwrap.dedent(
                '''
                現在の登録状況。
                '''
            )
        )
        self.add_field(name="__一覧__", value=value or "（登録がありません）", inline=False)

        if total_pages > 1:
            self.set_footer(text=f"ページ {page}/{total_pages}")