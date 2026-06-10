# Changelog

All notable changes to the AmazingHand controller project.

## [0.8.0] — 2026-06-10

### Added
- Voice control pipeline (Phase 1): push-to-talk, offline Vosk STT, fuzzy keyword match → 4 poses (`amazing_hand_audio.py`)
- Auto-select Vosk model: prefer small (grammar-constrained) over large
- MP3/any-format audio support + grammar-constrained recognition
- Mandarin-only, in-lexicon word bank for voice commands
- Pure Chinese command matcher with homophone tolerance
- Two-hand camera gesture recognition (left/right hand distinction)
- Offline Vosk mic capture with sounddevice
- Push-to-talk voice control loop and CLI (`--audio`, `--no-hand`)

### Changed
- Voice command vocabulary: 4 poses only (open/close/ok/victory), dropped 五指
- audio_samples moved to tests/fixtures/audio_samples/
- Project restructured to src/ layout (`src/amazing_hand/`)

## [0.7.0] — 2026-05

### Added
- PyQt6 native 4-button hand control panel (`amazing_hand_qt.py`)
- 4-button web control panel (`amazing_hand_web.py`, `web/index.html`)
- Camera hand-gesture recognition via MediaPipe (`amazing_hand_camera.py`)
- Per-gesture preview tint in Qt panel
- macOS serial port auto-detection

### Fixed
- macOS serial port auto-detection
- Tolerate disconnected servos (eliminate ~1s per-press delay)
- Gesture-preview width alignment

## [0.6.0] — 2026-04

### Added
- Initial public release: GUI (`amazing_hand_gui.py`), CLI (`amazing_hand_cmd.py`)
- Shared business logic (`hand_logic.py`)
- Pose and sequence management with YAML config (`data/hand_config.yaml`)
- Live servo telemetry charts (position, load, temperature, voltage)
- Keyboard controls with modifiers for precise finger positioning
- 284 unit/integration/system tests + 54 hardware tests
