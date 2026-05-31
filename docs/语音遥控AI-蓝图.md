# 语音遥控 AI — 完整蓝图

> 从「语音输入法」（话→字）升级为「语音遥控器」（话→AI 驱动的动作）。
> 前半段不变（按住说话→识别），革命发生在后半段：识别之后的「处理 + 输出」完全可编程。

## 一、为什么自己做（对比闪电说）

| | 闪电说 | 自己做 |
|---|---|---|
| 识别内核 | 本地 SenseVoice（锁死） | 可插拔：local/soniox/aliyun/volcano |
| 识别后处理 | 只有「润色」一种 | 任意管线：润色/总结/翻译/指令/Agent |
| 输出动作 | 只有「上屏」 | 上屏 / 写文件 / 剪贴板 / 触发动作 |
| LLM | 它支持的几家 | 复用你的 multi-LLM 调度（GLM/Gemini/Codex/Claude）|

**结论**：识别快慢闪电说能调（换快润色），但「语音→AI 工作流」它结构上做不到，只有自己做能要。

## 二、三层可编程架构

```
┌──────────────────────────────────────────────────────────┐
│  采集层：按住热键 → 录音                       【已完成】    │
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│  识别层 ASR（可插拔）                         【已完成】    │
│  local / soniox / aliyun / volcano  ──►  原始文字           │
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│  ★ 处理层 Pipeline（本蓝图核心，新增）                       │
│  原始文字 ──► [0~N 个处理器] ──► 成品文字 + 动作意图          │
│  直通 · 润色 · 总结 · 翻译 · 指令(Agent)                     │
│  LLM 复用 ~/.claude/skills/glm-provider/（GLM/Gemini/Codex）│
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│  ★ 输出层 Sink（扩展）                                       │
│  上屏(光标处) · 写 .md 文件 · 剪贴板 · 触发动作               │
└──────────────────────────────────────────────────────────┘
```

## 三、处理层：五种模式

| 模式 | 输入 | 处理 | 默认输出 | 场景 |
|---|---|---|---|---|
| **直通 raw** | 话 | 无 | 上屏 | 聊天、写代码（要原话） |
| **润色 polish** | 话 | LLM 去口水/加标点/通顺 | 上屏 | 写方案、发消息 |
| **总结 summary** | 长篇口述 | LLM 结构化摘要 | 写 .md 文件 | 会议、灵感、读书笔记 |
| **翻译 translate** | 中文 | LLM 译英/日 | 上屏 | 跨语言沟通 |
| **指令 command** | 一句指令 | LLM 当 Agent 执行 | 生成内容/触发动作 | "写成周报"、"查资料" |

## 四、模式怎么切换（交互核心）

三种方式，可组合：

1. **前缀词智能路由（推荐主用）**：说话开头带触发词，处理器自动识别意图路由
   - "总结一下，今天开会讨论了……" → summary
   - "翻译成英文，我想说……" → translate
   - "帮我写成周报，本周……" → command
   - 无前缀 → 走默认模式（如 raw 或 polish）
2. **多热键**：不同热键 = 不同模式（Cmd+Opt=直通，Cmd+Opt+S=总结，便于固定习惯）
3. **托盘切换**：托盘菜单选「当前默认模式」

> 最自然的体验：默认 polish + 前缀词路由——像对着助手说话，它自己判断你要"说"还是"做"。

## 五、LLM 接入：复用你已有的调度（零额外成本）

你的 `~/.claude/skills/glm-provider/` 已有 `dispatch.py` / `ask_glm.py` / `call_gemini_cli.py`。
处理层统一一个 `LLMProcessor`，内部按任务路由：
- 润色 / 中文 → **GLM**（最便宜快）
- 总结 / 复杂结构化 → **GLM 或 Claude**
- 超长文档 → **Gemini**（1M 上下文）
- 自主执行类指令 → **Codex / Claude**

兼容两种调用后端（config 可选）：
- `provider: glm-cli` → 直接 subprocess 调你的 glm-provider 脚本
- `provider: openai` → 走 OpenAI 兼容 `/v1/chat/completions`（填任意厂商 base_url + key）

## 六、输出层 Sink

| Sink | 行为 |
|---|---|
| `type` | 上屏到光标处（复用现有 output.py） |
| `file` | 写到 `~/VoiceNotes/2026-05-31-1530-标题.md`（时间戳+LLM生成标题） |
| `clipboard` | 只复制不上屏 |
| `action` | 触发后续动作（追加到当天笔记 / 发 Notion / 触发某 skill） |

## 七、在现有代码上怎么落地

新增两个模块，**改动极小**——只把 `desktop/main.py` 的 `on_final` 从"直接上屏"改为"过管线再分发"：

```
pipeline/
├── base.py          # Processor 抽象：process(text)->Result{text, mode, sink}
├── router.py        # 前缀词 → 模式路由
├── passthrough.py   # 直通
├── polish.py        # 润色（调 LLM）
├── summarize.py     # 总结（调 LLM）
├── translate.py     # 翻译（调 LLM）
├── command.py       # 指令/Agent（调 LLM）
└── llm.py           # 统一 LLM 调用（glm-cli / openai 两种后端）
sink/
├── base.py          # Sink 抽象：emit(result)
├── type_sink.py     # 上屏（包现有 output.py）
├── file_sink.py     # 写 .md
└── clipboard_sink.py
```

`main.py` 改造（伪代码）：
```python
def on_final(text):
    result = pipeline.run(text)     # 路由→处理器→成品+动作意图
    sink = sinks[result.sink]       # 选输出口
    sink.emit(result)               # 上屏 / 写文件 / ...
```

`config.yaml` 增加：
```yaml
pipeline:
  default_mode: polish        # raw|polish|summary|translate|command
  prefix_routing: true
  llm:
    provider: glm-cli         # glm-cli | openai
    openai:                   # provider=openai 时用
      base_url: ""
      api_key: ""
      model: ""
sinks:
  raw: type
  polish: type
  summary: file
  translate: type
  command: type
file_sink:
  dir: "~/VoiceNotes"
```

## 八、杀手级场景（结合你重度 AI 工作流）

- 🎙️→📝 走在路上想到个点子，按住说 2 分钟 → 自动结构化成 Markdown 存进 `~/VoiceNotes/`
- 🎙️→🤖 "帮我把刚才说的整理成给团队的周报" → LLM 生成 → 上屏到飞书/邮件
- 🎙️→🌐 中文口述 → 光标处直接出英文/日文
- 🎙️→⚙️ "查一下 XX 的最新进展" → 触发你的 deep-research skill
- 🎙️→📓 每次总结自动追加到当天的工作日志 `.md`

## 九、分阶段落地顺序

- **A. 润色模式**（最高频，验证整条管线跑通）
- **B. 总结→写文件**（你最想要的，体现"遥控"价值）
- **C. 翻译 + 指令/Agent**
- **D. 前缀词路由 + 托盘模式切换**（交互打磨）

> 识别层用 Soniox 保证质量、处理层用你熟的 LLM 调度——两边都踩在你的强项上。
