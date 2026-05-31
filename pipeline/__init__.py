"""处理层装配：按配置构建 Pipeline。"""
from __future__ import annotations

from .base import Pipeline, Processor, Result
from .llm import LLMClient
from .passthrough import PassthroughProcessor
from .polish import PolishProcessor
from .router import Router


def build_pipeline(cfg: dict) -> Pipeline:
    pcfg = cfg.get("pipeline") or {}
    default_mode = pcfg.get("default_mode", "polish")
    routing = bool(pcfg.get("prefix_routing", True))

    llm = LLMClient(cfg)
    processors = {
        "raw": PassthroughProcessor(),
        "polish": PolishProcessor(llm),
    }

    sinks_map = cfg.get("sinks") or {}
    mode_to_sink = {mode: sinks_map.get(mode, "type") for mode in processors}

    router = Router(routing, default_mode)
    return Pipeline(router, processors, mode_to_sink, default_mode)


__all__ = ["build_pipeline", "Pipeline", "Processor", "Result"]
