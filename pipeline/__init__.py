"""处理层装配：按配置构建 Pipeline。"""
from __future__ import annotations

from .base import Pipeline, Processor, Result
from .llm import LLMClient
from .passthrough import PassthroughProcessor
from .polish import PolishProcessor
from .router import Router
from .summarize import SummarizeProcessor
from .translate import TranslateProcessor


def build_pipeline(cfg: dict) -> Pipeline:
    pcfg = cfg.get("pipeline") or {}
    default_mode = pcfg.get("default_mode", "polish")
    routing = bool(pcfg.get("prefix_routing", True))

    llm = LLMClient(cfg)                                          # 默认通道(润色用)
    tp = (pcfg.get("llm") or {}).get("translate_provider")       # 翻译/总结专用通道(留空=同默认)
    llm_t = LLMClient(cfg, provider_override=tp) if tp else llm   # 翻译/总结可走 GLM(日语长文更稳)
    processors = {
        "raw": PassthroughProcessor(),
        "polish": PolishProcessor(llm, cfg),                     # 润色→默认通道(可本地，快/离线)
        "translate_zh": TranslateProcessor(llm_t, "translate_zh", "中文"),
        "translate_ja": TranslateProcessor(llm_t, "translate_ja", "日语"),
        "translate_en": TranslateProcessor(llm_t, "translate_en", "英语"),
        "summary": SummarizeProcessor(llm_t),
    }

    sinks_map = cfg.get("sinks") or {}
    mode_to_sink = {mode: sinks_map.get(mode, "type") for mode in processors}

    router = Router(routing, default_mode)
    return Pipeline(router, processors, mode_to_sink, default_mode)


__all__ = ["build_pipeline", "Pipeline", "Processor", "Result"]
