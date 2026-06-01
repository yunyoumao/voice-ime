"""前缀词 → 模式路由。

说话开头带触发词就切到对应模式（并去掉触发词本身），否则走默认模式。
已启用 raw / polish / translate_zh|ja|en / summary；command 待落地后再加规则。
"""
from __future__ import annotations

DEFAULT_RULES = [
    (["原文", "直接说", "不润色", "不要润色"], "raw"),
    (["润色", "整理一下", "帮我整理", "整理成"], "polish"),
    (["译中", "翻译成中文", "翻成中文", "译成中文"], "translate_zh"),
    (["译日", "翻译成日", "翻成日", "译成日"], "translate_ja"),
    (["译英", "翻译成英", "翻成英", "译成英"], "translate_en"),
    (["总结", "概括", "归纳", "小结一下", "小结"], "summary"),
]


class Router:
    def __init__(self, enabled: bool, default_mode: str, rules=None) -> None:
        self._enabled = enabled
        self._default = default_mode
        self._rules = rules if rules is not None else DEFAULT_RULES

    def route(self, raw_text: str):
        text = (raw_text or "").lstrip()
        if self._enabled and text:
            for prefixes, mode in self._rules:
                for p in prefixes:
                    if text.startswith(p):
                        stripped = text[len(p):].lstrip("，,：:。.、 \t")
                        return mode, (stripped or text)
        return self._default, raw_text
