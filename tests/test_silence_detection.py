import numpy as np
import pytest

from engine.analysis.silence_detection import detect_content_bounds


def test_detect_content_bounds_trims_trailing_silence():
  sr = 22050
  audible = np.ones(sr * 5, dtype=np.float32) * 0.5
  silence = np.zeros(sr * 3, dtype=np.float32)
  y = np.concatenate([audible, silence])

  start, end = detect_content_bounds(y, sr, min_silence_sec=1.0)

  assert start == pytest.approx(0.0, abs=0.2)
  assert end == pytest.approx(5.0, abs=0.5)


def test_detect_content_bounds_trims_leading_silence():
  sr = 22050
  silence = np.zeros(sr * 2, dtype=np.float32)
  audible = np.ones(sr * 4, dtype=np.float32) * 0.5
  y = np.concatenate([silence, audible])

  start, end = detect_content_bounds(y, sr, min_silence_sec=1.0)

  assert start == pytest.approx(2.0, abs=0.5)
  assert end == pytest.approx(6.0, abs=0.5)


def test_detect_content_bounds_ignores_short_gaps():
  sr = 22050
  y = np.ones(sr * 4, dtype=np.float32) * 0.5
  y[: int(0.3 * sr)] = 0.0

  start, end = detect_content_bounds(y, sr, min_silence_sec=2.0)

  assert start == pytest.approx(0.0, abs=0.2)
  assert end == pytest.approx(4.0, abs=0.3)
