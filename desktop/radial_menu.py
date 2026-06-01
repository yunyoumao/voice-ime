"""鼠标中键环形菜单：纯几何命中 + PIL 抗锯齿渲染 + 状态浮窗(动效)。

- MenuGeometry：纯函数命中(hit_test 高亮 / zone 松开判区)，可无 GUI 单测。
- RadialMenu：进程唯一 tk root；6 瓣环形 + 中心 hub 实时显示选中模式。
- StatusHud：贴光标状态浮窗，Siri/EQ 式跳动条。
- 三套主题(purple/green/cream)，config: mouse_menu.theme 切换。

绘制走 PIL(Image/ImageDraw)：4× 超采样 + LANCZOS 缩放 = 真·抗锯齿(tkinter Canvas
本身不抗锯齿，弧线必锯齿，故必须离屏渲染再贴图)。透明：图像 flatten 到主题 key 色，
窗口 -transparentcolor=key 抠掉四角；AA 边缘渐隐到 key → 柔和无台阶。

所有方法必须在创建 tk 的线程(main.py 事件循环主线程)调用；pynput 回调经
loop.call_soon_threadsafe 转移到主线程再调本类。
角度约定：屏幕坐标 atan2(dy,dx)(+Y 向下)；PIL 同为 y 向下，故绘制与 hit_test 同式。
"""
from __future__ import annotations

import collections
import math
import sys
from dataclasses import dataclass

MODES = ["raw", "polish", "translate_zh", "translate_ja", "translate_en", "summary"]
LABELS = ["直接打字", "语音润色", "译中", "译日", "译英", "总结"]

# 每个主题自带 key(透明抠图色)：取一个调色板里绝不出现、且与边缘亮度接近的色，
# 让 AA 边缘渐隐过去几乎无光晕(深色主题→近黑；奶白→近白)。
THEMES = {
    "purple": {  # 淡紫系（默认）— 静雅深紫 + 柔和丁香高亮
        "key": "#0c0a12",
        "wedge": "#2b2540", "wedge_hi": "#a98fe6", "accent": "#8a6fd6",
        "hub": "#191325", "hub_text": "#f4efff", "label": "#c2b6e0", "label_hi": "#ffffff",
        "hud_bg": "#191325", "hud_text": "#f4efff", "track": "#3a3357",
    },
    "green": {   # 墨绿系
        "key": "#06100c",
        "wedge": "#1f3a31", "wedge_hi": "#5bbf9f", "accent": "#3f9d82",
        "hub": "#102a22", "hub_text": "#ecf7f1", "label": "#b9d6ca", "label_hi": "#ffffff",
        "hud_bg": "#102a22", "hud_text": "#ecf7f1", "track": "#274a3f",
    },
    "cream": {   # 奶白系（浅色）
        "key": "#fdfcf8",
        "wedge": "#ece2cd", "wedge_hi": "#caa15f", "accent": "#b88d4a",
        "hub": "#f6efdf", "hub_text": "#473b28", "label": "#6f6149", "label_hi": "#2c2316",
        "hud_bg": "#f6efdf", "hud_text": "#473b28", "track": "#dccfb3",
    },
}

_SS = 4          # 超采样倍数(菜单)：4× 离屏再缩 → 抗锯齿
_FONT_CACHE: dict = {}


