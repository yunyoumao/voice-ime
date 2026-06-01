"""下载本地引擎模型（跨平台，Mac / Windows / Linux 通用）。

SenseVoice（中英日韩粤）+ Silero VAD，约 230MB。不依赖 curl/tar/bash。
用法： python scripts/download_model.py
"""
from __future__ import annotations

import os
import sys
import tarfile
import urllib.request

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
SV = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")


def _download(url: str, dest: str) -> None:
    print(f"==> 下载 {os.path.basename(dest)} …")

    def hook(block: int, block_size: int, total: int) -> None:
        if total > 0:
            pct = min(100, block * block_size * 100 // total)
            sys.stdout.write(f"\r    {pct}%   ")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, dest, hook)
    sys.stdout.write("\r    100%  \n")
    sys.stdout.flush()


def main() -> None:
    os.makedirs(MODELS, exist_ok=True)

    sv_dir = os.path.join(MODELS, SV)
    if not os.path.isdir(sv_dir):
        tar_path = os.path.join(MODELS, SV + ".tar.bz2")
        _download(f"{BASE}/{SV}.tar.bz2", tar_path)
        print("==> 解压 …")
        with tarfile.open(tar_path, "r:bz2") as t:
            try:
                t.extractall(MODELS, filter="data")   # Python 3.12+
            except TypeError:
                t.extractall(MODELS)
        os.remove(tar_path)
        print(f"✓ SenseVoice 解压完成")
    else:
        print("✓ SenseVoice 已存在，跳过")

    vad = os.path.join(MODELS, "silero_vad.onnx")
    if not os.path.isfile(vad):
        _download(f"{BASE}/silero_vad.onnx", vad)
    else:
        print("✓ Silero VAD 已存在，跳过")

    print(f"\n✓ 模型就绪：{MODELS}")


if __name__ == "__main__":
    main()
