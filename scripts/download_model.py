"""下载本地引擎模型（跨平台，Mac / Windows / Linux 通用）。

SenseVoice（中英日韩粤）+ Silero VAD + 中英标点模型，约 510MB。不依赖 curl/tar/bash。
用法： python scripts/download_model.py           # 下到项目根 models/
可编程调用： main(models_dir, progress=cb)        # 指定目录 + 进度回调(GUI 用)
"""
from __future__ import annotations

import os
import sys
import tarfile
import urllib.request

# 中文 Windows 控制台默认 GBK，print 带 ✓/… 在管道/重定向下会 UnicodeEncodeError；强制 stdout UTF-8。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
SV = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
PUNCT_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models"
PUNCT = "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12"   # 中英标点(CT-Transformer)，约 279MB
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")


def _download(url: str, dest: str, progress=None, label: str = "") -> None:
    if progress is None:
        print(f"==> 下载 {os.path.basename(dest)} …")

    def hook(block: int, block_size: int, total: int) -> None:
        if total > 0:
            pct = min(100, block * block_size * 100 // total)
            if progress:
                progress(label, pct)
            else:
                sys.stdout.write(f"\r    {pct}%   ")
                sys.stdout.flush()

    urllib.request.urlretrieve(url, dest, hook)
    if progress:
        progress(label, 100)
    else:
        sys.stdout.write("\r    100%  \n")
        sys.stdout.flush()


def main(models_dir: str | None = None, progress=None) -> None:
    """下载模型到 models_dir（默认项目根 models/）。progress(label, pct) 可选，供 GUI 进度。"""
    models = models_dir or MODELS
    os.makedirs(models, exist_ok=True)

    sv_dir = os.path.join(models, SV)
    if not os.path.isdir(sv_dir):
        tar_path = os.path.join(models, SV + ".tar.bz2")
        _download(f"{BASE}/{SV}.tar.bz2", tar_path, progress, "下载识别模型")
        if progress:
            progress("解压识别模型…", 100)
        else:
            print("==> 解压 …")
        with tarfile.open(tar_path, "r:bz2") as t:
            try:
                t.extractall(models, filter="data")   # Python 3.12+
            except TypeError:
                t.extractall(models)
        os.remove(tar_path)
        if not progress:
            print("✓ SenseVoice 解压完成")
    elif not progress:
        print("✓ SenseVoice 已存在，跳过")

    vad = os.path.join(models, "silero_vad.onnx")
    if not os.path.isfile(vad):
        _download(f"{BASE}/silero_vad.onnx", vad, progress, "下载 VAD 模型")
    elif not progress:
        print("✓ Silero VAD 已存在，跳过")

    punct_dir = os.path.join(models, PUNCT)        # 本地标点模型（识别即时补标点）
    if not os.path.isdir(punct_dir):
        tar_path = os.path.join(models, PUNCT + ".tar.bz2")
        _download(f"{PUNCT_BASE}/{PUNCT}.tar.bz2", tar_path, progress, "下载标点模型")
        if progress:
            progress("解压标点模型…", 100)
        else:
            print("==> 解压标点模型 …")
        with tarfile.open(tar_path, "r:bz2") as t:
            try:
                t.extractall(models, filter="data")   # Python 3.12+
            except TypeError:
                t.extractall(models)
        os.remove(tar_path)
        if not progress:
            print("✓ 标点模型解压完成")
    elif not progress:
        print("✓ 标点模型已存在，跳过")

    if progress:
        progress("完成", 100)
    else:
        print(f"\n✓ 模型就绪：{models}")


if __name__ == "__main__":
    main()
