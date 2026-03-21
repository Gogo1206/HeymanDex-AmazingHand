## AmazingHand Python Tools

Python GUI and command-line tools to control the AmazingHand robot using Feetech SCS0009 servos via a serial bus controller (e.g. Waveshare USB adapter).

This project is designed for the [AmazingHand](https://github.com/pollen-robotics/AmazingHand) by Pollen Robotics.

### Project Structure

```
amazing_hand_gui.py   – Main GUI application
amazing_hand_cmd.py   – Command-line interface
hand_logic.py         – Shared business logic (no UI dependencies)
pyproject.toml        – Package metadata, dependencies, pytest config
data/
  config.yaml         – App settings (serial ports, limits, speeds)
  hand_config.yaml    – Saved poses and sequences
docs/
  REQUIREMENTS.md     – Requirements & acceptance criteria
  user_manual.md      – User manual
  CONFIG_FORMAT.md    – Config file format reference
tests/
  test_hand_logic.py  – Unit tests for hand_logic (89 tests)
  test_gui_utils.py   – Unit tests for GUI utilities (51 tests)
  test_cmd.py         – Unit tests for CLI (41 tests)
  test_integration.py – Integration tests (14 tests)
  test_system.py      – System tests via subprocess (22 tests)
  test_system_hardware.py – Hardware tests (33 tests, requires --hardware)
```

### Requirements

- Python 3.10 or newer (Tkinter must be included for the GUI)
- External 5 V power supply for the eight servos
- USB serial bus adapter and driver installed on your computer

### Installation

Install with pip (recommended — uses `pyproject.toml`):

```bash
pip install -e .
```

Or install dependencies directly:

```bash
pip install -r requirements.txt
```

For development and testing:

```bash
pip install -r requirements-dev.txt
```

### Default Serial Port

Both the GUI and CLI try to choose a sensible default serial port:

- Windows: `COM9`
- Linux/macOS: `/dev/ttyACM0`

You can override this with the `--port` option, e.g. `python amazing_hand_gui.py --port COM4`.

---

### Running the GUI (`amazing_hand_gui.py`)

```bash
python amazing_hand_gui.py
```

Features:
- Per-finger sliders for open/close and left/right
- Per-finger Open / Close buttons for quick positioning
- Per-finger speed selection (1-6) with a global speed sync dropdown
- Keyboard shortcuts for quick precise movements
- Pose and sequence management using `data/hand_config.yaml`
- Delete saved poses directly from the GUI (🗑 Delete button)
- Live servo telemetry charts (position, load, temperature, voltage)

#### Keyboard Controls

- **1-4**: Select finger (Ring, Middle, Pointer, Thumb)
- **Arrow Keys**: Move selected finger
  - Up/Down: Close/Open
  - Left/Right: Move laterally
- **Modifiers**:
  - Normal: 1° per keypress (precise)
  - Shift: 5° per keypress (normal)
  - Ctrl: 10° per keypress (fast)
- **Quick Actions**:
  - Q: Fully close selected finger
  - E: Fully open selected finger
  - C: Center left/right position

#### Global Controls

- **✋ Open All / ✊ Close All / ⊙ Center All** perform simultaneous actions on every finger widget.
- **Global Speed** dropdown (1-6) instantly applies the chosen speed to all finger controls, keeping per-finger sliders in sync.

#### Poses and Sequences

All poses and sequences are stored in `data/hand_config.yaml`:

**Saving Poses:**
1. Position fingers using sliders or keyboard shortcuts
2. Enter a name in the "Name:" field
3. Click "➕ Add New" in the Pose Management section
  - Speeds only affect how the sliders move; saved poses store the 8 servo positions only

**Loading / Deleting Poses:**
- Select from dropdown and click **✓ Apply** to move the hand to that pose
- Click **🗑 Delete** (right of Apply) to permanently remove the selected pose after confirmation

**Sequence Management:**
1. Click "🔧 Manage" in the Sequence Player to open the sequence manager
2. **Saved Sequences** (left panel):
  - View, execute, edit, or delete existing sequences
  - Double-click or click "▶ Execute" to run a saved entry once
3. **Sequence Builder** (right panel):
  - Double-click poses from "Available Poses" to add them as steps
  - Choose individual servo speeds and delays for each step; steps are stored as `"pose:s1,s2,...,s8|delay"`
  - Use ↑/↓ to reorder steps or insert dedicated sleep steps with the "⏱ Delay" button
  - Enter a sequence name and click "💾 Save Sequence" to persist; use "▶ Execute" to test without saving
4. Back in the main window, use the "Loop" checkbox in the Sequence Player if you need continuous playback

**YAML Format Example:**

```yaml
poses:
  open:
    positions: [0, 0, 0, 0, 0, 0, 0, 0]
  close:
    positions: [110, 0, 110, 0, 110, 0, 110, 0]

sequences:
  demo:
    steps:
      - "open:3,3,3,3,3,3,3,3|2.0s"
      - "close:3,3,3,3,3,3,3,3|2.0s"
      - "SLEEP:1.0s"
  wave:
    steps:
      - "close:5,5,5,5,5,5,5,5|0.8s"
      - "open:2,2,2,2,2,2,2,2|0.8s"
```

Loop behavior is handled at runtime (GUI checkbox) and is no longer stored in YAML.

The GUI automatically creates `data/hand_config.yaml` if it doesn't exist.

---

### Running the CLI (`amazing_hand_cmd.py`)

A standalone command-line tool for applying poses and playing sequences without the GUI.
It reads the same `data/hand_config.yaml` used by the GUI.

#### List available poses and sequences

```bash
python amazing_hand_cmd.py --list
```

#### Apply a single pose

```bash
python amazing_hand_cmd.py --pose open
python amazing_hand_cmd.py --pose close
```

#### Play a sequence once

```bash
python amazing_hand_cmd.py --sequence demo
```

#### Play a sequence in a loop (Ctrl+C to stop)

```bash
python amazing_hand_cmd.py --sequence wave --loop
```

#### Options

| Option | Default | Description |
|---|---|---|
| `--pose NAME` | – | Apply the named pose |
| `--sequence NAME` | – | Play the named sequence |
| `--list` | – | List all poses and sequences |
| `--loop` | off | Loop sequence until Ctrl+C |
| `--port PORT` | `/dev/ttyACM0` (Linux) / `COM9` (Win) | Serial port |
| `--baudrate N` | `1000000` | Baud rate |
| `--config PATH` | `data/hand_config.yaml` | Alternative config file |

Torque is automatically disabled on all servos when the script exits (including Ctrl+C).

---

### Testing

The project includes 217 unit/integration/system tests plus 33 hardware tests.

#### Run all tests (no hardware required)

```bash
pytest
```

#### Run hardware tests (requires connected servos)

```bash
pytest tests/test_system_hardware.py --hardware --port /dev/ttyACM0
```

Hardware tests verify real servo communication: connection, pose apply, telemetry reads, individual finger open/close/wave, speed control, sequence execution, and movement detection.

See `docs/REQUIREMENTS.md` for the full requirements and acceptance criteria.

---

### Servo ID Configuration

Tutorial for configuring servo IDs with Feetech software and the serial bus driver:
<https://www.robot-maker.com/forum/tutorials/article/168-brancher-et-controler-le-servomoteur-feetech-sts3032-360/>

Feetech software download link:
<https://github.com/Robot-Maker-SAS/FeetechServo/tree/main/feetech%20debug%20tool%20master/FD1.9.8.2)>
