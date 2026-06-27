import numpy as np
import pytest
import soundfile as sf

from engine.analysis.intro_entry import detect_loud_entry_sec, intro_skip_sec


def test_detect_loud_entry_finds_quiet_duplicate_before_main_hit(tmp_path):
  sr = 22050
  duration_sec = 8.0
  t = np.linspace(0.0, duration_sec, int(sr * duration_sec), endpoint=False)
  quiet = 0.03 * np.sin(2 * np.pi * 3.0 * t)
  loud = 0.35 * np.sin(2 * np.pi * 3.0 * t)
  audio = np.concatenate(
    [
      quiet[: sr * 2],
      loud[sr * 2 : sr * 4],
      loud[sr * 4 :],
    ]
  ).astype(np.float32)
  path = tmp_path / "intro.wav"
  sf.write(path, audio, sr)

  entry = detect_loud_entry_sec(audio, sr)
  skip = intro_skip_sec(path, 0.0, scan_sec=8.0)
  assert entry == pytest.approx(2.0, abs=0.35)
  assert skip == pytest.approx(2.0, abs=0.35)


def test_intro_skip_returns_zero_when_no_level_jump(tmp_path):
  sr = 22050
  t = np.linspace(0.0, 3.0, int(sr * 3.0), endpoint=False)
  audio = (0.2 * np.sin(2 * np.pi * 5.0 * t)).astype(np.float32)
  path = tmp_path / "flat.wav"
  sf.write(path, audio, sr)
  assert intro_skip_sec(path, 0.0) == 0.0