def theme_of(cfg: dict | None) -> dict:
    name = str(((cfg or {}).get("mouse_menu") or {}).get("theme", "purple")).lower()
    return THEMES.get(name, THEMES["purple"])


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _font(px: int, bold: bool = False):
    """缓存的 YaHei truetype(给 PIL 用)；缺失则退化默认字体。"""
    from PIL import ImageFont
    key = (px, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    cands = (["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc"] if bold
             else ["C:/Windows/Fonts/msyh.ttc"])
    f = None
    for p in cands:
        try:
            f = ImageFont.truetype(p, px)
            break
        except Exception:
            continue
    if f is None:
        f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def _arc_pts(cx, cy, r, a0, a1, steps=28):
    out = []
    for k in range(steps + 1):
        ang = math.radians(a0 + (a1 - a0) * k / steps)
        out.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return out


def _seg_mask(W, cx, cy, ri, ro, indices, g, ss):
    """把若干瓣画进一张 L 掩膜，再 blur+threshold 把四角磨圆(无台阶、不溢色)。"""
    from PIL import Image, ImageDraw, ImageFilter
    m = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(m)
    for i in indices:
        a0, a1 = i * 60 + g, i * 60 + 60 - g
        pts = _arc_pts(cx, cy, ro, a0, a1) + _arc_pts(cx, cy, ri, a1, a0)
        d.polygon(pts, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(ss * 2.4))
    return m.point(lambda v: 255 if v >= 130 else 0)


def _draw_icon(d, idx, cx, cy, r, color):
    """在 (cx,cy) 画第 idx 个模式的矢量图标(坐标已是超采样尺度)。
    idx: 0 键盘(直接打字) 1 ✨(润色) 2/3/4 译 ZH/JA/EN 徽章 5 列表(总结)。"""
    w = max(2, int(r * 0.15))
    if idx == 0:                                         # 键盘
        d.rounded_rectangle((cx - r, cy - r * 0.6, cx + r, cy + r * 0.6), radius=r * 0.22,
                            outline=color, width=w)
        dot = max(1, int(w * 0.7))
        for ky in (-0.18, 0.18):
            for kx in (-0.6, -0.2, 0.2, 0.6):
                d.ellipse((cx + kx * r - dot, cy + ky * r - dot, cx + kx * r + dot, cy + ky * r + dot),
                          fill=color)
    elif idx == 1:                                       # ✨ 四角星 + 小星点
        pts = []
        for k in range(8):
            ang = math.radians(k * 45 - 90)
            rad = r if k % 2 == 0 else r * 0.34
            pts += [cx + rad * math.cos(ang), cy + rad * math.sin(ang)]
        d.polygon(pts, fill=color)
        sr, sx, sy = r * 0.32, cx + r * 0.72, cy - r * 0.72
        d.polygon([sx, sy - sr, sx + sr * 0.34, sy, sx, sy + sr, sx - sr * 0.34, sy], fill=color)
    elif idx in (2, 3, 4):                               # 译：圆环徽章 + 拉丁码(无汉字)
        code = {2: "ZH", 3: "JA", 4: "EN"}[idx]
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=w)
        d.text((cx, cy), code, font=_font(int(r * 0.8), bold=True), fill=color, anchor="mm")
    else:                                                # 列表(总结)：项目符号 + 横线
        for ly in (-0.55, -0.18, 0.19, 0.56):
            d.ellipse((cx - r * 0.92 - w, cy + ly * r - w, cx - r * 0.92 + w, cy + ly * r + w), fill=color)
            d.line((cx - r * 0.6, cy + ly * r, cx + r * 0.78, cy + ly * r), fill=color, width=w)


def render_menu_image(size, inner, outer, highlight, theme, glass=False):
    """纯 PIL 渲染环形菜单 → flatten 到 key 色的 RGB 图(不依赖 Tk，可离屏存 PNG 验证)。
    glass=True：静止瓣不填色、留 key(→透出毛玻璃磨砂)，只描边定形 → 整个控制器底儿都是玻璃；
    仅高亮瓣填实色突出。配合窗口亚克力 + set_opacity(key) 使用。"""
    from PIL import Image, ImageDraw, ImageFilter
    S = _SS
    W = size * S
    cx = cy = W / 2
    ri, ro = inner * S, outer * S
    g = 4
    hi = highlight

    base = Image.new("RGBA", (W, W), (0, 0, 0, 0))

    rest = [i for i in range(6) if i != hi]
    if glass:                                            # 玻璃：静止瓣留空(→key→磨砂)，仅描边定形
        od = ImageDraw.Draw(base)
        for i in rest:
            a0, a1 = i * 60 + g, i * 60 + 60 - g
            pts = _arc_pts(cx, cy, ro, a0, a1) + _arc_pts(cx, cy, ri, a1, a0)
            od.line(pts + [pts[0]], fill=_rgb(theme["accent"]), width=int(2.4 * S), joint="curve")
    elif rest:
        rmask = _seg_mask(W, cx, cy, ri, ro, rest, g, S)
        solid = Image.new("RGBA", (W, W), _rgb(theme["wedge"]) + (255,))
        base = Image.composite(solid, base, rmask)

    if hi is not None:                                   # 高亮瓣：凸出 + 柔光辉垫底
        hmask = _seg_mask(W, cx, cy, ri, ro + 8 * S, [hi], g, S)
        galpha = hmask.filter(ImageFilter.GaussianBlur(S * 7)).point(lambda v: int(v * 0.55))
        glow = Image.new("RGBA", (W, W), _rgb(theme["accent"]) + (0,))
        glow.putalpha(galpha)
        base = Image.alpha_composite(glow, base)
        solid_hi = Image.new("RGBA", (W, W), _rgb(theme["wedge_hi"]) + (255,))
        base = Image.composite(solid_hi, base, hmask)

    d = ImageDraw.Draw(base)
    Rm = (inner + outer) / 2 * S
    for i in range(6):                                   # 6 瓣矢量图标(去汉字)
        on = (i == hi)
        a = math.radians(i * 60 + 30)
        _draw_icon(d, i, cx + Rm * math.cos(a), cy + Rm * math.sin(a), 17 * S,
                   _rgb(theme["label_hi"] if on else theme["label"]))
    hr = (inner - 6) * S                                 # 中心 hub：放大显示当前选中图标(未选=直接打字)
    d.ellipse((cx - hr, cy - hr, cx + hr, cy + hr),
              fill=(None if glass else _rgb(theme["hub"])),   # 玻璃：hub 也留空→磨砂
              outline=_rgb(theme["accent"]), width=int(2 * S))
    _draw_icon(d, hi if hi is not None else 0, cx, cy, 22 * S, _rgb(theme["hub_text"]))

    base = base.resize((size, size), Image.LANCZOS)      # 缩小 = 抗锯齿
    flat = Image.new("RGB", (size, size), _rgb(theme["key"]))
    flat.paste(base, (0, 0), base)                       # 四角=key，随后被 -transparentcolor 抠透
    return flat


