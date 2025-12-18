import discord
import textwrap
import time
from typing import Optional, Union
from discord.ext import commands
from discord import Embed
from utils.colorcodes import *
from utils.emojis import *
from utils.ids import *


class Create_Thread_Embed(Embed):
    def __init__(self, channel_id):
        url = f"https://discord.com/channels/{MAIN_SERVER_ID}/{channel_id}"
        super().__init__(
            title="__裏募集作成__",
            description=f"裏募集作成用スレッドを作成しました。\nスレッド: {url}",
            color=COLORS.BLACK
        )

class Recruit_Panel_Embed(Embed):
    def __init__(self):
        super().__init__(
            title=f"{DEFAULT.MEMO}__裏募集作成__",
            description=textwrap.dedent(
                '''
                異性にしか見えない募集を出せます。
                -# 【記名】- 募集主が誰か分かります。
                -# 【匿名】- 募集主が誰か分かりません。
                -# 募集は1つしか出せません。新しく投稿したい場合は以前の募集を削除してください。

                ※ ブラックリストの追加確認は [こちら](https://discord.com/channels/1421436016442740749/1446850336903004201) から
                '''
            ),
            color=SERVER_COLORS.MAIN
        )

class Recruit_Signed_Setting_Embed(Embed):
    def __init__(self, user_name, user_id, user_avatar_url, profile_url, color, number,
                 content="雑談、猥談、作業、ゲーム、エロイプ、寝落ち、他",
                 desire_time="いまから、◯時から、など",
                 desire_you="",
                 message="",
                 thread_id=None,
                 posted_time=None,
                 ):
        super().__init__(
            title="__記名裏募集__",
            color=color
        )
        self.add_field(name="__募集主__", value=f"{user_name} (<@{user_id}>)", inline=False)
        self.add_field(name="__プロフィール__", value=f"{profile_url}", inline=False)
        self.add_field(name="__したいこと__", value=content, inline=False)
        self.add_field(name="__いつから__", value=desire_time, inline=False)
        self.add_field(name="__相手に望むもの__", value=desire_you, inline=False)
        self.add_field(name="__一言__", value=message, inline=False)
        self.add_field(name="__投稿日時__", value=posted_time, inline=False)
        self.set_thumbnail(url=user_avatar_url)
        self.set_footer(text=f"{number}")
        if thread_id:
            self.set_author(name=f"{thread_id}")

class Recruit_Anonymous_Setting_Embed(Embed):
    def __init__(self, color, number,
                 hint="",
                 content="雑談、猥談、作業、ゲーム、エロイプ、寝落ち、他",
                 desire_time="いまから、◯時から、など",
                 desire_you="",
                 message="",
                 thread_id=None,
                 posted_time=None,
                 ):
        super().__init__(
            title="__匿名裏募集__",
            color=color
        )
        self.add_field(name="__募集者のヒント__", value=hint, inline=False)
        self.add_field(name="__したいこと__", value=content, inline=False)
        self.add_field(name="__いつから__", value=desire_time, inline=False)
        self.add_field(name="__相手に望むもの__", value=desire_you, inline=False)
        self.add_field(name="__一言__", value=message, inline=False)
        self.add_field(name="__投稿日時__", value=posted_time, inline=False)
        self.set_footer(text=f"{number}")
        if thread_id:
            self.set_author(name=f"{thread_id}")

class Recruit_Other_Setting_Embed(Embed):
    def __init__(self, role_id):
        super().__init__(
            title="__その他設定__",
        )
        self.add_field(name="__性別__", value=f"<@&{role_id}>", inline=False)
        self.add_field(name="__その他ロール__", value="", inline=False)

class Recruit_Post_Embed(Embed):
    def __init__(self, message_id):
        super().__init__(
            description=textwrap.dedent(
                '''
                【公開】のボタンを押すと、裏募集を公開します。
                -# 　・性別/その他ロールを所持してる人を対象とします。
                -# 　・マイリスト => マイリスト登録ユーザーにのみ募集を行います。
                -# 　・ブラックリスト => ブラックリスト登録ユーザーを除外して募集を行います。
                【編集】のボタンを押すと設定したもので裏募集を更新します。
                【削除】のボタンを押すと裏募集を削除し、このスレッドを閉じます。
                '''
            )
        )
        self.set_author(name=f"{message_id}")

class Recruit_Filter_Set_Embed(Embed):
    def __init__(self, message_id, gender_role, filter_roles):
        super().__init__(
            title="__その他ロール設定__",
            description=textwrap.dedent(
                '''
                募集条件に設定ロールを持ってるか全て持っているかという条件を追加できます。
                -# 【設定】- ロール設定を行います。
                -# 【リセット】- ロール設定をリセットします。
                -# 【確認】- 設定内容で対象ユーザーが何人いるか確認できます。
                -# 【確定】- 設定を確定します。
                '''
            )
        )
        self.add_field(name="__性別__", value=gender_role, inline=False)
        self.add_field(name="__その他ロール__", value=filter_roles, inline=False)
        self.add_field(name="を全て所持してるユーザーを募集対象とする。", value="", inline=False)
        self.set_author(name=f"{message_id}")

