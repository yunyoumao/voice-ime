"""macOS 原生环形菜单 + 状态浮窗(PyObjC)，替代 tkinter 版在 Mac 上的实现。

tkinter 在 Mac 做不出真磨砂/不抢焦点(详见 radial_menu.py 的历史)。这里用原生：
  NSPanel(Borderless+NonactivatingPanel → 不抢焦点) + NSVisualEffectView(系统实时磨砂)
  + CALayer.mask(把磨砂裁成花瓣环/圆角卡片) + NSImageView(描边/图标层)。
渲染/几何全复用 radial_menu.py。不调 NSApp.run()，靠 main.py 的 _pump_tk 每帧泵一拍 runloop
融入既有 asyncio 事件循环。

接口与 RadialMenu / StatusHud 对齐：main.py 只需按平台切换 import，其余调用不变。
视觉参数(下面常量)为第 0 步反复真机实测锁定。
"""
from __future__ import annotations

import collections
import io

from AppKit import (
    NSApplication, NSPanel, NSView, NSColor, NSImage, NSImageView, NSScreen,
    NSVisualEffectView, NSVisualEffectBlendingModeBehindWindow, NSVisualEffectStateActive,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSStatusWindowLevel, NSBackingStoreBuffered, NSApplicationActivationPolicyAccessory,
    NSImageScaleAxesIndependently, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary, NSWindowCollectionBehaviorIgnoresCycle,
)
from Foundation import (
    NSData, NSDate, NSMakeRect, NSMakePoint, NSMakeSize, NSDefaultRunLoopMode, NSRunLoop,
)
from Quartz import CALayer, CGImageSourceCreateWithData, CGImageSourceCreateImageAtIndex
from PIL import Image, ImageChops

from desktop.radial_menu import (
    MenuGeometry, theme_of, cursor_xy,
    _glass_layers, _wedge_shape, _disc_mask, _frost_card_mask, render_hud_glass_content,
)

try:
    from AppKit import NSEventMaskAny
except Exception:
    NSEventMaskAny = (1 << 64) - 1

# ---- 锁定的视觉参数(第 0 步反复实测定下) ----
_MATERIAL_POPOVER = 6      # NSVisualEffectMaterialPopover
_HUB_R = 50               # 中心磨砂圆半径(与花瓣留 ~5px 透明环)
_ICON_R = 19              # 花瓣图标半径(含译徽字)
_HUB_ICON_R = 23          # 中心图标半径

_APP = None


def _ensure_app():
    global _APP
    if _APP is None:
        _APP = NSApplication.sharedApplication()
        _APP.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # 后台 app：无 dock 图标、不抢焦点
    return _APP


def _pump_cocoa() -> None:
    """泵一拍 Cocoa runloop(不调 NSApp.run)，让透明窗完成显示/重绘。main.py 的 _pump_tk 每帧调。"""
    app = _ensure_app()
    while True:
        ev = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
            NSEventMaskAny, NSDate.distantPast(), NSDefaultRunLoopMode, True)
        if ev is None:
            break
        app.sendEvent_(ev)
    NSRunLoop.currentRunLoop().runMode_beforeDate_(
        NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.0))


def _backing_scale() -> int:
    try:
        return max(1, int(NSScreen.screens()[0].backingScaleFactor() or 2))
    except Exception:
        return 2


def _main_screen_h() -> float:
    try:
        return float(NSScreen.screens()[0].frame().size.height)
    except Exception:
        return 1080.0


def _pil_to_cgimage(im):
    if im.mode == "L":
        im = Image.merge("RGBA", (im, im, im, im))
    elif im.mode != "RGBA":
        im = im.convert("RGBA")
    b = io.BytesIO()
    im.save(b, "PNG")
    raw = b.getvalue()
    return CGImageSourceCreateImageAtIndex(
        CGImageSourceCreateWithData(NSData.dataWithBytes_length_(raw, len(raw)), None), 0, None)