def make_frost(shot_rgb, blur=18, saturate=1.8, tint=(22, 24, 42, 120)):
    """把"菜单背后的屏幕截图"做成苹果风磨砂底：高斯模糊 + 提饱和(saturate 180%) + 暗蓝 tint。
    tint 的 alpha 越大越暗(白描边/图标越清晰)、越小越透。返回 RGBA。"""
    from PIL import Image, ImageEnhance, ImageFilter
    f = shot_rgb.convert("RGB").filter(ImageFilter.GaussianBlur(blur))
    f = ImageEnhance.Color(f).enhance(saturate).convert("RGBA")
    return Image.alpha_composite(f, Image.new("RGBA", f.size, tuple(tint)))


def _wedge_shape(size, indices, inner, outer, ss=3, fillet_px=2.8, band_px=1.7):
    """给定瓣的(填充mask, 描边mask)，均圆角(blur+阈值)、描边由腐蚀得到 → 与磨砂边完全贴合、全圆角。"""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    W = size * ss
    cx = cy = W / 2
    ri, ro = inner * ss, outer * ss
    g = 4
    m = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(m)
    for i in indices:
        a0, a1 = i * 60 + g, i * 60 + 60 - g
        pts = _arc_pts(cx, cy, ro, a0, a1) + _arc_pts(cx, cy, ri, a1, a0)
        d.polygon(pts, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(fillet_px * ss)).point(lambda v: 255 if v >= 128 else 0)  # 圆角
    eroded = m.filter(ImageFilter.GaussianBlur(band_px * ss)).point(lambda v: 255 if v >= 185 else 0)  # 高斯腐蚀(比 MinFilter 快很多)
    edge = ImageChops.subtract(m, eroded)
    return m.resize((size, size), Image.LANCZOS), edge.resize((size, size), Image.LANCZOS)


def _disc_mask(size, r, ss=3):
    from PIL import Image, ImageDraw
    W = size * ss
    cx = cy = W / 2
    rr = r * ss
    m = Image.new("L", (W, W), 0)
    ImageDraw.Draw(m).ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=255)
    return m.resize((size, size), Image.LANCZOS)


def _tint_layer(rgb, alpha_mask, scale=1.0):
    """实色 rgb、alpha=alpha_mask*scale 的 RGBA 层(用掩膜上色，边缘随掩膜抗锯齿)。"""
    from PIL import Image
    layer = Image.new("RGBA", alpha_mask.size, tuple(rgb) + (0,))
    layer.putalpha(alpha_mask if scale == 1.0 else alpha_mask.point(lambda v: int(v * scale)))
    return layer


def _glass_icons(size, inner, outer, highlight, ss=3):
    """白图标 + hub 白圈(超采样抗锯齿)，RGBA 透明底。"""
    from PIL import Image, ImageDraw
    W = size * ss
    cx = cy = W / 2
    ov = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    WHITE_ICON = (255, 255, 255, 242)
    Rm = (inner + outer) / 2 * ss
    for i in range(6):
        a = math.radians(i * 60 + 30)
        _draw_icon(d, i, cx + Rm * math.cos(a), cy + Rm * math.sin(a), 17 * ss, WHITE_ICON)
    hr = (inner - 6) * ss
    d.ellipse((cx - hr, cy - hr, cx + hr, cy + hr), outline=(255, 255, 255, 170), width=int(2 * ss))
    _draw_icon(d, highlight if highlight is not None else 0, cx, cy, 22 * ss, WHITE_ICON)
    return ov.resize((size, size), Image.LANCZOS)


_GLASS_LAYER_CACHE: dict = {}    # (size,inner,outer,highlight) → (花瓣alpha掩膜, 内容层)；几何相关、与背景无关 → 缓存


