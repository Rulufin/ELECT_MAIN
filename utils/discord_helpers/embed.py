import re
from typing import Optional

from discord import Embed, Message

USER_ID_RE = re.compile(r"(\d{15,25})")

def get_first_embed_from_message(message: Message | None) -> Embed | None:
    if message is None or not message.embeds:
        return None
    return message.embeds[0]


def get_embed_footer_text(embed: Embed) -> str | None:
    footer = embed.footer
    text = getattr(footer, "text", None)
    return text or None


def extract_user_id_from_author_url(embed: Embed) -> Optional[int]:
    author = embed.author
    author_url = getattr(author, "url", None)
    if not author_url:
        return None

    match = USER_ID_RE.search(author_url or "")
    if not match:
        return None

    return int(match.group(1))


def extract_user_id_from_author_name(embed: Embed) -> Optional[int]:
    author = embed.author
    author_name = getattr(author, "name", None)
    if not author_name:
        return None

    match = USER_ID_RE.search(author_name or "")
    if not match:
        return None

    return int(match.group(1))