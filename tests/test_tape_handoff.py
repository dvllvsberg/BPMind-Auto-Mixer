import numpy as np
import pytest

from engine.transitions.tape_handoff import blend_tape_track_seam, soften_tape_boundary_dip


def test_soften_tape_boundary_dip_boosts_quiet_center():
  audio = np.zeros((5000, 2), dtype=np.float32)
  audio[:2000] = 0.4
  audio[2000:2400] = 0.02
  audio[2400:] = 0.35
  fixed = soften_tape_boundary_dip(audio, 2000, sr=22050)
  seam = fixed[1990:2010]
  assert float(np.max(np.abs(seam))) > 0.05


def test_blend_tape_track_seam_crossfades_incoming_head():
  tail = np.full((500, 2), 0.3, dtype=np.float32)
  incoming = np.zeros((800, 2), dtype=np.float32)
  incoming[500:] = 0.4
  blended = blend_tape_track_seam(tail, incoming)
  assert float(np.max(np.abs(blended[:100]))) > 0.05
  assert float(np.max(np.abs(blended[600:]))) == pytest.approx(0.4)
