"""键名探测：按一下你想当热键的键，照抄打印的填法写进 config.yaml 的 hotkey。

运行： .venv/bin/python scripts/probe_key.py     （按 Esc 退出）

- 单键：直接抄 hotkey: "<alt_r>" 这样
- 组合键：把两个填法用 + 连起来，如 hotkey: "<ctrl>+<space>"
- 如果你按键完全没有任何打印 → 是 macOS「输入监控/辅助功能」权限没给，
  去「系统设置 → 隐私与安全性」授权运行本脚本的终端，再重开终端重试。
"""
from pynput import keyboard


def fmt(key) -> str:
    """给出能直接填进 config 的写法。标准修饰键用名字(左右键准确)；
    日语/特殊键等无标准名的键回退到 vk 数字 <NNN>(pynput 的 HotKey.parse 支持)。"""
    if isinstance(key, keyboard.Key):
        return f"<{key.name}>"
    if getattr(key, "char", None):
        return key.char
    vk = getattr(key, "vk", None)
    if vk is not None:
        return f"<{vk}>"
    return repr(key)


def on_press(key) -> bool | None:
    if key == keyboard.Key.esc:
        print("\n再见。把上面的填法写进 config.yaml 的 hotkey 或 mouse_menu.hotkey，重启生效。")
        return False
    vk = getattr(key, "vk", None)
    if vk is None and isinstance(key, keyboard.Key):
        vk = getattr(key.value, "vk", None)
    info = f"vk={vk}" if vk is not None else "无vk(抓不到/权限未给)"
    print(f'  按下 {key!r:24} [{info}]  →  config 里填  "{fmt(key)}"')
    return None


def main() -> None:
    print("按下你想用作热键的键（修饰键如右 Option/右 Cmd 最适合）。按 Esc 退出。\n")
    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


if __name__ == "__main__":
    main()
