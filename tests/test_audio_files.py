"""Recognition tests driven by recordings in tests/fixtures/audio_samples/.

These run Vosk on real .wav files, so they need vosk installed and the model
downloaded. The whole module auto-skips when no samples are present, so the
default test run (no recordings committed) stays green and hardware-free.

Name a sample so its expected pose is known — either the spoken command word
itself (e.g. ``张开.mp3``, ``好的.mp3``) or a pose-name prefix (``open_1.wav``).
See tests/fixtures/audio_samples/README.md. Supported formats: wav/mp3/flac/ogg/opus.
"""
from amazing_hand.amazing_hand_audio import (
    AUDIO_EXTS,
    AUDIO_SAMPLES_DIR,
    POSE_VOCAB,
    match_command,
)

import pytest


def _audio_files():
    if not AUDIO_SAMPLES_DIR.is_dir():
        return []
    return sorted(
        p for p in AUDIO_SAMPLES_DIR.iterdir() if p.suffix.lower() in AUDIO_EXTS
    )


def _expected_pose(stem: str) -> str | None:
    norm = stem.lower()
    # 1. filename is the spoken command word itself (e.g. 张开, 好的)
    for pose, keywords in POSE_VOCAB.items():
        if norm in [k.lower() for k in keywords]:
            return pose
    # 2. filename starts with a command word, allowing a suffix such as a voice
    #    or take number (e.g. 张开_tingting, 好的-2)
    for pose, keywords in POSE_VOCAB.items():
        for k in keywords:
            if norm.startswith(k.lower()):
                return pose
    # 3. filename starts with a pose name (e.g. open_1, close_loud)
    for pose in POSE_VOCAB:
        if norm.startswith(pose):
            return pose
    return None


_FILES = _audio_files()

pytestmark = pytest.mark.skipif(
    not _FILES,
    reason="no recordings in tests/fixtures/audio_samples/ (drop some audio files to enable)",
)


@pytest.mark.parametrize("sample", _FILES, ids=[p.name for p in _FILES])
def test_sample_maps_to_expected_pose(sample):
    expected = _expected_pose(sample.stem)
    if expected is None:
        pytest.skip(
            f"{sample.name}: name it after the spoken word (张开/好的/…) or a "
            f"pose prefix (open/close/ok/victory) to be checked"
        )
    # Import here so collection doesn't require vosk when the module is skipped.
    from amazing_hand.amazing_hand_audio import recognize_file

    text = recognize_file(sample)
    assert match_command(text) == expected, f"{sample.name}: heard {text!r}"
