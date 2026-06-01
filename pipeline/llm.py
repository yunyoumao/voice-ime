"""统一 LLM 调用。

两种后端（config: pipeline.llm.provider）：
- glm-cli（默认，推荐）：复用你的 ~/.claude/skills/glm-provider/ask_glm.py，
  走已配置好的可用渠道。注意必须用系统 Python（非本项目 .venv）调用。
- openai：OpenAI 兼容 HTTP（直连智谱需账户有余额；也可填任意厂商 base_url）。

阻塞调用统一包在 asyncio.to_thread 里，不卡事件循环。
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import urllib.request


class LLMClient:
    def __init__(self, cfg: dict) -> None:
        llm = (cfg.get("pipeline") or {}).get("llm") or {}
        self.provider = llm.get("provider", "glm-cli")
        self.timeout = int(llm.get("timeout", 60))

        gc = llm.get("glm_cli") or {}
        self.glm_python = os.path.expanduser(gc.get("python", "python3"))
        self.glm_script = os.path.expanduser(gc.get("script", "~/.claude/skills/glm-provider/ask_glm.py"))
        self.glm_model = gc.get("model", "glm-4.7")

        oc = llm.get("openai") or {}
        self.base_url = oc.get("base_url", "https://open.bigmodel.cn/api/paas/v4")
        self.openai_model = oc.get("model", "glm-4.5-air")
        self.api_key = oc.get("api_key") or os.environ.get(oc.get("api_key_env", "ZHIPU_API_KEY"), "")

    async def chat(self, system: str, user: str) -> str:
        return await asyncio.to_thread(self._chat_sync, system, user)

    def _chat_sync(self, system: str, user: str) -> str:
        if self.provider == "openai":
            return self._openai(system, user)
        return self._glm_cli(system, user)

    def _glm_cli(self, system: str, user: str) -> str:
        proc = subprocess.run(
            [self.glm_python, self.glm_script, "--system", system,
             "--model", self.glm_model, "--json", "--timeout", str(self.timeout)],
            input=user, capture_output=True, text=True, encoding="utf-8",
            timeout=self.timeout + 30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ask_glm.py 退出码 {proc.returncode}: {proc.stderr[:200]}")
        data = json.loads(proc.stdout)
        return (data.get("text") or "").strip()

    def _openai(self, system: str, user: str) -> str:
        body = json.dumps({
            "model": self.openai_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