def _glass_layers(size, inner, outer, highlight):
    """几何相关的(花瓣 alpha 掩膜, 内容层 RGBA)。只随 highlight 变(7种)→ 缓存，避免运行时重算昂贵的 mask。
    内容层 = 白描边 + 白图标 + periwinkle 高亮(填充/柔光/亮描边)，与背景无关，可直接叠到任意磨砂底上。"""
    key = (size, inner, outer, highlight)
    cached = _GLASS_LAYER_CACHE.get(key)
    if cached is not None:
        return cached
    from PIL import Image, ImageChops, ImageFilter
    rest = [i for i in range(6) if i != highlight]
    rfill, redge = _wedge_shape(size, rest, inner, outer)
    petal_alpha = ImageChops.lighter(rfill, _disc_mask(size, inner - 2))   # 静止瓣 + 中心 hub 盘
    hfill = hedge = None
    if highlight is not None:
        hfill, hedge = _wedge_shape(size, [highlight], inner, outer + 8)    # 高亮瓣外凸 8px
        petal_alpha = ImageChops.lighter(petal_alpha, hfill)
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if hfill is not None:                                          # 高亮柔光辉 + periwinkle 半透填充
        overlay = Image.alpha_composite(overlay, _tint_layer((166, 179, 248),
                                                             hfill.filter(ImageFilter.GaussianBlur(7)), 0.5))
        overlay = Image.alpha_composite(overlay, _tint_layer((166, 179, 248), hfill, 0.40))
    overlay = Image.alpha_composite(overlay, _tint_layer((255, 255, 255), redge, 0.60))    # 静止瓣白描边
    if hedge is not None:
        overlay = Image.alpha_composite(overlay, _tint_layer((210, 218, 255), hedge, 0.95))  # 高亮亮描边
    overlay = Image.alpha_composite(overlay, _glass_icons(size, inner, outer, highlight))    # 白图标 + hub 圈
    _GLASS_LAYER_CACHE[key] = (petal_alpha, overlay)
    return petal_alpha, overlay


def compose_menu_glass(frost_rgba, inner, outer, highlight):
    """磨砂底 + 缓存的玻璃内容层 → RGBA(瓣外透明)。运行时只做 putalpha + 1 次合成 → 高亮切换零卡顿。"""
    from PIL import Image
    petal_alpha, overlay = _glass_layers(frost_rgba.width, inner, outer, highlight)
    frosted = frost_rgba.copy()
    frosted.putalpha(petal_alpha)                                  # 仅花瓣+hub 磨砂，其余 alpha=0
    return Image.alpha_composite(frosted, overlay)


def _frost_card_mask(W, H, radius=18, ss=3):
    """浮窗圆角卡片形 alpha 掩膜(卡外=0)。"""
    from PIL import Image, ImageDraw
    Wp, Hp = W * ss, H * ss
    m = Image.new("L", (Wp, Hp), 0)
    ImageDraw.Draw(m).rounded_rectangle((ss, ss, Wp - ss, Hp - ss), radius=radius * ss, fill=255)
    return m.resize((W, H), Image.LANCZOS)


def render_hud_glass_content(W, H, mode, frame, levels=None, progress=0.0, done=False, ss=3):
    """浮窗玻璃版"内容层"(白/periwinkle 声波 或 流动进度条)，透明底，叠到磨砂圆角卡片上。"""
    from PIL import Image, ImageDraw
    Wp, Hp = W * ss, H * ss
    img = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ACC = (180, 191, 250, 240)                           # periwinkle 亮(与轮盘高亮同系)
    midy = Hp * 0.5
    if mode == "process":
        pad = 20 * ss
        bx0, bx1, bh = pad, Wp - pad, 8 * ss
        cyk = midy - 13 * ss
        p = 1.0 if done else max(0.05, min(0.97, progress))
        d.rounded_rectangle((bx0, midy - bh / 2, bx1, midy + bh / 2), radius=bh / 2, fill=(255, 255, 255, 60))
        d.rounded_rectangle((bx0, midy - bh / 2, bx0 + (bx1 - bx0) * p, midy + bh / 2), radius=bh / 2, fill=ACC)
        if done:
            k = 5 * ss
            d.line([(Wp / 2 - k, cyk), (Wp / 2 - k * 0.2, cyk + k * 0.7), (Wp / 2 + k, cyk - k * 0.7)],
                   fill=(255, 255, 255, 245), width=max(2, int(2 * ss)), joint="curve")
        else:
            d.text((Wp / 2, cyk), f"{int(p * 100)}%", font=_font(int(11 * ss), bold=True),
                   fill=(235, 240, 255, 245), anchor="mm")
    else:                                                # listen：滚动声波
        vals = list(levels or [])
        nb, pad = 20, 14 * ss
        span = Wp - 2 * pad
        slot = span / nb
        bw = slot * 0.55
        vals = [0.0] * (nb - len(vals)) + vals[-nb:]
        maxh = 0.34 * Hp
        for i, v in enumerate(vals):
            idle = 0.10 * (0.5 + 0.5 * math.sin(frame * 0.3 + i * 0.5))
            vv = max(idle, min(1.0, v))
            x = pad + slot * (i + 0.5)
            h = 2 * ss + (maxh - 2 * ss) * vv
            d.rounded_rectangle((x - bw / 2, midy - h, x + bw / 2, midy + h), radius=bw / 2, fill=ACC)
    return img.resize((W, H), Image.LANCZOS)


