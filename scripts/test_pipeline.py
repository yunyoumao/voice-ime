"""验证处理层管线：前缀词路由 + 润色（真实调 GLM），不依赖麦克风。

运行： .venv/bin/python scripts/test_pipeline.py
"""
from __future__ import annotations

import asyncio
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from desktop.config import load_config  # noqa: E402
from pipeline import build_pipeline  # noqa: E402


async def main() -> None:
    cfg = load_config()
    pcfg = cfg.get("pipeline", {})
    print(f"默认模式={pcfg.get('default_mode')}  前缀路由={pcfg.get('prefix_routing')}  "
          f"LLM={pcfg.get('llm', {}).get('provider')}\n")

    pipe = build_pipeline(cfg)
    tests = [
        "呃那个我想说就是今天天气挺好的然后我们要不要出去走走啊",   # 无前缀 → 默认 polish
        "原文 这句话保持原样不要润色直接上屏",                       # → raw
        "润色 嗯这个方案我觉得吧大概还行就先这样",                   # → polish
    ]
    for t in tests:
        r = await pipe.run(t)
        print(f"输入: {t}")
        print(f"  [{r.mode} → {r.sink}] {r.text}\n")


if __name__ == "__main__":
    asyncio.run(main())
