# Windows 部署指南

在 Windows 上跑这套语音输入法。**好消息：Windows 没有 macOS 那套"辅助功能/输入监控"授权坑，pynput 直接就能监听键鼠。**

---

## 0. 前提：装两样东西

1. **Python 3.12**（[python.org](https://www.python.org/downloads/) 下载，安装时**务必勾选 "Add python.exe to PATH"**）
   - 验证：开 PowerShell 或 CMD，输 `py -3.12 --version`，显示 `Python 3.12.x` 即可
   - ⚠️ 别用 3.13/3.14（部分 C 扩展库还没预编译包）
2. **Git**（[git-scm.com](https://git-scm.com/download/win)）

---

## 1. 拉代码

```cmd
git clone <你的 GitHub 仓库地址> 语音输入法
cd 语音输入法
```

## 2. 装环境（建 venv + 装依赖）

```cmd
scripts\setup_env.bat
```

## 3. 下模型（约 230MB，跨平台脚本）

```cmd
.venv\Scripts\python.exe scripts\download_model.py
```

## 4. 配置

```cmd
copy config.example.yaml config.yaml
```

然后用记事本/VS Code 打开 `config.yaml`，重点改两处：

- **`hotkey`**：热键。不确定填什么就先跑 `scripts\run.bat probe`，按一下你想用的键，照抄它给的填法。
- **`hotkey_mode`**：`hold`（按住说话）或 `toggle`（点一下开始、再点一下结束）。
- **LLM 配置**（润色/翻译/总结要用）：见下方「§ LLM 配置」。**只想先试基础识别**就把 `pipeline.default_mode` 设成 `raw`，识别完直接上屏、不调模型。

## 5. 跑

```cmd
scripts\run.bat
```

看到 `✅ 就绪` 后，按热键说话上屏。第一次可能弹 **麦克风权限**（Windows 设置→隐私→麦克风），允许即可。

---

## § LLM 配置（Windows）

润色 / 翻译 / 总结都要调大模型。三选一：

### 方式 A — 先不用（纯识别，最快跑通）
`config.yaml` 里：
```yaml
pipeline:
  default_mode: raw      # 识别完直接上屏，不调模型
```

### 方式 B — openai 兼容 HTTP（最通用）
```yaml
pipeline:
  llm:
    provider: openai
    openai:
      base_url: "https://open.bigmodel.cn/api/paas/v4"   # 智谱；也可换任意厂商
      api_key_env: "ZHIPU_API_KEY"
      model: "glm-4.5-air"
```
然后设环境变量（需账户有余额）：
```cmd
setx ZHIPU_API_KEY "你的key"
```
（`setx` 后要**重开终端**才生效）

### 方式 C — glm-cli（你 Windows 也装了 glm-provider skill 才用）
```yaml
pipeline:
  llm:
    provider: glm-cli
    glm_cli:
      python: "C:\\你的\\系统Python\\python.exe"
      script: "C:\\Users\\你\\.claude\\skills\\glm-provider\\ask_glm.py"
      model: "glm-4.7"
```

---

## 探测热键 / 排查

```cmd
scripts\run.bat probe
```
按一下键看该填什么 `hotkey`。Windows 上若按键没反应，多半是杀软/权限拦了全局钩子，用管理员身份开终端再试。

## 跟 Mac 的差异

| | macOS | Windows |
|---|---|---|
| 键鼠监听授权 | 要开"辅助功能/输入监控" | **不用**，直接能监听 |
| venv python | `.venv/bin/python` | `.venv\Scripts\python.exe` |
| 上屏快捷键 | Cmd+V（代码已自动判断） | Ctrl+V（代码已自动判断） |
| 启动脚本 | `bash scripts/run.sh` | `scripts\run.bat` |
