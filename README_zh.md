## AmazingHand Python 工具集

通过串行总线控制器（如 Waveshare USB 适配器）控制 AmazingHand 机械手的 Python GUI 和命令行工具，使用 Feetech SCS0009 舵机。

本项目为 [Pollen Robotics 的 AmazingHand](https://github.com/pollen-robotics/AmazingHand) 设计。

### 项目结构

```
src/amazing_hand/
  __init__.py           – 包元数据
  hand_logic.py         – 共享业务逻辑（无 UI 依赖）
  amazing_hand_cmd.py   – 命令行界面
  amazing_hand_gui.py   – 主 GUI 应用
  amazing_hand_audio.py – 语音控制（按键说话，离线语音识别）
  amazing_hand_camera.py– 摄像头手势控制
  amazing_hand_qt.py    – PyQt6 原生控制面板
  amazing_hand_web.py   – Web 控制面板后端
pyproject.toml          – 包元数据、依赖、pytest 配置
requirements.txt        – 完整依赖列表（核心 + 可选分组）
data/
  config.yaml           – 应用设置（串口、限位、速度）
  hand_config.yaml      – 已保存的手势和序列
docs/
  REQUIREMENTS.md       – 需求与验收标准
  user_manual.md        – 用户手册
  CONFIG_FORMAT.md      – 配置文件格式参考
tests/
  test_hand_logic.py    – hand_logic 单元测试（155 条）
  test_gui_utils.py     – GUI 工具单元测试（51 条）
  test_cmd.py           – CLI 单元测试（42 条）
  test_camera.py        – 摄像头单元测试（12 条）
  test_audio.py         – 音频匹配单元测试（20 条）
  test_audio_files.py   – 录音识别测试
  test_web.py           – Web 面板单元测试（10 条）
  test_integration.py   – 集成测试（14 条）
  test_system.py        – 系统测试（22 条，通过子进程运行）
  test_system_hardware.py – 硬件测试（33 条，需 --hardware 参数）
  test_cmd_hardware.py    – CMD 硬件测试（21 条，需 --hardware 参数）
  fixtures/
    audio_samples/      – test_audio_files.py 的语音录音
```

### 环境要求

- Python 3.10 或更高版本（GUI 需要包含 Tkinter）
- 为八个舵机提供外部 5V 电源
- 电脑上安装 USB 串行总线适配器及驱动

### 安装

推荐使用 pip 安装（使用 `pyproject.toml`）：

```bash
pip install -e .
```

安装后可使用控制台命令：`amazing-hand-gui`、`amazing-hand-cmd`。
或直接运行：`python src/amazing_hand/amazing_hand_cmd.py`。

安装可选功能：

```bash
pip install -e ".[audio]"      # 语音控制
pip install -e ".[camera]"     # 手势识别
pip install -e ".[qt]"         # Qt 原生面板
pip install -e ".[all]"        # 全部功能
```

或直接安装所有依赖：

```bash
pip install -r requirements.txt
```

开发与测试依赖：

```bash
pip install -r requirements-dev.txt
```

### 默认串口

GUI 和 CLI 均会尝试选择合理的默认串口：

- Windows：`COM9`
- Linux/macOS：`/dev/ttyACM0`

可通过 `--port` 参数覆盖，例如 `python src/amazing_hand/amazing_hand_gui.py --port /dev/ttyUSB0`（Linux）或 `python src/amazing_hand/amazing_hand_gui.py --port COM4`（Windows）。

---

### 运行 GUI（`amazing_hand_gui.py`）

通过 pip 安装后：

```bash
amazing-hand-gui
amazing-hand-gui --port /dev/ttyUSB0
```

或直接运行：

```bash
python src/amazing_hand/amazing_hand_gui.py
python src/amazing_hand/amazing_hand_gui.py --port /dev/ttyUSB0
```

功能：
- 每根手指的张开/闭合和左/右滑块
- 每根手指的张开/闭合快捷按钮
- 每根手指速度选择（1-6），全局速度同步下拉菜单
- 键盘快捷键实现快速精确移动
- 使用 `data/hand_config.yaml` 管理手势和序列
- 直接在 GUI 中删除已保存的手势（🗑 删除按钮）
- 实时舵机遥测图表（位置、负载、温度、电压）

#### 键盘控制

- **1-4**：选择手指（无名指、中指、食指、拇指）
- **方向键**：移动选中的手指
  - 上/下：闭合/张开
  - 左/右：横向移动
- **修饰键**：
  - 普通：每次按键 1°（精确）
  - Shift：每次按键 5°（常规）
  - Ctrl：每次按键 10°（快速）
- **快捷操作**：
  - Q：完全闭合选中手指
  - E：完全张开选中手指
  - C：居中左右位置

#### 全局控制

- **✋ 全部张开 / ✊ 全部闭合 / ⊙ 全部居中** 同时对每根手指执行操作。
- **全局速度** 下拉菜单（1-6）可即时将选定速度应用到所有手指控件，保持各手指滑块同步。

#### 手势与序列

所有手势和序列存储在 `data/hand_config.yaml` 中：

**保存手势：**
1. 使用滑块或键盘快捷键调整手指位置
2. 在 "Name:" 输入框中输入名称
3. 在"手势管理"区域点击 "➕ Add New"
  - 速度仅影响滑块移动方式；保存的手势仅存储 8 个舵机位置

**加载 / 删除手势：**
- 从下拉菜单选择后点击 **✓ Apply** 将机械手移动到该手势
- 点击 **🗑 Delete**（Apply 右侧）确认后永久删除选中手势

**序列管理：**
1. 在序列播放器中点击 "🔧 Manage" 打开序列管理器
2. **已保存序列**（左侧面板）：
  - 查看、执行、编辑或删除已有序列
  - 双击或点击 "▶ Execute" 运行一次已保存的条目
3. **序列构建器**（右侧面板）：
  - 双击"可用手势"中的手势将其添加为步骤
  - 为每个步骤选择单独的舵机速度和延迟；步骤存储格式为 `"pose:s1,s2,...,s8|delay"`
  - 使用 ↑/↓ 调整步骤顺序，或使用 "⏱ Delay" 按钮插入独立的等待步骤
  - 输入序列名称并点击 "💾 Save Sequence" 保存；使用 "▶ Execute" 测试而不保存
4. 回到主窗口后，如需连续播放可在序列播放器中勾选 "Loop" 复选框

**YAML 格式示例：**

```yaml
poses:
  open:
    positions: [0, 0, 0, 0, 0, 0, 0, 0]
  close:
    positions: [110, 110, 110, 110, 110, 110, 110, 110]
  ring_close:
    positions: [110, 0, 0, 0, 0, 0, 0, 0]

sequences:
  wave:
    steps:
      - "open:6,6,6,6,6,6,6,6|0.8s"
      - "wave_r:5,5,5,5,5,5,5,5|0.6s"
      - "wave_l:5,5,5,5,5,5,5,5|0.6s"
      - "open:5,5,5,5,5,5,5,5|0.8s"
  finger_roll:
    steps:
      - "open:6,6,6,6,6,6,6,6|0.5s"
      - "ring_close:5,5,5,5,5,5,5,5|0.6s"
      - "open:5,5,5,5,5,5,5,5|0.5s"
      - "middle_close:5,5,5,5,5,5,5,5|0.6s"
      - "open:5,5,5,5,5,5,5,5|0.5s"
  demo:
    steps:
      - "open:3,3,3,3,3,3,3,3|2.0s"
      - "close:3,3,3,3,3,3,3,3|2.0s"
      - "SLEEP:1.0s"
```

循环行为在运行时处理（GUI 复选框），不再存储在 YAML 中。

如果 `data/hand_config.yaml` 不存在，GUI 会自动创建。

---

### 运行 CLI（`amazing_hand_cmd.py`）

独立的命令行工具，无需 GUI 即可应用手势和播放序列。
它读取 `data/hand_config.yaml`，与 GUI 共用同一配置文件。

#### Linux：串口访问

USB 串行适配器通常显示为 `/dev/ttyACM0`（Waveshare / CDC-ACM）或 `/dev/ttyUSB0`（FTDI / CH340）。

查找设备：
```bash
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
# 或
dmesg | grep -E 'ttyACM|ttyUSB' | tail -5
```

如果遇到 **Permission denied** 错误，将用户添加到 `dialout` 组并重新登录：
```bash
sudo usermod -aG dialout $USER
```

#### 通过 pip 安装后

```bash
amazing-hand-cmd --list
amazing-hand-cmd --pose open
amazing-hand-cmd --sequence demo --loop
amazing-hand-cmd --pose open --speed 6
# 如需要可覆盖串口：
amazing-hand-cmd --pose open --port /dev/ttyUSB0
```

#### 直接运行

##### 列出可用手势和序列

```bash
python src/amazing_hand/amazing_hand_cmd.py --list
```

##### 应用单个手势

```bash
python src/amazing_hand/amazing_hand_cmd.py --pose open
python src/amazing_hand/amazing_hand_cmd.py --pose close
python src/amazing_hand/amazing_hand_cmd.py --pose scissors --speed 6
```

##### 设置舵机速度（1 慢 … 6 快，默认 3）

```bash
python src/amazing_hand/amazing_hand_cmd.py --pose close --speed 6
python src/amazing_hand/amazing_hand_cmd.py --sequence wave --speed 4
```

##### 覆盖串口

```bash
python src/amazing_hand/amazing_hand_cmd.py --pose open --port /dev/ttyACM0
python src/amazing_hand/amazing_hand_cmd.py --pose open --port /dev/ttyUSB0
```

##### 播放序列（一次）

```bash
python src/amazing_hand/amazing_hand_cmd.py --sequence demo
```

##### 循环播放序列（Ctrl+C 停止）

```bash
python src/amazing_hand/amazing_hand_cmd.py --sequence wave --loop
```

##### 使用替代配置文件

```bash
python src/amazing_hand/amazing_hand_cmd.py --list --config /path/to/hand_config.yaml
```

#### 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--pose NAME` | – | 应用指定手势 |
| `--sequence NAME` | – | 播放指定序列 |
| `--list` | – | 列出所有手势和序列 |
| `--loop` | off | 循环播放序列，直到 Ctrl+C |
| `--speed N` | `3` | 舵机速度 1（慢）… 6（快） |
| `--port PORT` | `/dev/ttyACM0`（Linux）/ `COM9`（Win） | 串口 |
| `--baudrate N` | `1000000` | 波特率 |
| `--config PATH` | `data/hand_config.yaml` | 替代配置文件 |

脚本退出时（包括 Ctrl+C）会自动释放所有舵机扭矩。

---

### 语音控制（中文，离线）

按住 **空格键**，说出指令，松开 — 机械手即动作。离线运行（Vosk），无需大语言模型。

| 说出（中文）         | 手势    |
|----------------------|---------|
| 张开 / 打开 / 展开   | open    |
| 握拳 / 握紧 / 抓紧   | close   |
| 好的 / 抓取 / 可以   | ok      |
| 胜利 / 剪刀 / 两个   | victory |

仅限普通话（不支持英文）— 所选词汇清晰且在小模型的词表中。完整词表见 `amazing_hand_audio.py` 中的 `POSE_VOCAB`。

```bash
python src/amazing_hand/amazing_hand_audio.py            # 控制机械手
python src/amazing_hand/amazing_hand_audio.py --no-hand  # 仅识别，不连接串口
```

首次使用需配置：`pip install vosk sounddevice pynput soundfile`，并将 Vosk 小型中文模型下载到 `models/vosk-model-small-cn-0.22/`（见 `docs/superpowers/plans/2026-06-10-voice-control.md` 任务 2）。在 macOS 上，需在系统设置中授权终端"输入监控"权限以检测空格键。

---

### 测试

项目包含 284 条单元/集成/系统测试，外加 54 条硬件测试。

#### 运行所有测试（无需硬件）

```bash
pytest
```

#### 运行 GUI+CLI 硬件测试（需连接舵机）

```bash
pytest tests/test_system_hardware.py --hardware --port /dev/ttyACM0
pytest tests/test_cmd_hardware.py --hardware --port /dev/ttyACM0
# 或同时运行：
pytest tests/test_system_hardware.py tests/test_cmd_hardware.py --hardware
```

`test_system_hardware.py` 验证连接、手势应用、遥测读取、单指张开/闭合/波浪、速度控制、序列执行和运动检测。

`test_cmd_hardware.py` 验证 CLI 层的端到端功能：手势位置、速度参数、序列步骤、`wait_for_motion`、`--list` 输出和扭矩释放。

完整需求与验收标准见 `docs/REQUIREMENTS.md`。

---

### 舵机 ID 配置

使用 Feetech 软件配置舵机 ID 的教程及串行总线驱动：
<https://www.robot-maker.com/forum/tutorials/article/168-brancher-et-controler-le-servomoteur-feetech-sts3032-360/>

Feetech 软件下载链接：
<https://github.com/Robot-Maker-SAS/FeetechServo/tree/main/feetech%20debug%20tool%20master/FD1.9.8.2)>
