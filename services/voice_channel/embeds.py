import discord
import time
from discord.ext import commands
from discord import Embed
import textwrap

from utils.colorcodes import *
from utils.emojis import *
from utils.ids import *

class VC_Create_Response_Embed(Embed):
    def __init__(self, channel_id):
        url = f"https://discord.com/channels/{MAIN_SERVER_ID}/{channel_id}"
        super().__init__(
            title="__VC作成__",
            description=f"{url} を作成しました。\n※リンクをクリックするとVCに接続できます。",
            color=SERVER_COLORS.MAIN
        )

class VC_Menu_Embed(Embed):
    def __init__(self, vc_type, user_id):
        super().__init__(title="__VCメニュー__", color=SERVER_COLORS.MAIN)
        if vc_type == "Free_Room":
            self.add_field(name=f"{DEFAULT.MEMO}__名前/ステータス変更__", value="部屋名とチャンネルステータスを変更できます。", inline=False)
            self.add_field(name=f"{DEFAULT.PEOPLE_TWO}__人数制限変更__", value="人数制限を変更します。", inline=False)
            self.add_field(name=f"{DEFAULT.HEADPHONE}__ビットレート変更__", value="ビットレートを変更できます。", inline=False)
            self.add_field(name=f"{DEFAULT.SLEEP}__寝落ち切断__", value="寝落ちた人を切断できます。", inline=False)
            self.set_footer(text=f"{user_id}")
        elif vc_type == "Knock_Room":
            self.add_field(name=f"{DEFAULT.MEMO}__名前/ステータス変更__", value="部屋名とチャンネルステータスを変更できます。", inline=False)
            self.add_field(name=f"{DEFAULT.HEADPHONE}__ビットレート変更__", value="ビットレートを変更できます。", inline=False)
            self.add_field(name=f"{DEFAULT.SLEEP}__寝落ち切断__", value="寝落ちた人を切断できます。", inline=False)
            self.add_field(name=f"{DEFAULT.DOOR}__ノック__", value="入室申請のノックボタンです。", inline=False)
            self.set_footer(text=f"{user_id}")
        elif vc_type == "Private_Room":
            self.add_field(name=f"{DEFAULT.MEMO}__名前/ステータス変更__", value="部屋名とチャンネルステータスを変更できます。", inline=False)
            self.add_field(name=f"{DEFAULT.HEADPHONE}__ビットレート変更__", value="ビットレートを変更できます。", inline=False)
            self.add_field(name=f"{DEFAULT.SLEEP}__寝落ち切断__", value="寝落ちた人を切断できます。", inline=False)
            self.add_field(name=f"{DEFAULT.MALE_HEART}__ユーザー招待__", value="この個室にユーザーを招待します。", inline=False)
            self.set_footer(text=f"{user_id}")

class VC_Status_Change_Embed(Embed):
    def __init__(self, change_type, name: str = "", status: str = None, user_limit: int = None, bitrate: int = None):
        type_map = {
            "Name": {
                "title": "__変更: 名前/ステータス__",
                "content": f"名前: {name}\nステータス: {status if status else 'なし'}\nに変更しました。"
            },
            "Limit": {
                "title": "__変更: 人数制限__",
                "content": f"人数制限: {user_limit if user_limit != 0 else '無制限'}\nに変更しました。"
            },
            "Bitrate": {
                "title": "__変更: ビットレート__",
                "content": f"ビットレート: {int(bitrate) / 1000 if bitrate else '未設定'} kbps に変更しました。"
            }
        }

        # 安全にデータを取得
        data = type_map.get(change_type)

        # Embedの生成
        super().__init__(
            title=data["title"],
            description=data["content"],
            color=COLORS.BLACK
        )

class VC_Sleep_Response_Embed(Embed):
    def __init__(self, user_name, target_name, comment):
        super().__init__(
            title="__寝落ち切断__",
            description=f"{user_name} さんが {target_name} さんを寝落ち切断しました。",
            color=COLORS.BLUE_CORNFLOWER
        )
        self.add_field(name="__一言__", value=f"{comment}")

class VC_User_Invite_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__選択: ユーザー招待__",
            description="招待するユーザーを選択してください。(上限5人)",
            color=COLORS.BLACK
        )

class VC_User_Invite_Check_Embed(Embed):
    def __init__(self, user_list):
        super().__init__(
            title="__確認: ユーザー招待__",
            description="以下のユーザーを招待してよろしいですか？",
            color=COLORS.BLACK
        )
        self.add_field(name="__ユーザー一覧__", value=user_list, inline=False)

class VC_User_Invite_Result_Embed(Embed):
    def __init__(self, invited_user_list, failed_user_list):
        super().__init__(
            title="__結果: ユーザー招待__",
            color=COLORS.BLACK
        ),
        if invited_user_list:
            self.add_field(name="__招待成功__", value=invited_user_list, inline=False)
        if failed_user_list:
            self.add_field(name="__招待失敗__", value=failed_user_list, inline=False)