def _pil_to_nsimage(im, pt_w, pt_h):
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    b = io.BytesIO()
    im.save(b, "PNG")
    raw = b.getvalue()
    img = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(raw, len(raw)))
    img.setSize_(NSMakeSize(pt_w, pt_h))   # 标逻辑点尺寸 → 高分数据 Retina 锐利
    return img


class _NativePanel:
    """无边框/非激活/透明/置顶/鼠标穿透的磨砂窗：
    底层 NSVisualEffectView(CALayer.mask 裁形) + 上层 NSImageView(描边/图标，不裁)。"""

    def __init__(self, w: int, h: int, material: int) -> None:
        _ensure_app()
        self.w, self.h = int(w), int(h)
        self._scale = _backing_scale()
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, self.w, self.h), style, NSBackingStoreBuffered, False)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setLevel_(NSStatusWindowLevel)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setIgnoresMouseEvents_(True)            # 鼠标完全穿透(位置靠 cursor_xy 轮询)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle)

        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self.w, self.h))
        container.setWantsLayer_(True)
        self._glass_wrap = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self.w, self.h))
        self._glass_wrap.setWantsLayer_(True)
        effect = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, self.w, self.h))
        effect.setMaterial_(material)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        self._glass_wrap.addSubview_(effect)
        self._mask_layer = CALayer.alloc().init()
        self._mask_layer.setFrame_(NSMakeRect(0, 0, self.w, self.h))
        self._mask_layer.setContentsScale_(self._scale)
        self._glass_wrap.layer().setMask_(self._mask_layer)   # 只裁磨砂、不碰描边层
        container.addSubview_(self._glass_wrap)
        self._image_view = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, self.w, self.h))
        self._image_view.setImageScaling_(NSImageScaleAxesIndependently)
        container.addSubview_(self._image_view)
        self.panel.setContentView_(container)

    def set_mask(self, pil) -> None:
        self._mask_layer.setContents_(_pil_to_cgimage(pil))

    def set_content(self, pil) -> None:
        self._image_view.setImage_(_pil_to_nsimage(pil, self.w, self.h))

    def place_topleft(self, left: int, top: int) -> None:
        cocoa_y = _main_screen_h() - top - self.h          # top-left(pynput) → bottom-left(Cocoa)
        self.panel.setFrameOrigin_(NSMakePoint(left, cocoa_y))

    def order_front(self) -> None:
        self.panel.orderFrontRegardless()                  # 非激活显示

    def order_out(self) -> None:
        self.panel.orderOut_(None)

    def close(self) -> None:
        try:
            self.panel.orderOut_(None)
            self.panel.close()
        except Exception:
            pass


class MacRadialMenu:
    """原生环形菜单。接口对齐 radial_menu.RadialMenu(show/highlight/hit_test/zone/hide/pump/close
    + root/theme/use_glass)。"""

    def __init__(self, cfg: dict | None = None) -> None:
        mm = (cfg or {}).get("mouse_menu", {}) or {}
        self._inner = float(mm.get("inner_radius", 55))
        self._outer = float(mm.get("outer_radius", 160))
        self._size = int(self._outer * 2 + 48)
        self.theme = theme_of(cfg)
        self._glass_tint = (22, 24, 42, int(mm.get("glass_tint_alpha", 78)))
        self.geom = MenuGeometry(0.0, 0.0, self._inner, self._outer)
        self._highlight = None
        self._visible = False
        self._scale = _backing_scale()
        self._panel = _NativePanel(self._size, self._size, _MATERIAL_POPOVER)
        self._panel.set_mask(self._build_mask())           # mask 固定：花瓣环 + 中心磨砂圆
        self._overlay_cache: dict = {}

    def _build_mask(self):
        s = self._scale
        fill, _edge = _wedge_shape(self._size * s, [0, 1, 2, 3, 4, 5],
                                   int(self._inner * s), int(self._outer * s))
        hub = _disc_mask(self._size * s, int(_HUB_R * s))
        return ImageChops.lighter(fill, hub)

    def _overlay(self, hl):
        if hl in self._overlay_cache:
            return self._overlay_cache[hl]
        s = self._scale
        _, ov = _glass_layers(self._size, self._inner, self._outer, hl,
                              icon_r=_ICON_R, hub_icon_r=_HUB_ICON_R)
        ov = ov.resize((self._size * s, self._size * s), Image.LANCZOS)
        self._overlay_cache[hl] = ov
        return ov

    def show(self, x: int, y: int) -> None:
        self.geom.center_x, self.geom.center_y = float(x), float(y)
        self._highlight = None
        self._panel.place_topleft(int(x - self._size / 2), int(y - self._size / 2))
        self._panel.set_content(self._overlay(None))
        self._panel.order_front()
        self._visible = True

    def highlight(self, seg) -> None:
        if seg != self._highlight:
            self._highlight = seg
            if self._visible:
                self._panel.set_content(self._overlay(seg))

    def hit_test(self, x: int, y: int):
        return self.geom.hit_test(x, y)

    def zone(self, x: int, y: int):
        return self.geom.zone(x, y)

    def hide(self) -> None:
        self._visible = False
        self._panel.order_out()

    def pump(self) -> None:
        _pump_cocoa()

    def close(self) -> None:
        self._panel.close()

    @property
    def root(self):
        return None            # HUD 不再依赖 tk root

    def use_glass(self) -> bool:
        return True


