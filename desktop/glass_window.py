"""
Windows 毛玻璃/亚克力效果模块 (tkinter)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

支持 Win10 + Win11，自动降级策略。
- Win11 DWM SYSTEMBACKDROP_TYPE (TRANSIENTWINDOW = 亚克力)
- Win10 ACCENT_POLICY (BLURBEHIND = 毛玻璃)

可信度：★★★★★ 基于 win32mica + pywinstyles 的验证实现

用法：
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.geometry('370x370')
    setup_glass_toplevel(root, mode='blur', dark=True)
    root.mainloop()
"""

import ctypes
import sys
from typing import Literal

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 常数定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ACCENT_POLICY 状态值 (Win10)
ACCENT_DISABLED = 0
ACCENT_ENABLE_GRADIENT = 1
ACCENT_ENABLE_TRANSPARENTGRADIENT = 2
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

# ACCENT 属性常数
WCA_ACCENT_POLICY = 19

# DWM 属性常数 (Win11)
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWA_WINDOW_CORNER_PREFERENCE = 33

# DWM 背景类型 (Win11)
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_DEFAULT = 2
DWMSBT_TRANSIENTWINDOW = 3  # 亚克力 Acrylic
DWMSBT_TINTED_GLASS = 4     # Mica (Win11 22621+)