class Recruit_FoundData_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__裏募集: 公開済__",
            description=textwrap.dedent(
                '''
                すでに公開済です。
                編集を行いたい場合は、【編集】を押してください。
                新しく投稿したい場合は、【削除】を押して作り直してください。
                '''
            )
        )

class Recruit_NotFoundData_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__裏募集: 未公開__",
            description=textwrap.dedent(
                '''
                裏募集が公開されていません。
                '''
            )
        )

class Recruit_New_Info_Embed(Embed):
    def __init__(self, anonymity):
        if anonymity == "Signed":
            recruit_type = "記名募集"
        else:
            recruit_type = "匿名募集"
        super().__init__(
            description=textwrap.dedent(
                f'''
                新しい{recruit_type}が公開されました。
                募集内容の確認は [コチラ](https://ptb.discord.com/channels/1421436016442740749/1443828612921823303)
                '''
            )
        )

class Recruit_Result_None_Embed(Embed):
    def __init__(self):
        super().__init__(
            description="閲覧可能な裏募集がありませんでした。"
        )

class Recruit_Check_Result_Embed(Embed):
    def __init__(self, number):
        super().__init__(
            description=f"{number}件の裏募集が見つかりました。"
        )

class Receive_Embed(Embed):
    def __init__(self, user_name, user_id, user_avatar_url, profile_url, number):
        super().__init__(
            title="立候補が届きました",
            description="ボタンを押すことで、連絡用のスレッドを作成します。"
        )
        self.add_field(name="__立候補者__", value=f"{user_name} (<@{user_id}>)", inline=False)
        self.add_field(name="__プロフィール__", value=f"{profile_url}")
        self.set_thumbnail(url=user_avatar_url)
        self.set_author(name=f"{user_id}")
        self.set_footer(text=number)

class Allow_Embed(Embed):
    def __init__(self, number):
        super().__init__(
            description="立候補が承認されました。"
        )
        self.set_footer(text=f"{number}")

class Recruit_Check_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="__裏募集確認__",
            description=textwrap.dedent(
                '''
                公開されている裏募集を確認できます。
                -# あなたが閲覧可能な裏募集がドロップダウンメニューで表示されます。
                -# 閲覧したい募集を選択してください。
                '''
            )
        )

class Recruit_NotFound_Data_Embed(Embed):
    def __init__(self):
        super().__init__(
            description="該当の募集は削除済です。"
        )

class P_Recruit_Panel_Embed(Embed):
    def __init__(self):
        super().__init__(
            title=f"{CUSTOM.OWL}__なう募集__",
            description=textwrap.dedent(
                '''
                男性/女性/全員に
                『誰か話そう』
                という募集をかけることができます。
                '''
            ),
            color=SERVER_COLORS.MAIN
        )

class P_Recruit_Set_Embed(Embed):
    def __init__(
            self, label: Optional[str], color: Optional[Union[int, discord.Colour]], user_name: Optional[str], user_id: Optional[int],
            user_avatar_url: Optional[str], gender: Optional[str], profile_url: Optional[str], comment: Optional[str] = None,
            ):
        super().__init__(
            title=f"__なう募集 - {label}__",
            description="誰か話そう！",
            color=color
        )
        self.add_field(name="__ユーザー__", value=f"{user_name} (<@{user_id}>)", inline=False)
        self.add_field(name="__プロフィール__", value=f"{profile_url}", inline=False)
        if comment is not None:
            self.add_field(name="__一言__", value=comment, inline=False)
        self.set_author(name=f"for {gender}")
        self.set_thumbnail(url=user_avatar_url)

class P_Recruit_Request_Embed(Embed):
    def __init__(self, author_name: Optional[str], author_id: Optional[int], author_avatar_url: Optional[str], comment: Optional[str]):
        super().__init__(
            title="✋️立候補",
        )
        self.add_field(name="__ユーザー__", value=f"{author_name} (<@{author_id}>)", inline=False)
        self.add_field(name="__一言__", value=f"{comment}", inline=False)
        self.set_thumbnail(url=author_avatar_url)

class P_Recruit_OK_Embed(Embed):
    def __init__(self):
        super().__init__(
            title="🤝マッチング",
            description=textwrap.dedent(
                '''
                立候補が承認されました。
                このスレッドは連絡を取るためにご利用ください。
                '''
            )
        )