class MacStatusHud:
    """原生状态浮窗。接口对齐 radial_menu.StatusHud；忽略 root 参数(签名兼容)。"""

    def __init__(self, root, theme: dict, glass: bool = True, glass_tint=(22, 24, 42, 78)) -> None:
        self._t = theme
        self._W, self._H = 178, 62
        self._scale = _backing_scale()
        self._panel = _NativePanel(self._W, self._H, _MATERIAL_POPOVER)
        self._panel.set_mask(self._build_mask())           # 圆角卡片 mask 固定
        self._visible = False
        self._mode = "listen"
        self._frame = 0
        self._levels = collections.deque(maxlen=20)
        self._progress = 0.0
        self._estimate_frames = 52
        self._proc_frame0 = 0
        self._done = False
        self._done_frame = 0

    def _build_mask(self):
        s = self._scale
        return _frost_card_mask(self._W * s, self._H * s, radius=18 * s, ss=2)

    def _content(self):
        s = self._scale
        c = render_hud_glass_content(self._W, self._H, self._mode, self._frame,
                                     levels=list(self._levels), progress=self._progress,
                                     done=self._done, ss=3)
        return c.resize((self._W * s, self._H * s), Image.LANCZOS)

    def _position_and_show(self) -> None:
        s0 = NSScreen.screens()[0]
        full_h = float(s0.frame().size.height)
        vf = s0.visibleFrame()
        x = int(vf.origin.x + (vf.size.width - self._W) / 2)        # 当前屏水平居中
        cocoa_bottom = float(vf.origin.y) + 60.0                     # 工作区底部上方 60px
        top = int(full_h - (cocoa_bottom + self._H))
        self._panel.place_topleft(x, top)
        self._panel.order_front()
        self._visible = True

    def show_listen(self) -> None:
        self._mode = "listen"
        self._frame = 0
        self._levels.clear()
        self._done = False
        self._position_and_show()
        self._panel.set_content(self._content())

    def show_process(self, estimate_s: float = 1.3) -> None:
        self._mode = "process"
        self._frame = 0
        self._proc_frame0 = 0
        self._estimate_frames = max(8, int(float(estimate_s) / 0.025))
        self._progress = 0.0
        self._done = False
        self._position_and_show()
        self._panel.set_content(self._content())

    def feed_level(self, v: float) -> None:
        if self._visible and self._mode == "listen":
            self._levels.append(max(0.0, min(1.0, float(v))))

    def finish(self) -> None:
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
                if self._frame - self._done_frame > 16:
                    self.hide()
                    return
            else:
                self._progress = min(0.97, (self._frame - self._proc_frame0) / max(1, self._estimate_frames))
        self._panel.set_content(self._content())

    def hide(self) -> None:
        if not self._visible:
            return
        self._visible = False
        self._panel.order_out()

    def close(self) -> None:
        self._panel.close()
