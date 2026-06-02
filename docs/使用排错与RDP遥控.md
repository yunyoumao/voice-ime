# 使用排错 & RDP / 遥控器笔记

实战踩坑记录。覆盖：杀软误报、麦克风、配置生效、遥控器热键、RDP 远程使用。

---

## 1. 杀软误报（Defender 把 exe 当病毒）

- **现象**：下载/运行报 `Trojan:Win32/Bearfoos.B!ml`、`Wacatac` 等，结尾 `!ml`。
- **根因**：PyInstaller 打包 + 未签名 + 全局键盘钩子/写注册表自启 → 启发式/ML 误报。`!ml`=机器学习猜的，**不是真毒**。
- **临时解**（自己机器）：
  ```powershell
  Add-MpPreference -ExclusionPath "<程序文件夹>"
  Add-MpPreference -ExclusionProcess "VoiceInput.exe"
  ```
  下载的包还带"来自网络"封锁时：`Get-ChildItem <folder> -Recurse | Unblock-File`。
- **降误报**（v0.0.2 已做）：spec `upx=False` + `version_info.txt` 补公司/产品/版本元数据（空白元数据加重误报）。
- **根治**：向微软提交误报申诉（https://www.microsoft.com/en-us/wdsi/filesubmission ，选 Software developer）；彻底免 SmartScreen 需代码签名证书。

## 2. 麦克风选不对 / 一开就闪退

- **现象**：日志 `Multiple input devices found for '...'`，程序启动即退出。
- **根因**：同一支麦在 Windows 的 MME / DirectSound / WASAPI / WDM-KS **四套接口下重名**，按名字匹配时撞多个 → sounddevice 抛错。
- **修复**（v0.0.2，`desktop/audio.py` 的 `_resolve_device`）：撞名时自动取第一个输入设备（通常 MME），永不崩。
- **配置建议**：`audio.device` 填 `null`（系统默认）或具体**索引整数**，别填会重名的设备名。

## 3. 改了配置不生效

- 配置**只在程序启动时读一次** → 改 key / 热键 / 任何设置后，**必须重启主程序**。
- 设置界面保存 key 的坑（v0.0.3 已修）：误点「载入默认值」再保存曾会把已存 key 冲空 → 后端加了安全网，空值不再覆盖已存的 key/凭据。

## 4. 遥控器 / 快捷键

- 音量键可直接当热键：`remote.talk_hotkey: <media_volume_up>`、`menu_hotkey: <media_volume_down>`，配 `suppress: true` 吃掉音量变化。
- **CheerTok 等只有音量键的蓝牙遥控器**：想把音量键改成普通键（如 F13）——
  - **PowerToys 键盘管理器改不了**：它对多媒体键做源键映射是已知短板（GitHub 一堆 issue），实测无效。
  - AutoHotkey 理论上行（`Volume_Up::F13`），但**对 RDP 远程无用**（见下）。
- 设置界面"录制"抓不到音量键（系统级多媒体键）→ 用"填音量+/−"按钮（v0.0.3 修了缺失的 setKey）。

## 5. RDP 远程使用（重点）

### 原理：为什么音量键在 RDP 下只动远程
- VoiceInput 跑在**本地**，监听本地键盘钩子。
- RDP 焦点时，键盘输入被转发给远程。**普通键**（右Alt 等）会同时走本地钩子 + 转发远程（两边都触发）；**音量键这类多媒体键**则被 RDP 从"媒体通道"直接抓走送远程，**绕过本地钩子** → 本地 VoiceInput 收不到，只有远程音量在变。
- 推论：**任何本地改键工具（AHK/PowerToys）在 RDP 下都救不了音量键** —— 键还没到它们手里就被 RDP 拿走了。

### 方案：要把语音打进远程 → 把 VoiceInput 装到远程
1. **开 RDP 麦克风重定向**（mstsc → 显示选项 → 本地资源 → 远程音频设置 → 远程录制「从此计算机录制」）。
2. 把 `VoiceInput` 程序文件夹 + 远程版 `config.yaml` 拷到远程（RDP 剪贴板）。
3. 远程上加 Defender 排除、首次运行下模型、放好 config、重启。
4. 远程版 config 关键项：`audio.device: null`（自动选重定向麦）、`audio.gain: 4~8`（RDP 麦偏小声）、音量键当热键。
5. 用右Alt（普通键）在远程也能直接当热键，最稳。

### ✅ 已确认可用（实测打通）
实测：RDP 会把音量键以**键盘事件**转发到远程 → 远程的 VoiceInput 能正常接住，CheerTok（仅音量键）在远程可直接触发录音。所以这套组合 **已验证打通**：
- 远程跑 VoiceInput（音量键当热键）
- RDP 麦克风重定向「从此计算机录制」把本地麦送过去
- 远程版 config：`audio.device: null` + `gain: 4~8`

本地（不开 RDP）用音量键、远程（RDP 焦点）用同一个 CheerTok 音量键，两个场景各跑一份 VoiceInput 即可。
