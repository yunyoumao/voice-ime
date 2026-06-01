"""键名探测：按一下你想当热键的键，照抄打印的填法写进 config.yaml 的 hotkey。

运行： .venv/bin/python scripts/probe_key.py     （按 Esc 退出）

- 单键：直接抄 hotkey: "<alt_r>" 这样
- 组合键：把两个填法用 + 连起来，如 hotkey: "<ctrl>+<space>"
- 如果你按键完全没有任何打印 → 是 macOS「输入监控/辅助功能」权限没给，
  去「系统设置 → 隐私与安全性」授权运行本脚本的终端，再重开终端重试。
"""
from pynput import keyboard


def fmt(key) -> str:
    if isinstance(key, keyboard.Key):
        return f"<{key.name}>"
    if getattr(key, "char", None):
        return key.char
    return repr(key)


def on_press(key) -> bool | None:
    if key == keyboard.Key.esc:
        print("\n再见。把上面的填法写进 config.yaml 的 hotkey，重启 main.py 生效。")
        return False
    print(f'  按下 {key!r:18} →  config 里填  hotkey: "{fmt(key)}"')
    return None


def main() -> None:
    print("按下你想用作热键的键（修饰键如右 Option/右 Cmd 最适合）。按 Esc 退出。\n")
    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


if __name__ == "__main__":
    main()
