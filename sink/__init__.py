"""输出层装配：按配置构建各 Sink。起步只有 type（上屏）。"""
from __future__ import annotations

from .base import Sink
from .type_sink import TypeSink


def build_sinks(cfg: dict, output_controller) -> dict:
    return {
        "type": TypeSink(output_controller),
    }


__all__ = ["build_sinks", "Sink"]