def render_hud_image(W, H, mode, frame, theme, levels=None, progress=0.0, done=False, ss=3):
    """纯 PIL 渲染状态浮窗(不依赖 Tk)。
    mode='listen' → 随真实音量起伏的滚动声波条；mode='process' → 0→100% 进度条(done=完成跳满)。
    """
    from PIL import Image, ImageDraw
    Wp, Hp = W * ss, H * ss
    img = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2 * ss, 2 * ss, Wp - 2 * ss, Hp - 2 * ss), radius=int(18 * ss),
                        fill=_rgb(theme["hud_bg"]), outline=_rgb(theme["accent"]), width=max(1, ss))
    midy = Hp * 0.5
    if mode == "process":                                # 处理中：0→进度填充条 + 百分比(完成跳满+对勾)
        pad = 20 * ss
        bx0, bx1, bh = pad, Wp - pad, 8 * ss
        cyk = midy - 13 * ss
        p = 1.0 if done else max(0.05, min(0.97, progress))
        d.rounded_rectangle((bx0, midy - bh / 2, bx1, midy + bh / 2), radius=bh / 2, fill=_rgb(theme["track"]))
        d.rounded_rectangle((bx0, midy - bh / 2, bx0 + (bx1 - bx0) * p, midy + bh / 2),
                            radius=bh / 2, fill=_rgb(theme["accent"]))
        if done:                                         # 完成 → 矢量对勾(字体 ✓ 常缺字→手画)
            k = 5 * ss
            d.line([(Wp / 2 - k, cyk), (Wp / 2 - k * 0.2, cyk + k * 0.7), (Wp / 2 + k, cyk - k * 0.7)],
                   fill=_rgb(theme["accent"]), width=max(2, int(2 * ss)), joint="curve")
        else:
            d.text((Wp / 2, cyk), f"{int(p * 100)}%", font=_font(int(11 * ss), bold=True),
                   fill=_rgb(theme["hud_text"]), anchor="mm")
    else:                                                # listen：滚动声波(随真实音量起伏)
        vals = list(levels or [])
        nb, pad = 20, 14 * ss
        span = Wp - 2 * pad
        slot = span / nb
        bw = slot * 0.55
        vals = [0.0] * (nb - len(vals)) + vals[-nb:]
        maxh = 0.34 * Hp
        for i, v in enumerate(vals):
            idle = 0.10 * (0.5 + 0.5 * math.sin(frame * 0.3 + i * 0.5))   # 静音时也有轻微呼吸
            vv = max(idle, min(1.0, v))
            x = pad + slot * (i + 0.5)
            h = 2 * ss + (maxh - 2 * ss) * vv
            d.rounded_rectangle((x - bw / 2, midy - h, x + bw / 2, midy + h), radius=bw / 2,
                                fill=_rgb(theme["accent"]))
    img = img.resize((W, H), Image.LANCZOS)
    flat = Image.new("RGB", (W, H), _rgb(theme["key"]))
    flat.paste(img, (0, 0), img)
    return flat


def cursor_xy() -> tuple[int, int]:
    """当前鼠标光标屏幕坐标（Windows）。键盘触发菜单时用它定位/命中。"""
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)
    except Exception:
        return 0, 0


