"""第 0 步验证 v9：图标/译徽字大小可调(默认放大)。

锯齿/圆/缝都已定(中心圆半径 50、popover、Retina 2x)。这版只调图标(含 ZH/JA/EN 字)大小：
    .venv/bin/python scripts/probe_glass.py        # 默认图标半径 26 (原来 17，明显放大)
    .venv/bin/python scripts/probe_glass.py 24      # 小一点
    .venv/bin/python scripts/probe_glass.py 30      # 更大

窗口常驻、高亮循环，Ctrl+C 关。字号合适就告诉我那个数，第 0 步就收工。
"""
from __future__ import annotations

import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from AppKit import (
    NSApplication, NSPanel, NSView, NSColor, NSImage, NSImageView, NSScreen,
    NSVisualEffectView, NSVisualEffectBlendingModeBehindWindow, NSVisualEffectStateActive,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSStatusWindowLevel, NSBackingStoreBuffered, NSApplicationActivationPolicyAccessory,
    NSImageScaleAxesIndependently, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary, NSWindowCollectionBehaviorIgnoresCycle,
)
from Foundation import NSData, NSDate, NSMakeRect, NSMakeSize, NSDefaultRunLoopMode, NSRunLoop
from Quartz import CALayer, CGImageSourceCreateWithData, CGImageSourceCreateImageAtIndex
from PIL import Image, ImageChops

try:
    from AppKit import NSEventMaskAny
except Exception:
    NSEventMaskAny = (1 << 64) - 1

from desktop.radial_menu import _glass_layers, _wedge_shape, _disc_mask, cursor_xy

SIZE, INNER, OUTER = 368, 55, 160
POPOVER = 6
HUB_R = 50                                                          # 中心磨砂圆半径(已定)
ICON_R = int(sys.argv[1]) if (len(sys.argv) > 1 and sys.argv[1].isdigit()) else 26
HUB_ICON_R = int(ICON_R * 1.25)                                     # 中心图标比花瓣图标略大


def pil_to_cgimage(im):
    if im.mode == "L":
        im = Image.merge("RGBA", (im, im, im, im))
    elif im.mode != "RGBA":
        im = im.convert("RGBA")
    b = io.BytesIO()
    im.save(b, "PNG")
    raw = b.getvalue()
    data = NSData.dataWithBytes_length_(raw, len(raw))
    src = CGImageSourceCreateWithData(data, None)
    return CGImageSourceCreateImageAtIndex(src, 0, None)


def pil_to_nsimage(im, pt_size):
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    b = io.BytesIO()
    im.save(b, "PNG")
    raw = b.getvalue()
    img = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(raw, len(raw)))
    img.setSize_(NSMakeSize(pt_size, pt_size))
    return img


def main() -> None:
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    mx, my = cursor_xy()
    left, top = mx - SIZE // 2, my - SIZE // 2
    screen0 = NSScreen.screens()[0]
    main_h = screen0.frame().size.height
    scale = int(screen0.backingScaleFactor() or 2)
    cocoa_y = main_h - top - SIZE
    S = max(1, scale)

    style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(left, cocoa_y, SIZE, SIZE), style, NSBackingStoreBuffered, False)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(NSColor.clearColor())
    panel.setLevel_(NSStatusWindowLevel)
    panel.setHidesOnDeactivate_(False)
    panel.setIgnoresMouseEvents_(True)
    panel.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorIgnoresCycle)

    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, SIZE, SIZE))
    container.setWantsLayer_(True)

    glass_wrap = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, SIZE, SIZE))
    glass_wrap.setWantsLayer_(True)
    effect = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, SIZE, SIZE))
    effect.setMaterial_(POPOVER)
    effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
    effect.setState_(NSVisualEffectStateActive)
    glass_wrap.addSubview_(effect)

    fill, _edge = _wedge_shape(SIZE * S, [0, 1, 2, 3, 4, 5], INNER * S, OUTER * S)
    hub = _disc_mask(SIZE * S, HUB_R * S)
    mask_pil = ImageChops.lighter(fill, hub)
    mask_layer = CALayer.alloc().init()
    mask_layer.setContents_(pil_to_cgimage(mask_pil))
    mask_layer.setFrame_(NSMakeRect(0, 0, SIZE, SIZE))
    mask_layer.setContentsScale_(scale)
    glass_wrap.layer().setMask_(mask_layer)
    container.addSubview_(glass_wrap)

    image_view = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, SIZE, SIZE))
    image_view.setImageScaling_(NSImageScaleAxesIndependently)
    container.addSubview_(image_view)
    panel.setContentView_(container)

    def render(hl):
        _, overlay = _glass_layers(SIZE, INNER, OUTER, hl, icon_r=ICON_R, hub_icon_r=HUB_ICON_R)
        overlay = overlay.resize((SIZE * S, SIZE * S), Image.LANCZOS)
        image_view.setImage_(pil_to_nsimage(overlay, SIZE))

    render(None)
    panel.orderFrontRegardless()

    def pump():
        while True:
            ev = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                NSEventMaskAny, NSDate.distantPast(), NSDefaultRunLoopMode, True)
            if ev is None:
                break
            app.sendEvent_(ev)
        NSRunLoop.currentRunLoop().runMode_beforeDate_(
            NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.0))

    print(f"材质=popover  中心圆半径={HUB_R}  图标半径={ICON_R}(原17)  中心图标={HUB_ICON_R}")
    print(f"isKeyWindow={panel.isKeyWindow()} 窗口数={len(app.windows())}")
    print("--- 窗口常驻、高亮循环；Ctrl+C 关。看 ZH/JA/EN 字号合适吗 ---")

    seq = [None, 0, 1, 2, 3, 4, 5]
    i = 0
    last = time.time()
    try:
        while True:
            if time.time() - last > 1.2:
                i += 1
                render(seq[i % len(seq)])
                last = time.time()
            pump()
            time.sleep(1 / 60)
    except KeyboardInterrupt:
        pass
    panel.orderOut_(None)
    print(f"\n已关闭。当前图标半径={ICON_R}。合适就告诉我；调整试 probe_glass.py 24 / 30")


if __name__ == "__main__":
    main()