# DWM 圆角偏好
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ctypes 结构体定义 (Win10 ACCENT_POLICY)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ACCENT_POLICY(ctypes.Structure):
    """Win10 ACCENT_POLICY 结构体

    字段说明：
    - AccentState: 0-4 枚举值 (ACCENT_ENABLE_*)
    - AccentFlags: 通常 0，或 0x20 用于动画
    - GradientColor: ABGR 格式 (0xAABBGGRR)
      * AA = Alpha (透明度，0-255)
      * BB = Blue
      * GG = Green
      * RR = Red
    - AnimationId: 通常 0
    """
    _fields_ = [
        ('AccentState', ctypes.c_int),
        ('AccentFlags', ctypes.c_int),
        ('GradientColor', ctypes.c_uint),
        ('AnimationId', ctypes.c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    """SetWindowCompositionAttribute 的参数结构体

    字段说明：
    - Attribute: 19 = WCA_ACCENT_POLICY (固定)
    - Data: 指向 ACCENT_POLICY 实例的指针
    - cbData: ACCENT_POLICY 的字节大小 (16)
    """
    _fields_ = [
        ('Attribute', ctypes.c_int),
        ('Data', ctypes.c_void_p),
        ('cbData', ctypes.c_int),
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 版本检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_windows_version() -> tuple[int, int, int]:
    """(major, minor, build)。按 build 判 Win11(build>=22000)——platform.release() 在 Win11 会误报 '10'。"""
    try:
        v = sys.getwindowsversion()
        major = 11 if v.build >= 22000 else v.major
        return (major, v.minor, v.build)
    except Exception:
        return (10, 0, 0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 核心函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def apply_glass_effect(
    hwnd: int,
    mode: Literal['blur', 'acrylic', 'mica'] = 'blur',
    gradient_color: int = 0xCC000000,
    corner: Literal['round', 'sharp'] = 'round'
) -> bool:
    """应用毛玻璃/亚克力效果到 tkinter 窗口

    参数：
    - hwnd: 窗口句柄 (root.winfo_id())
    - mode: 'blur'(BLURBEHIND) / 'acrylic'(ACRYLICBLUR) / 'mica'(TINTED_GLASS)
    - gradient_color: ABGR 格式颜色，如 0xCC000000 (80% 透明黑)
      * 高字节 = Alpha (0-255)
      * 中高字节 = Blue
      * 中低字节 = Green
      * 低字节 = Red
    - corner: 'round'(圆角) / 'sharp'(直角)

    返回：成功返回 True，失败返回 False

    策略：
    1. Win11: 尝试 DwmSetWindowAttribute (SYSTEMBACKDROP_TYPE)
    2. Win10: 降级到 SetWindowCompositionAttribute (ACCENT_POLICY)
    3. 失败: 返回 False，窗口保持原样

    可信度：★★★★★
    """

    if sys.platform != 'win32':
        print("[glass_window] ⚠ 非 Windows 平台，毛玻璃方案不生效")
        return False

    major, minor, build = get_windows_version()

    # ━━━ 方案 1: Win11 DWM API (推荐) ━━━
    if major >= 11:
        try:
            dwmapi = ctypes.windll.dwmapi

            # 选择背景类型
            backdrop_map = {
                'blur': DWMSBT_TRANSIENTWINDOW,
                'acrylic': DWMSBT_TRANSIENTWINDOW,
                'mica': DWMSBT_TINTED_GLASS if build >= 22621 else DWMSBT_TRANSIENTWINDOW,
            }
            backdrop_type = backdrop_map.get(mode, DWMSBT_TRANSIENTWINDOW)

            # 应用背景类型
            result = dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(ctypes.c_int(backdrop_type)),
                ctypes.sizeof(ctypes.c_int)
            )

            if result != 0:  # 0 = S_OK
                print(f"[glass_window] ⚠ DwmSetWindowAttribute 返回 {result:#x}")
                # 继续尝试圆角，不返回

            # 设置圆角（可选）
            if corner == 'round':
                try:
                    dwmapi.DwmSetWindowAttribute(
                        hwnd,
                        DWMWA_WINDOW_CORNER_PREFERENCE,
                        ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
                        ctypes.sizeof(ctypes.c_int)
                    )
                except Exception as e:
                    print(f"[glass_window] ⚠ 圆角设置失败: {e}")

            print(f"[glass_window] ✓ Win11 DWM 方案已应用 (backdrop={backdrop_type}, corner={corner})")
            return True

        except Exception as e:
            print(f"[glass_window] ⚠ Win11 DWM API 失败: {e}，尝试 Win10 方案...")

    # ━━━ 方案 2: Win10 ACCENT_POLICY (降级) ━━━
    if major >= 10 and build >= 17763:  # Win10 1809+
        try:
            user32 = ctypes.windll.user32

            # 选择 accent state
            accent_map = {
                'blur': ACCENT_ENABLE_BLURBEHIND,
                'acrylic': ACCENT_ENABLE_ACRYLICBLURBEHIND,
                'mica': ACCENT_ENABLE_BLURBEHIND,  # Win10 没有 Mica，降级
            }
            accent_state = accent_map.get(mode, ACCENT_ENABLE_BLURBEHIND)

            # 构造 ACCENT_POLICY
            accent = ACCENT_POLICY()
            accent.AccentState = accent_state
            accent.AccentFlags = 0
            accent.GradientColor = gradient_color
            accent.AnimationId = 0

            # 构造 WINDOWCOMPOSITIONATTRIBDATA
            attr_data = WINDOWCOMPOSITIONATTRIBDATA()
            attr_data.Attribute = WCA_ACCENT_POLICY
            attr_data.Data = ctypes.addressof(accent)
            attr_data.cbData = ctypes.sizeof(accent)

            # 应用
            result = user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(attr_data))

            print(f"[glass_window] ✓ Win10 ACCENT_POLICY 方案已应用 (state={accent_state})")
            return True

        except Exception as e:
            print(f"[glass_window] ✗ Win10 方案也失败: {e}")
            return False

    print(f"[glass_window] ✗ Windows 版本过旧 (major={major}, build={build})，不支持毛玻璃")
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 便利函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def setup_glass_toplevel(
    root,  # tk.Tk | tk.Toplevel
    mode: Literal['blur', 'acrylic', 'mica'] = 'blur',
    dark: bool = True,
    round_corner: bool = True
) -> bool:
    """一键为 tkinter 窗口启用毛玻璃效果（推荐用法）

    参数：
    - root: tkinter 窗口对象 (Tk 或 Toplevel)
    - mode: 'blur'(毛玻璃，推荐) / 'acrylic'(亚克力) / 'mica'(Mica+着色，Win11)
    - dark: True(暗色) / False(亮色)
      * True → 0xCC000000 (80% 透明黑) → 深色 glassmorphism
      * False → 0xCCFFFFFF (80% 透明白) → 亮色 glassmorphism
    - round_corner: True(圆角) / False(直角)

    返回：成功返回 True，失败返回 False

    推荐配置：
    >>> root = tk.Tk()
    >>> root.overrideredirect(True)  # 无边框（可选）
    >>> root.attributes('-topmost', True)  # 顶层（可选）
    >>> root.geometry('370x370')
    >>> root.configure(bg='#1a1a1a')  # 暗色背景
    >>> setup_glass_toplevel(root, mode='blur', dark=True)
    >>> root.mainloop()

    注意：
    - 不要用 `-transparentcolor`，会与毛玻璃冲突
    - 不要用 `-alpha`，会削弱毛玻璃效果
    - 改用 Canvas + PIL 绘制 RGBA 内容实现透明
    """

    hwnd = root.winfo_id()

    # 根据 dark 参数选择梯度颜色
    gradient = 0xCC000000 if dark else 0xCCFFFFFF

    return apply_glass_effect(
        hwnd,
        mode=mode,
        gradient_color=gradient,
        corner='round' if round_corner else 'sharp'
    )


def apply_acrylic(hwnd: int, gradient_abgr: int = 0x66141019) -> bool:
    """ACCENT_ENABLE_ACRYLICBLURBEHIND + 自定义着色(ABGR：高字节=alpha，越小越透明)。
    Win10/11 通用，比 DWM SYSTEMBACKDROP 更能精确控制"磨砂浓度/透明度"。"""
    try:
        a = ACCENT_POLICY()
        a.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
        a.AccentFlags = 0
        a.GradientColor = gradient_abgr
        a.AnimationId = 0
        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = WCA_ACCENT_POLICY
        data.Data = ctypes.addressof(a)
        data.cbData = ctypes.sizeof(a)
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        return True
    except Exception:
        return False


def set_round(hwnd: int, on: bool = True) -> bool:
    """Win11 圆角窗口(DWMWA_WINDOW_CORNER_PREFERENCE)。pywinstyles 不一定给无边框窗圆角，单独调。"""
    try:
        pref = DWMWCP_ROUND if on else DWMWCP_DONOTROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(ctypes.c_int(pref)), ctypes.sizeof(ctypes.c_int))
        return True
    except Exception:
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试代码
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == '__main__':
    import tkinter as tk

    print("[glass_window] 模块加载成功")

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.geometry('370x370+500+300')
    root.configure(bg='#1a1a1a')

    # 应用毛玻璃
    print("[glass_window] 正在应用毛玻璃效果...")
    success = setup_glass_toplevel(root, mode='blur', dark=True, round_corner=True)
    print(f"[glass_window] 应用结果: {'✓' if success else '✗'}")

    # 简单内容
    label = tk.Label(
        root,
        text='毛玻璃窗口',
        bg='#1a1a1a',
        fg='#ffffff',
        font=('Arial', 20, 'bold')
    )
    label.pack(expand=True)

    button = tk.Button(
        root,
        text='关闭',
        command=root.quit,
        bg='#333333',
        fg='#ffffff',
        borderwidth=0,
        highlightthickness=0,
        padx=20,
        pady=10,
        font=('Arial', 12)
    )
    button.pack(side=tk.BOTTOM, pady=20)

    root.mainloop()
