from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import discord
from PIL import Image, ImageDraw, ImageFont

from pilmoji import Pilmoji

try:
    from pilmoji import getsize as pilmoji_getsize
except Exception:
    from pilmoji.helpers import getsize as pilmoji_getsize

from .level_math import progress_from_points_kind


PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parents[2]))
ASSETS = PROJECT_ROOT / "assets"

TEMPLATE_PATH = ASSETS / "images" / "elect_rank_back.png"
FONT_NAME     = ASSETS / "fonts" / "UDDigiKyokashoN-R.ttc"
FONT_NUM      = ASSETS / "fonts" / "Cinzel-Regular.ttf"
FONT_SERIF    = ASSETS / "fonts" / "NotoSerif-VariableFont_wdth,wght.ttf"
FONT_NUM_WGHT = 700  # NotoSerif variable weight

for _p in (TEMPLATE_PATH, FONT_NAME, FONT_NUM, FONT_SERIF):
    if not _p.exists():
        raise FileNotFoundError(f"missing asset: {_p}")


@dataclass(frozen=True)
class ElectRankCardData:
    tc_points: int
    vc_points: int


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class ElectRankCardImager:
    """elect_rank_back.png (940×400) にランク情報を合成する。"""

    # ── Avatar ────────────────────────────────────
    AVA_X    = 740
    AVA_Y    = 20
    AVA_SIZE = 180
    AVA_RING = 3

    # ── Name (背景フレーム内) ──────────────────────
    NAME_BOX_X = 735
    NAME_BOX_Y = 210
    NAME_BOX_W = 190
    NAME_BOX_H = 40
    NAME_MAX_W = 172
    NAME_BASE_SIZE = 20
    NAME_MIN_SIZE  = 10

    # ── TC セクション ────────────────────────────
    TC_LVL_X   = 405          # 背景 "TC" の右に level 番号
    TC_LVL_Y   = 40
    TC_BAR_X   = 330
    TC_BAR_Y   = 80
    TC_BAR_W   = 335          # 100% で右端 x=665
    TC_BAR_H   = 20
    TC_BAR_R   = 10
    TC_COLOR   = (0, 64, 255) # #0040ff

    # ── VC セクション ────────────────────────────
    VC_LVL_X   = 405
    VC_LVL_Y   = 140
    VC_BAR_X   = 330
    VC_BAR_Y   = 180
    VC_BAR_W   = 335
    VC_BAR_H   = 20
    VC_BAR_R   = 10
    VC_COLOR   = (255, 0, 225) # #ff00e1

    # ── 統計テキスト (右揃え) ────────────────────
    STAT_RIGHT_X = 720         # 数字ブロック右端 X
    TC_LINE1_Y   = 36          # "XXXXX/YYYYY"
    TC_LINE2_Y   = 57          # "next XXXXX"
    VC_LINE1_Y   = 135
    VC_LINE2_Y   = 155

    # ── Colors ───────────────────────────────────
    RING_COLOR = (255, 255, 255, 200)
    TEXT_WHITE = (255, 255, 255, 245)
    TEXT_DARK  = (30, 10, 60, 240)     # 名前バッジ内（背景が明るい場合）

    # ── Font sizes ───────────────────────────────
    LVL_SIZE  = 28   # "000" レベル番号
    STAT_SIZE = 17   # "XXXXX/YYYYY"
    NEXT_SIZE = 15   # "next XXXXX"

    def __init__(self) -> None:
        self.f_lvl  = self._load_num_font(self.LVL_SIZE)
        self.f_stat = self._load_num_font(self.STAT_SIZE)
        self.f_next = self._load_num_font(self.NEXT_SIZE)

    @staticmethod
    def _load_num_font(size: int) -> ImageFont.FreeTypeFont:
        f = ImageFont.truetype(str(FONT_SERIF), size)
        try:
            f.set_variation_by_axes([FONT_NUM_WGHT, 100])
        except Exception:
            try:
                f.set_variation_by_axes([FONT_NUM_WGHT])
            except Exception:
                pass
        return f

    async def build(self, *, user: discord.abc.User, data: ElectRankCardData) -> discord.File:
        base = Image.open(TEMPLATE_PATH).convert("RGBA")
        draw = ImageDraw.Draw(base)

        tc = progress_from_points_kind(data.tc_points, kind="text")
        vc = progress_from_points_kind(data.vc_points, kind="voice")

        # ── グラデーションバー ────────────────────
        self._draw_gradient_bar(base, self.TC_BAR_X, self.TC_BAR_Y,
                                self.TC_BAR_W, self.TC_BAR_H,
                                _clamp01(tc.ratio), self.TC_COLOR, self.TC_BAR_R)
        self._draw_gradient_bar(base, self.VC_BAR_X, self.VC_BAR_Y,
                                self.VC_BAR_W, self.VC_BAR_H,
                                _clamp01(vc.ratio), self.VC_COLOR, self.VC_BAR_R)

        # ── レベル番号（背景 TC/VC の右に） ──────
        draw.text((self.TC_LVL_X, self.TC_LVL_Y), str(tc.level),
                  font=self.f_lvl, fill=self.TEXT_WHITE)
        draw.text((self.VC_LVL_X, self.VC_LVL_Y), str(vc.level),
                  font=self.f_lvl, fill=self.TEXT_WHITE)

        # ── 統計テキスト 2行（右揃え） ──────────
        self._draw_right(draw, self.STAT_RIGHT_X, self.TC_LINE1_Y,
                         f"{tc.total_points}/{tc.points_at_next}", self.f_stat)
        self._draw_right(draw, self.STAT_RIGHT_X, self.TC_LINE2_Y,
                         f"next {tc.remain_to_next}", self.f_next)

        self._draw_right(draw, self.STAT_RIGHT_X, self.VC_LINE1_Y,
                         f"{vc.total_points}/{vc.points_at_next}", self.f_stat)
        self._draw_right(draw, self.STAT_RIGHT_X, self.VC_LINE2_Y,
                         f"next {vc.remain_to_next}", self.f_next)

        # ── アバター ──────────────────────────────
        avatar_bytes = await user.display_avatar.with_size(512).with_format("png").read()
        ava = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        ava = self._center_crop_square(ava).resize(
            (self.AVA_SIZE, self.AVA_SIZE), Image.LANCZOS)

        mask = Image.new("L", (self.AVA_SIZE, self.AVA_SIZE), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, self.AVA_SIZE-1, self.AVA_SIZE-1), fill=255)
        ava.putalpha(mask)
        base.alpha_composite(ava, (self.AVA_X, self.AVA_Y))

        # ── 名前（背景フレーム内に中央配置） ──────
        name_text = user.display_name
        name_font = self._fit_name_font(name_text)
        name_w, name_h = pilmoji_getsize(name_text, font=name_font)
        cx = self.NAME_BOX_X + self.NAME_BOX_W // 2
        cy = self.NAME_BOX_Y + self.NAME_BOX_H // 2
        nx = cx - name_w // 2
        ny = cy - name_h // 2

        with Pilmoji(base) as pilmoji:
            pilmoji.text((nx, ny), name_text, font=name_font, fill=self.TEXT_DARK)

        out = io.BytesIO()
        base.save(out, format="PNG")
        out.seek(0)
        return discord.File(fp=out, filename="elect_rank.png")

    # ──────────────────────────────────────────────
    def _draw_gradient_bar(self, base: Image.Image, x: int, y: int,
                           w: int, h: int, ratio: float,
                           color_end: tuple, radius: int) -> None:
        """白→color_end の水平グラデーション、50% 不透明、角丸 radius px。"""
        bar_w = max(1, int(w * ratio))

        t = np.linspace(0, 1, bar_w, dtype=np.float32)
        r = (255 * (1 - t) + color_end[0] * t).astype(np.uint8)
        g = (255 * (1 - t) + color_end[1] * t).astype(np.uint8)
        b = (255 * (1 - t) + color_end[2] * t).astype(np.uint8)
        a = np.full(bar_w, 128, dtype=np.uint8)  # 50% opacity

        row = np.stack([r, g, b, a], axis=1)          # (bar_w, 4)
        arr = np.tile(row, (h, 1, 1)).astype(np.uint8) # (h, bar_w, 4)

        grad = Image.fromarray(arr, "RGBA")

        # 角丸マスク（fill=128 で 50% 不透明）
        r_eff = min(radius, bar_w // 2, h // 2)
        mask = Image.new("L", (bar_w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, bar_w - 1, h - 1), radius=r_eff, fill=128)
        grad.putalpha(mask)

        base.alpha_composite(grad, (x, y))

    def _draw_right(self, draw: ImageDraw.ImageDraw, right_x: int, y: int,
                    text: str, font: ImageFont.FreeTypeFont) -> None:
        w = draw.textlength(text, font=font)
        draw.text((int(right_x - w), y), text, font=font, fill=self.TEXT_WHITE)

    def _fit_name_font(self, name: str) -> ImageFont.FreeTypeFont:
        size = self.NAME_BASE_SIZE
        while size >= self.NAME_MIN_SIZE:
            font = ImageFont.truetype(str(FONT_NAME), size)
            w, _ = pilmoji_getsize(name, font=font)
            if w <= self.NAME_MAX_W:
                return font
            size -= 2
        return ImageFont.truetype(str(FONT_NAME), self.NAME_MIN_SIZE)

    @staticmethod
    def _center_crop_square(im: Image.Image) -> Image.Image:
        w, h = im.size
        side = min(w, h)
        return im.crop(((w - side) // 2, (h - side) // 2,
                         (w + side) // 2, (h + side) // 2))