@dataclass
class MenuGeometry:
    """环形命中判定（屏幕坐标，+Y 向下）。纯函数、可单测。"""
    center_x: float
    center_y: float
    inner_radius: float = 55.0
    outer_radius: float = 160.0

    def hit_test(self, x: float, y: float) -> int | None:
        dx, dy = x - self.center_x, y - self.center_y
        r = math.hypot(dx, dy)
        if r < self.inner_radius or r > self.outer_radius:
            return None                       # 中心死区 / 环外 → 不高亮任何瓣
        ang = math.degrees(math.atan2(dy, dx)) % 360.0
        return int(ang // 60) % 6

    def zone(self, x: float, y: float):
        """松开判区：int(瓣 0-5) | 'center'(死区,默认直接打字) | 'outside'(环外,取消)。"""
        dx, dy = x - self.center_x, y - self.center_y
        r = math.hypot(dx, dy)
        if r < self.inner_radius:
            return "center"
        if r > self.outer_radius:
            return "outside"
        ang = math.degrees(math.atan2(dy, dx)) % 360.0
        return int(ang // 60) % 6


class RadialMenu:
    def __init__(self, cfg: dict | None = None) -> None:
        import tkinter as tk
        mm = (cfg or {}).get("mouse_menu", {}) or {}
        self._inner = float(mm.get("inner_radius", 55))
        self._outer = float(mm.get("outer_radius", 160))
        self._size = int(self._outer * 2 + 48)    # 余量给高亮凸出 + 柔光辉
        self._highlight: int | None = None
        self._visible = False
        self._saved_hwnd = None
        self._photo = None
        self._img_item = None
        self.theme = theme_of(cfg)
        self._key = self.theme["key"]
        self._glass = bool(mm.get("glass", False)) and sys.platform == "win32"   # 毛玻璃(逐像素 alpha)
        self._glass_tint = (22, 24, 42, int(mm.get("glass_tint_alpha", 78)))      # 暗蓝 tint(越小越透)
        self._frost = None                          # 缓存的磨砂底(show 时截屏一次，高亮变化复用)
        self._left = self._top = 0
        self.geom = MenuGeometry(0.0, 0.0, self._inner, self._outer)

        self._glass_hwnd = None
        self.root = tk.Tk()                          # 始终建隐藏 tk root：HUD/pump/main.py 都依赖它
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if self._glass:                              # 玻璃菜单：独立原生层窗显示(tkinter 不碰它→不被重绘擦掉)
            try:
                from desktop import glass_window
                self._glass_hwnd = glass_window.create_glass_window()
                glass_window.set_layered(self._glass_hwnd)
                glass_window.apply_noactivate(self._glass_hwnd)
            except Exception as e:
                print(f"[RadialMenu] 原生玻璃窗创建失败，回退 v3: {e}")
                self._glass = False
            if self._glass:                          # 预热 7 种高亮的几何层缓存 → 运行时高亮切换零卡顿
                try:
                    for _h in (None, 0, 1, 2, 3, 4, 5):
                        _glass_layers(self._size, self._inner, self._outer, _h)
                except Exception:
                    pass
        if not self._glass:                          # 回退：transparentcolor + alpha + canvas(v3)
            try:
                self.root.attributes("-transparentcolor", self._key)
            except Exception:
                pass
            try:
                self.root.attributes("-alpha", 0.96)
            except Exception:
                pass
            self.root.configure(bg=self._key)
            self._canvas = tk.Canvas(self.root, width=self._size, height=self._size,
                                     bg=self._key, highlightthickness=0, bd=0)
            self._canvas.pack()
        self.root.withdraw()                         # 隐藏 root：玻璃模式它从不显示，仅作 tkinter 机器/HUD 父窗

    def pump(self) -> None:
        # 始终泵 tk root：它只刷新隐藏 root + 泵线程消息队列(含原生玻璃窗的消息)，不碰原生窗的 ULW 内容 → 不冲突。
        try:
            self.root.update()
        except Exception:
            pass

    def show(self, x: int, y: int) -> None:
        self.geom.center_x, self.geom.center_y = float(x), float(y)
        self._highlight = None
        left, top = int(x - self._size / 2), int(y - self._size / 2)
        self._left, self._top = left, top
        if self._glass and self._glass_hwnd:
            # 原生窗模式：截屏、合成、显示
            self._grab_frost()
            self._save_focus()
            try:
                from desktop import glass_window
                img = compose_menu_glass(self._frost, self._inner, self._outer, None)
                glass_window.show_glass_window(self._glass_hwnd, left, top, self._size, self._size)
                glass_window.show_layered_image(self._glass_hwnd, img, left, top)
            except Exception as e:
                print(f"[RadialMenu.show] glass display failed: {e}")
            self._restore_focus()
        else:
            # Tkinter 模式
            self.root.geometry(f"{self._size}x{self._size}+{left}+{top}")
            if self._glass:
                self._grab_frost()
            self._save_focus()
            self.root.deiconify()
            self.root.update_idletasks()
            self._apply_noactivate()
            if self._glass:
                self._paint_glass()
            else:
                self._draw()
            self._restore_focus()
        self._visible = True

    def _grab_frost(self) -> None:
        from PIL import Image, ImageGrab
        box = (self._left, self._top, self._left + self._size, self._top + self._size)
        try:
            shot = ImageGrab.grab(bbox=box, all_screens=True)
        except Exception:
            try:
                shot = ImageGrab.grab(bbox=box)
            except Exception:
                shot = Image.new("RGB", (self._size, self._size), (28, 30, 46))
        self._frost = make_frost(shot, tint=self._glass_tint)

    def _paint_glass(self) -> None:
        if self._frost is None:
            return
        try:
            from desktop import glass_window
            img = compose_menu_glass(self._frost, self._inner, self._outer, self._highlight)
            glass_window.show_layered_image(self.root.winfo_id(), img, self._left, self._top)
        except Exception:
            pass

    def highlight(self, seg: int | None) -> None:
        if seg != self._highlight:
            self._highlight = seg
            if self._visible:
                if self._glass and self._glass_hwnd:
                    # 原生窗模式：重新合成并显示
                    try:
                        from desktop import glass_window
                        img = compose_menu_glass(self._frost, self._inner, self._outer, seg)
                        glass_window.show_layered_image(self._glass_hwnd, img, self._left, self._top)
                    except Exception:
                        pass
                else:
                    self._paint_glass() if self._glass else self._draw()

    def hit_test(self, x: int, y: int) -> int | None:
        return self.geom.hit_test(x, y)

    def zone(self, x: int, y: int):
        return self.geom.zone(x, y)

    def hide(self) -> None:
        self._visible = False
        if self._glass and self._glass_hwnd:
            # 原生窗模式
            try:
                from desktop import glass_window
                glass_window.hide_glass_window(self._glass_hwnd)
            except Exception:
                pass
        else:
            try:
                self.root.withdraw()
            except Exception:
                pass

    def close(self) -> None:
        if self._glass and self._glass_hwnd:
            try:
                from desktop import glass_window
                glass_window.destroy_glass_window()
            except Exception:
                pass
        else:
            try:
                self.root.destroy()
            except Exception:
                pass

    # ---------------- 渲染(PIL 抗锯齿) ----------------
    def _draw(self) -> None:
        from PIL import ImageTk
        flat = render_menu_image(self._size, self._inner, self._outer, self._highlight, self.theme)
        self._photo = ImageTk.PhotoImage(flat)
        if self._img_item is None:
            self._img_item = self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        else:
            self._canvas.itemconfig(self._img_item, image=self._photo)

    # ---------------- 焦点处理 ----------------
    def _save_focus(self) -> None:
        try:
            import ctypes
            self._saved_hwnd = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            self._saved_hwnd = None

    def _restore_focus(self) -> None:
        try:
            import ctypes
            if self._saved_hwnd:
                ctypes.windll.user32.SetForegroundWindow(self._saved_hwnd)
        except Exception:
            pass

    def _apply_noactivate(self) -> None:
        try:
            import ctypes
            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
            user32 = ctypes.windll.user32
            hwnd = self.root.winfo_id()
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass


class StatusHud:
    """录音/处理状态浮窗(贴光标，不抢焦点)。PIL 抗锯齿渲染。

    show_listen() 显示随真实音量起伏的声波；show_process(est) 显示 0→100% 进度条；
    feed_level(v) 录音中喂入瞬时音量；finish() 处理完成跳满收起；tick() 每帧推进(main 的 tk 泵 ~25ms 调)。
    """

    _SS = 3   # HUD 每帧重绘 → 超采样小一点省开销

    def __init__(self, root, theme: dict, glass: bool = False, glass_tint=(22, 24, 42, 78)) -> None:
        import tkinter as tk
        self._t = theme
        self._key = theme["key"]
        self._W, self._H = 178, 62
        self._glass = bool(glass) and sys.platform == "win32"
        self._glass_tint = tuple(glass_tint)
        self._frost_card = None
        self._x = self._y = 0
        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        if self._glass:                          # 玻璃：层窗(无 canvas)，先置 LAYERED 防黑闪
            self._win.geometry(f"{self._W}x{self._H}+0+0")
            self._win.update_idletasks()
            try:
                from desktop import glass_window
                glass_window.set_layered(self._win.winfo_id())
            except Exception:
                self._glass = False
        if not self._glass:
            try:
                self._win.attributes("-transparentcolor", self._key)
            except Exception:
                pass
            try:
                self._win.attributes("-alpha", 0.97)
            except Exception:
                pass
            self._win.configure(bg=self._key)
            self._c = tk.Canvas(self._win, width=self._W, height=self._H,
                                bg=self._key, highlightthickness=0, bd=0)
            self._c.pack()
        self._win.withdraw()
        self._visible = False
        self._mode = "listen"             # listen(声波) | process(进度条)
        self._frame = 0
        self._levels = collections.deque(maxlen=20)   # 最近若干帧音量(0..1)，画滚动声波
        self._progress = 0.0
        self._estimate_frames = 52        # 处理进度估计(帧)，由 show_process 按实测时长设定
        self._proc_frame0 = 0
        self._done = False
        self._done_frame = 0
        self._photo = None
        self._img_item = None

    def _position_and_show(self) -> None:
        cx, cy = cursor_xy()
        x, y = cx + 18, cy + 22
        try:                                   # 先夹到屏内(deiconify 前定位 → 玻璃才能干净截背景)
            sw, sh = self._win.winfo_screenwidth(), self._win.winfo_screenheight()
            x = max(4, min(x, sw - self._W - 4))
            y = max(4, min(y, sh - self._H - 4))
        except Exception:
            pass
        self._x, self._y = x, y
        self._win.geometry(f"{self._W}x{self._H}+{x}+{y}")
        if self._glass:
            self._grab_frost()                 # 窗口仍 withdraw → 干净截背后桌面做磨砂卡片
        saved = self._foreground()
        self._win.deiconify()
        self._win.update_idletasks()
        self._apply_noactivate()
        self._set_foreground(saved)
        self._visible = True

    def show_listen(self) -> None:
        self._mode = "listen"
        self._frame = 0
        self._levels.clear()
        self._done = False
        self._position_and_show()
        self._draw()

    def show_process(self, estimate_s: float = 1.3) -> None:
        self._mode = "process"
        self._frame = 0
        self._proc_frame0 = 0
        self._estimate_frames = max(8, int(float(estimate_s) / 0.025))
        self._progress = 0.0
        self._done = False
        self._position_and_show()
        self._draw()

    def feed_level(self, v: float) -> None:
        # 录音中由 main 每帧喂入瞬时音量(0..1)，听写声波随之起伏。
        if self._visible and self._mode == "listen":
            self._levels.append(max(0.0, min(1.0, float(v))))

    def finish(self) -> None:
        # 处理真正完成：进度瞬跳 100% 再短暂停留后收起。
        if self._visible and self._mode == "process":
            self._done = True
            self._done_frame = self._frame
        else:
            self.hide()

    def tick(self) -> None:
        if not self._visible:
            return
        self._frame += 1
        if self._mode == "process":
            if self._done:
                if self._frame - self._done_frame > 16:    # 完成填满后约 0.4s 收起
                    self.hide()
                    return
            else:                                          # 按 elapsed/估计 填充进度，封顶 97%，真完成跳满
                self._progress = min(0.97, (self._frame - self._proc_frame0) / max(1, self._estimate_frames))
        self._draw()

    def hide(self) -> None:
        if not self._visible:
            return
        self._visible = False
        try:
            self._win.withdraw()
        except Exception:
            pass

    def _draw(self) -> None:
        if self._glass:
            self._draw_glass()
            return
        from PIL import ImageTk
        flat = render_hud_image(self._W, self._H, self._mode, self._frame, self._t,
                                levels=list(self._levels), progress=self._progress,
                                done=self._done, ss=self._SS)
        self._photo = ImageTk.PhotoImage(flat)
        if self._img_item is None:
            self._img_item = self._c.create_image(0, 0, anchor="nw", image=self._photo)
        else:
            self._c.itemconfig(self._img_item, image=self._photo)

    def _grab_frost(self) -> None:
        from PIL import Image, ImageGrab
        box = (self._x, self._y, self._x + self._W, self._y + self._H)
        try:
            shot = ImageGrab.grab(bbox=box, all_screens=True)
        except Exception:
            try:
                shot = ImageGrab.grab(bbox=box)
            except Exception:
                shot = Image.new("RGB", (self._W, self._H), (28, 30, 46))
        frost = make_frost(shot, tint=self._glass_tint)
        frost.putalpha(_frost_card_mask(self._W, self._H))     # 裁成圆角卡片(卡外透明)
        self._frost_card = frost

    def _draw_glass(self) -> None:
        if self._frost_card is None:
            return
        try:
            from PIL import Image
            from desktop import glass_window
            content = render_hud_glass_content(self._W, self._H, self._mode, self._frame,
                                               levels=list(self._levels), progress=self._progress,
                                               done=self._done, ss=self._SS)
            img = Image.alpha_composite(self._frost_card, content)
            glass_window.show_layered_image(self._win.winfo_id(), img, self._x, self._y)
        except Exception:
            pass

    def _foreground(self):
        try:
            import ctypes
            return ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None

    def _set_foreground(self, h) -> None:
        try:
            import ctypes
            if h:
                ctypes.windll.user32.SetForegroundWindow(h)
        except Exception:
            pass

    def _apply_noactivate(self) -> None:
        try:
            import ctypes
            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
            user32 = ctypes.windll.user32
            hwnd = self._win.winfo_id()
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass
