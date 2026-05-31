# 语音输入法（中英日无缝混合 · 低延迟 · 引擎可插拔）

一个自用优先、架构可扩展的语音输入法。核心目标：**中文 / 英文 / 日语三语无缝混合、低延迟、便宜**。
桌面端（macOS / Windows）先行，安卓端随后。

## 特性

- **引擎可插拔**：同一套接口下挂 4 个识别引擎，改一行配置即可切换对比
  | 引擎 | 特点 | 成本 | 网络 |
  |---|---|---|---|
  | `local` 本地 SenseVoice | 离线、隐私最好、整段秒出 | 0 元 | 不需要 |
  | `soniox` | 逐字实时、中英日混合最强、<200ms | ~0.85 元/小时 | 需梯子 |
  | `aliyun` 阿里百炼 | 国内稳定合规、中文一流 | 按时长 | 国内直连 |
  | `volcano` 火山豆包 | 国内一流中文、13+ 语种 | ~1.8–3.5 元/小时 | 国内直连 |
- **按住说话（push-to-talk）**：按住热键说话，松开即上屏到任意输入框
- **上屏稳**：默认剪贴板粘贴，对中日文 IME 无冲突，用后自动恢复剪贴板

## 项目结构

```
asr/         引擎抽象层 + 各家适配器（base / factory / soniox / aliyun / volcano / local_sensevoice）
desktop/     桌面客户端（audio 录音 / hotkey 热键 / output 上屏 / overlay 浮窗 / tray 托盘 / main 入口）
scripts/     环境与模型安装脚本
models/      本地模型（按需下载，不入库）
config.yaml  你的私有配置（含 key，不入库）
```

## 快速开始（macOS）

```bash
# 1. 安装 Python 3.12（C 扩展兼容性最好；系统 3.14 过新可能缺 wheel）
brew install python@3.12

# 2. 建虚拟环境并装依赖
bash scripts/setup_env.sh
source .venv/bin/activate

# 3. 下载本地模型（local 引擎用，约 230MB）
bash scripts/download_sensevoice.sh

# 4. 准备配置
cp config.example.yaml config.yaml      # 默认 engine: local，开箱即用

# 5. 运行
python -m desktop.main
```

## ⚠️ macOS 必须授权（否则热键/录音/上屏会静默失败）

「系统设置 → 隐私与安全性」里，给运行本程序的终端（或打包后的 App）勾选：

1. **麦克风** —— 录音
2. **辅助功能（Accessibility）** —— 模拟键盘上屏
3. **输入监控（Input Monitoring）** —— 全局热键监听

> 首次运行系统会弹窗请求；若没弹或误点拒绝，到上述设置里手动添加。

## 各云引擎拿 key

- **Soniox**：<https://console.soniox.com> 注册取 API key → 填 `config.yaml` 的 `engines.soniox.api_key`
- **阿里百炼**：阿里云百炼控制台开通 → DashScope API Key → `engines.aliyun.api_key`
- **火山豆包**：火山引擎语音控制台开通流式 ASR → `app_id` + `access_token`

## 使用

1. 启动后按住配置的热键（默认 `Ctrl+Space`）开始说话
2. 说话时浮窗实时显示（云引擎逐字；本地引擎整段）
3. 松开热键 → 识别结果自动粘贴到当前光标处

## 路线图

- [x] 阶段 0：环境与项目骨架
- [x] 阶段 1：本地 SenseVoice 引擎（识别已用真实音频验证；录音/热键/上屏待真机联调）
- [x] 阶段 2：引擎抽象层 + 4 引擎适配（代码完成 + 静态验证；云端识别待填 key 验证）
- [ ] 阶段 3：体验层（实时浮窗 + 系统托盘）
- [ ] 阶段 4：安卓 IME 输入法
- [ ] 阶段 5（未来）：iOS 自定义键盘、打包分发、产品化
