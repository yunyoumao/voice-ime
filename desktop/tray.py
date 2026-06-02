"""系统托盘图标（pystray）。

pystray 的 icon.run() 是阻塞的 → 在 asyncio.to_thread 后台线程跑；菜单回调在
pystray 线程，经 loop.call_soon_threadsafe 把动作转回主事件循环。
菜单：打开设置 / 退出。
"""
from __future__ import annotations

import asyncio
import os


class TrayIcon:
    def __init__(self, loop: asyncio.AbstractEventLoop, on_open_settings, on_quit) -> None:
        self._loop = loop
        self._open = on_open_settings        # 无参回调(在主线程执行)
        self._quit = on_quit
        self._icon = None

    @staticmethod
    def _image():
        from PIL import Image
        from desktop import config
        
        # Try load logo from assets/icon.ico or fall back to drawing microphone
        icon_path = os.path.join(config.ROOT, "assets", "icon.ico")
        if os.path.exists(icon_path):
            try:
                img = Image.open(icon_path).convert("RGBA")
                # Resize to 64x64 for tray
                if img.size != (64, 64):
                    img = img.resize((64, 64), Image.Resampling.LANCZOS)
                return img
            except Exception:
                pass
        
        # Fallback: draw microphone
        from PIL import ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c = (166, 179, 248, 255)             # periwinkle
        d.rounded_rectangle([25, 10, 39, 40], radius=7, fill=c)
        d.arc([20, 30, 44, 50], start=0, end=180, fill=c, width=3)
        d.line([32, 50, 32, 56], fill=c, width=3)
        d.line([25, 56, 39, 56], fill=c, width=3)
        return img

    def _do_open(self, icon=None, item=None):
        self._loop.call_soon_threadsafe(self._open)

    def _do_quit(self, icon=None, item=None):
        try:
            if self._icon:
                self._icon.stop()
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._quit)

    def run(self) -> None:
        """阻塞运行托盘(放 asyncio.to_thread 里调用)。"""
        import pystray
        self._icon = pystray.Icon(
            "voice_input", self._image(), "语音输入法",
            menu=pystray.Menu(
                pystray.MenuItem("打开设置", self._do_open, default=True),
                pystray.MenuItem("退出", self._do_quit),
            ),
        )
        self._icon.run()

    def stop(self) -> None:
        try:
            if self._icon:
                self._icon.stop()
        except Exception:
            pass
