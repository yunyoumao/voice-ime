"""前缀词 → 模式路由。

说话开头带触发词就切到对应模式（并去掉触发词本身），否则走默认模式。
起步只启用 raw / polish；summary/translate/command 在各自 Processor 落地后再加规则。
"""
from __future__ import annotations

DEFAULT_RULES = [
    (["原文", "直接说", "不润色", "不要润色"], "raw"),
    (["润色", "整理一下", "帮我整理", "整理成"], "polish"),
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
