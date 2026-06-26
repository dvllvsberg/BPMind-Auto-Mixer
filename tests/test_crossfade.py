import numpy as np
import pytest

from engine.transitions.crossfade import crossfade_segments


def test_crossfade_segments_blends_two_halves():
  outgoing = np.ones((100, 1), dtype=np.float32)
  incoming = np.zeros((100, 1), dtype=np.float32)

  mixed = crossfade_segments(outgoing, incoming)

  assert mixed.shape == (100, 1)
  assert mixed[0, 0] == pytest.approx(1.0, abs=0.05)
  assert mixed[-1, 0] == pytest.approx(0.0, abs=0.05)
  assert mixed[50, 0] == pytest.approx(0.5, abs=0.05)


def test_crossfade_uses_shorter_overlap():
  outgoing = np.ones((80, 1), dtype=np.float32)
  incoming = np.zeros((50, 1), dtype=np.float32)

  mixed = crossfade_segments(outgoing, incoming)

  assert mixed.shape == (50, 1)
