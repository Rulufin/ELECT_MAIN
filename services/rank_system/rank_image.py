from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

import discord
from PIL import Image, ImageDraw, ImageFont

from pilmoji import Pilmoji

# pilmoji の getsize はバージョン差があるので両対応
try:
    from pilmoji import getsize as pilmoji_getsize  # newer
except Exception:
    from pilmoji.helpers import getsize as pilmoji_getsize  # fallback


PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parents[2]))
ASSETS = PROJECT_ROOT / "assets"

TEMPLATE_PATH = ASSETS / "images" / "rank_back.png"

FONT_NAME = ASSETS / "fonts" / "UDDigiKyokashoN-R.ttc"
FONT_NUM = ASSETS / "fonts" / "Cinzel-Regular.ttf"

for p in (TEMPLATE_PATH, FONT_NAME, FONT_NUM):
    if not p.exists():
        raise FileNotFoundError(f"missing asset: {p}")


@dataclass(frozen=True)
class RankCardData:
    text_level: int
    text_total: int
    text_next_total: int
    text_into: int
    text_need: int

    voice_level: int
    voice_total: int
    voice_next_total: int
    voice_into: int
    voice_need: int


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1.0 else x


class RankCardImager:
    def __init__(self) -> None:
        with Image.open(TEMPLATE_PATH) as im:
            self.TPL_W, self.TPL_H = im.size

        self.AVA_X, self.AVA_Y = 20, 20
        self.AVA_SIZE = 300

        self.NAME_TOP_GAP = 20
        self.NAME_MAX_W = 240

        self.BAR_X = 340
        self.TEXT_BAR_Y = 120
        self.VOICE_BAR_Y = 290
        self.BAR_W, self.BAR_H = 580, 40

        self.RIGHT_X = self.BAR_X + self.BAR_W

        self.TEXT_LVL_X = 340
        self.TEXT_LVL_Y = 65
        self.TEXT_EXP_Y = 46.5
        self.TEXT_NEXT_Y = 80

        self.VOICE_LVL_X = 340
        self.VOICE_LVL_Y = 235
        self.VOICE_EXP_Y = 215
        self.VOICE_NEXT_Y = 250

        self.PCT_SIZE = 30
        self.PCT_PAD_IN = 12
        self.PCT_PAD_OUT = 12
        self.PCT_Y_OFFSET = -4

        self.TEXT_PCT_CENTER_Y = self.TEXT_BAR_Y + self.BAR_H // 2
        self.VOICE_PCT_CENTER_Y = self.VOICE_BAR_Y + self.BAR_H // 2

        self.FILL = (210, 170, 110, 180)
        self.TEXT = (255, 255, 255, 235)
        self.TEXT_SOFT = (255, 255, 255, 190)

        self.name_base_size = 30
        self.name_min_size = 16

        self.f_lvl = ImageFont.truetype(str(FONT_NUM), 48)
        self.f_num = ImageFont.truetype(str(FONT_NUM), 29)
        self.f_pct = ImageFont.truetype(str(FONT_NUM), self.PCT_SIZE)

        # 名前フォントは毎回 truetype してるので、必要ならキャッシュしてもOK
        # self._name_font_cache: dict[int, ImageFont.FreeTypeFont] = {}

    async def build(self, *, user: discord.abc.User, data: RankCardData) -> discord.File:
        base = Image.open(TEMPLATE_PATH).convert("RGBA")
        draw = ImageDraw.Draw(base)

        # -------------------------
        # Avatar
        # -------------------------
        avatar_asset = user.display_avatar.with_size(512).with_format("png")
        avatar_bytes = await avatar_asset.read()
        ava = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        ava = self._center_crop_square(ava).resize((self.AVA_SIZE, self.AVA_SIZE), Image.LANCZOS)
        base.alpha_composite(ava, (self.AVA_X, self.AVA_Y))

        # -------------------------
        # Name (display_name + pilmoji)
        #   → 絵文字部分だけ補完する意図なので、ここだけ Pilmoji で描画
        # -------------------------
        name_text = user.display_name  # nick を含む（絵文字入りが多い）
        name_top = self.AVA_Y + self.AVA_SIZE + self.NAME_TOP_GAP
        name_center_x = self.AVA_X + self.AVA_SIZE // 2

        name_font = self._fit_name_font(name_text)

        # pilmoji の getsize で絵文字込みの幅を取る
        name_w, _ = pilmoji_getsize(name_text, font=name_font)
        name_x = int(round(name_center_x - (name_w / 2.0)))

        # 名前だけ pilmoji で描画（他は従来通り ImageDraw）
        with Pilmoji(base) as pilmoji:
            pilmoji.text(
                (name_x, name_top),
                name_text,
                font=name_font,
                fill=self.TEXT,
                # 必要なら微調整
                # emoji_scale_factor=1.0,
                # emoji_position_offset=(0, -2),
            )

        # -------------------------
        # Progress
        # -------------------------
        t_prog = clamp01(float(data.text_into) / max(int(data.text_need), 1))
        v_prog = clamp01(float(data.voice_into) / max(int(data.voice_need), 1))

        self._draw_fill(draw, self.BAR_X, self.TEXT_BAR_Y, t_prog)
        self._draw_fill(draw, self.BAR_X, self.VOICE_BAR_Y, v_prog)

        self._draw_percent_smart(draw, self.BAR_X, self.TEXT_BAR_Y, t_prog, self.TEXT_PCT_CENTER_Y)
        self._draw_percent_smart(draw, self.BAR_X, self.VOICE_BAR_Y, v_prog, self.VOICE_PCT_CENTER_Y)

        # -------------------------
        # Text labels
        # -------------------------
        self._draw_left(draw, self.TEXT_LVL_X, self.TEXT_LVL_Y, f"Lvl : {data.text_level}", self.f_lvl)
        self._draw_left(draw, self.VOICE_LVL_X, self.VOICE_LVL_Y, f"Lvl : {data.voice_level}", self.f_lvl)

        self._draw_right(draw, self.RIGHT_X, self.TEXT_EXP_Y, f"Exp : {data.text_total}", self.f_num)
        self._draw_right(draw, self.RIGHT_X, self.TEXT_NEXT_Y, f"Next : {data.text_next_total}", self.f_num)

        self._draw_right(draw, self.RIGHT_X, self.VOICE_EXP_Y, f"Exp : {data.voice_total}", self.f_num)
        self._draw_right(draw, self.RIGHT_X, self.VOICE_NEXT_Y, f"Next Lvl : {data.voice_next_total}", self.f_num)

        out = io.BytesIO()
        base.save(out, format="PNG")
        out.seek(0)
        return discord.File(fp=out, filename="rank.png")

    def _fit_name_font(self, name: str) -> ImageFont.FreeTypeFont:
        """
        名前の幅が NAME_MAX_W に収まるようにフォントサイズを調整。
        絵文字込みで幅を測るため pilmoji_getsize を使う。
        """
        size = self.name_base_size
        while size >= self.name_min_size:
            font = ImageFont.truetype(str(FONT_NAME), size)
            w, _ = pilmoji_getsize(name, font=font)
            if w <= self.NAME_MAX_W:
                return font
            size -= 2
        return ImageFont.truetype(str(FONT_NAME), self.name_min_size)

    def _draw_fill(self, draw: ImageDraw.ImageDraw, x: int, y: int, p: float) -> None:
        fw = int(self.BAR_W * p)
        if fw > 0:
            draw.rectangle((x, y, x + fw, y + self.BAR_H), fill=self.FILL)

    def _draw_percent_smart(self, draw: ImageDraw.ImageDraw, bar_x: int, bar_y: int, p: float, y_center: int) -> None:
        pct_text = f"{int(p * 100)}%"
        pct_w = float(draw.textlength(pct_text, font=self.f_pct))
        fill_w = float(int(self.BAR_W * p))

        if fill_w >= pct_w + self.PCT_PAD_IN * 2:
            x = bar_x + fill_w - self.PCT_PAD_IN - pct_w
        else:
            x = bar_x + fill_w + self.PCT_PAD_OUT

        min_x = bar_x + self.PCT_PAD_IN
        max_x = bar_x + self.BAR_W - self.PCT_PAD_IN - pct_w
        if x < min_x:
            x = min_x
        if x > max_x:
            x = max_x

        y = float(y_center) - (self.PCT_SIZE / 2) + self.PCT_Y_OFFSET
        draw.text((int(round(x)), int(round(y))), pct_text, font=self.f_pct, fill=self.TEXT_SOFT)

    def _draw_right(self, draw: ImageDraw.ImageDraw, right_x: int, y: float, text: str, font: ImageFont.FreeTypeFont) -> None:
        w = draw.textlength(text, font=font)
        draw.text((right_x - w, int(round(y))), text, font=font, fill=self.TEXT)

    def _draw_left(self, draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.FreeTypeFont) -> None:
        draw.text((x, y), text, font=font, fill=self.TEXT)

    @staticmethod
    def _center_crop_square(im: Image.Image) -> Image.Image:
        w, h = im.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        return im.crop((left, top, left + side, top + side))
