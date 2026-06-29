from __future__ import annotations

import numpy as np
import pytest

from engine.playback.segment_envelope import (
  apply_opening_track_main_envelope,
  cosine_fade_in_envelope,
)


def test_cosine_fade_in_starts_at_zero_ends_at_one():
  env = cosine_fade_in_envelope(1000, fade_frames=200)
  assert env[0] == pytest.approx(0.0, abs=1e-6)
  assert env[199] == pytest.approx(1.0, abs=0.02)
  assert env[500] == pytest.approx(1.0)


def test_opening_track_skips_fade_out_before_transition():
  audio = np.ones((4410, 2), dtype=np.float32)
  with_transition = apply_opening_track_main_envelope(
    audio,
    fade_in_sec=0.0,
    fade_out_sec=0.05,
    apply_fade_out=False,
    sr=44100,
  )
  assert float(with_transition[-1, 0]) == pytest.approx(1.0)

  solo = apply_opening_track_main_envelope(
    audio,
    fade_in_sec=0.0,
    fade_out_sec=0.05,
    apply_fade_out=True,
    sr=44100,
  )
  assert float(solo[-1, 0]) == pytest.approx(0.0, abs=0.05)


def test_opening_track_envelope_fade_in_and_out():
  audio = np.ones((4410, 2), dtype=np.float32)
  shaped = apply_opening_track_main_envelope(
    audio,
    fade_in_sec=0.05,
    fade_out_sec=0.05,
    sr=44100,
  )
  assert float(shaped[0, 0]) == pytest.approx(0.0, abs=0.05)
  assert float(shaped[2200, 0]) == pytest.approx(1.0, abs=0.05)
  assert float(shaped[-1, 0]) == pytest.approx(0.0, abs=0.05)