class VC_Invited_Embed(Embed):
    def __init__(self, guild_name, channel_id):
        url = f"https://discord.com/channels/{MAIN_SERVER_ID}/{channel_id}"
        super().__init__(
            title="__VC招待__",
            color=SERVER_COLORS.MAIN
        )
        self.add_field(name="__サーバー名__", value=f"{guild_name}", inline=False)
        self.add_field(name="__チャンネル__", value=f"{url})", inline=False)
        self.set_footer(text="リンクを押すことでVCに接続できます。")

class VC_Per_Check_Embed(Embed):
    def __init__(self, current_page, max_page, viewer_role_list, viewer_user_list, nonviewer_user_list):
        super().__init__(
            title=f"__確認: 閲覧権限({current_page}/{max_page})"
        )
        self.add_field(name="__閲覧可能ロール__", value=viewer_role_list, inline=False)
        self.add_field(name="__閲覧可能ユーザー__", value=viewer_user_list, inline=False)
        self.add_field(name="__閲覧不可ユーザー__", value=nonviewer_user_list, inline=False)

class VC_Knock_Response_Embed(Embed):
    def __init__(self):
        super().__init__(
            description="ノックしました。"
        )

class VC_Knock_Receive_Embed(Embed):
    def __init__(self, target: discord.User, prof_url):
        super().__init__(
            title = "__ノック__",
            description = textwrap.dedent(
                '''
                ノックされました。どうしますか？
                -# 【承認】を押すと入場可能になります。
                -# 【また今度】を押すとお断りDMが相手に届きます。
                '''
            )
        )
        self.add_field(name="__ノックユーザー__", value=f"{target.display_name} ({target.mention})", inline=False)
        self.add_field(name="__プロフィール__", value=f"{prof_url}", inline=False)
        self.set_author(name=f"{target.id}")

class VC_Knock_Approve_Embed(Embed):
    def __init__(self):
        super().__init__(
            description="ノックが承認されました。"
        )

class VC_Knock_Approve_DM_Embed(Embed):
    def __init__(self, vc_url):
        super().__init__(
            description=textwrap.dedent(
                f'''
                {vc_url}
                でノックが承認されました。
                '''
            )
        )

class VC_Knock_Cancel_Embed(Embed):
    def __init__(self, comment: str):
        super().__init__(
            title="__ノック - また今度__",
            description=textwrap.dedent(
                f'''
                コメント：
                {comment}
                '''
            )
        )

class VC_Profile_Embed(Embed):
    def __init__(self, member_name, member_id, avator_url, profile_url):
        super().__init__(
            description=f"{member_name} (<@{member_id}>)",
        )
        self.add_field(name="__プロフィールリンク__", value=f"{profile_url}")
        self.set_thumbnail(url=avator_url)

class VC_Knock_Disconnect_Embed(Embed):
    def __init__(self):
        super().__init__(
            description=textwrap.dedent(
                '''
                この部屋に接続するためにはノックが必要です。
                '''
            )
        )

# ――――――――――――――――――――――――
# エラー
# ――――――――――――――――――――――――
class VC_Error_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__エラー__",
            description="操作中にエラーが発生しました。",
            color=COLORS.RED
        )

class VC_Create_Error_Embed(Embed):
    def __init__(self, e):
        super().__init__(
            title="__エラー: VC作成__",
            description=f"VC作成中にエラーが発生しました。\n==========\n{e}",
            color=COLORS.RED
        )

class VC_One_Minutes_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__エラー: 部屋作成制限__",
            description="部屋作成は1分間に一回だけ行えます。\nしばらくしてからもう一度試してください。",
            color=COLORS.RED
        )

class VC_Owner_Error_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__エラー: 権限エラー__",
            description="このボタンを利用できるのは部屋を作成した人だけです。",
            color=COLORS.RED
        )

class VC_Zenhankaku_Error_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__エラー: 文字入力__",
            description="このボタンの入力は半角数字のみにしてください。",
            color=COLORS.RED
        )

class VC_RateLimit_Embed(Embed):
    def __init__(self, retry_after):
        retry_time = int(time.time() + retry_after)  # 秒単位で整数化
        super().__init__(
            title="__エラー: レート制限__",
            description=f"現在、レート制限に達しています。\nレート制限解除は **__<t:{retry_time}:R>__** です。",
            color=COLORS.RED
        )

class VC_DM_Error_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__エラー: DM未許可__",
            description="botからのDM受信が許可されていません。",
            color=COLORS.RED
        )  

class VC_Internal_Error_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__エラー: 内部エラー__",
            description="内部エラーが発生しました。\n管理者にお問い合わせください。",
            color=COLORS.RED
        )

class VC_Connect_Error_Embed(Embed):
    def __init__(self, jump_url):
        super().__init__(
            title="__エラー: VC接続__",
            description=f"このボタンは {jump_url} に接続している状態でのみ利用できます。",
            color=COLORS.RED
            )

class VC_Bitrate_Error_Embed(Embed):
    def __init__(self, max_bitrate):
        super().__init__(
            title="__エラー: ビットレート__",
            description=f"ビットレートは8kbpsから{max_bitrate/1000}kbpsの範囲で設定してください。",
            color=COLORS.RED
        )