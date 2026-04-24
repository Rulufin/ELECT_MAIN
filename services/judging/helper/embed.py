import textwrap
from typing import Optional

from discord import Embed, Member

from utils.colorcodes import COLORS

def extract_date_ymd(embed: Embed) -> Optional[str]:
    footer = embed.footer
    text = getattr(footer, "text", None)
    if not text:
        return None
    return text

def build_action_confirm_embed(
    *,
    target_user: Member,
    action_label: str,
) -> Embed:
    return Embed(
        description=textwrap.dedent(
            f"""
            {target_user.display_name} ({target_user.mention})
            に対して
            **{action_label}** を行います。

            本当によろしいですか？
            """
        ).strip(),
        color=COLORS.YELLOW,
    )