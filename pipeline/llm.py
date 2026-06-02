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
import time
import urllib.error
import urllib.request


class LLMClient:
    def __init__(self, cfg: dict) -> None:
        llm = (cfg.get("pipeline") or {}).get("llm") or {}
        self.provider = llm.get("provider", "glm-cli")
        self.timeout = int(llm.get("timeout", 30))
        # 并发闸：智谱按 key 限并发，多请求齐发会 429→退避重试→卡 5-8s 甚至失败。
        # 默认串行(1)从源头避免；连说多句排队处理(每句~1.2s)。配额高可在 config 调大。
        self.max_concurrency = max(1, int(llm.get("max_concurrency", 1)))
        self._sem: asyncio.Semaphore | None = None   # 懒建(绑到运行中的事件循环)

        gc = llm.get("glm_cli") or {}
        self.glm_python = os.path.expanduser(gc.get("python", "python3"))
        self.glm_script = os.path.expanduser(gc.get("script", "~/.claude/skills/glm-provider/ask_glm.py"))
        self.glm_model = gc.get("model", "glm-4.7")
        # glm-http 的 key 与模型：key 优先 config(pipeline.llm.api_key)、回退环境变量；
        # 模型优先 pipeline.llm.model、回退 glm_cli.model（兼容旧配置）。无环境变量的机器也能用。
        self.glm_http_key = (llm.get("api_key") or "").strip()
        self.model = llm.get("model") or self.glm_model

        oc = llm.get("openai") or {}
        self.base_url = oc.get("base_url", "https://open.bigmodel.cn/api/paas/v4")
        self.openai_model = oc.get("model", "glm-4.5-air")
        self.api_key = oc.get("api_key") or os.environ.get(oc.get("api_key_env", "ZHIPU_API_KEY"), "")

        oll = llm.get("ollama") or {}                # 本地 Ollama（GPU 推理：快、稳、离线、无网络抖动）
        self.ollama_url = oll.get("base_url", "http://localhost:11434").rstrip("/") + "/api/chat"
        self.ollama_model = oll.get("model", "qwen2.5:7b")
        self.ollama_keep_alive = oll.get("keep_alive", "30m")   # 模型常驻显存时长，避免每次冷加载

    async def chat(self, system: str, user: str) -> str:
        if self._sem is None:                        # 首次调用时在运行中的循环里建信号量
            self._sem = asyncio.Semaphore(self.max_concurrency)
        async with self._sem:                        # 串行(默认)：避免并发触发智谱 429
            return await asyncio.to_thread(self._chat_sync, system, user)

    def _chat_sync(self, system: str, user: str) -> str:
        if self.provider == "openai":
            return self._openai(system, user)
        if self.provider == "ollama":
            return self._ollama_http(system, user)
        if self.provider in ("glm-http", "glm", "glm-direct"):
            return self._glm_http(system, user)
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

    def _glm_http(self, system: str, user: str) -> str:
        # 直连智谱 anthropic 端点：无子进程（省 ~0.5s/次）、不依赖系统 Python 路径。
        # key 取环境变量 ZHIPU_API_KEY / ANTHROPIC_AUTH_TOKEN（与 ask_glm.py 同源）。
        key = (self.glm_http_key or os.environ.get("ZHIPU_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
        if not key:
            raise RuntimeError("未找到 GLM key（环境变量 ZHIPU_API_KEY 或 ANTHROPIC_AUTH_TOKEN）")
        body = {"model": self.model, "max_tokens": 1024,
                "messages": [{"role": "user", "content": user}]}
        if system:
            body["system"] = system
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "x-api-key": key,
                   "anthropic-version": "2023-06-01"}
        url = "https://open.bigmodel.cn/api/anthropic/v1/messages"
        last = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    d = json.loads(resp.read())
                return "\n".join(c.get("text", "") for c in d.get("content", [])
                                 if c.get("type") == "text").strip()
            except urllib.error.HTTPError as e:
                last = e
                if e.code != 429 and not (500 <= e.code < 600):
                    raise
                time.sleep(1.0 * (attempt + 1))   # 429/5xx 退避重试
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
                time.sleep(0.5 * (attempt + 1))
        raise last if last else RuntimeError("glm-http 调用失败")

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
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("openai 响应无 choices")
        return ((choices[0].get("message") or {}).get("content") or "").strip()

    def _ollama_http(self, system: str, user: str) -> str:
        # 本地 Ollama /api/chat：GPU 推理，快且稳(无网络抖动)；think=False 关掉思考链以提速。
        body = json.dumps({
            "model": self.ollama_model, "stream": False, "think": False,
            "keep_alive": self.ollama_keep_alive,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0.2, "num_predict": 1024},
        }).encode("utf-8")
        req = urllib.request.Request(self.ollama_url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=max(60, self.timeout)) as resp:   # 本地冷加载可能~10s，超时给宽
            d = json.loads(resp.read())
        return (d.get("message", {}).get("content") or "").strip()
