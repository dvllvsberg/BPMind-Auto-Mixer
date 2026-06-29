from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import _ensure_2d
from engine.transitions.overlap_utils import OVERLAP_SR, sec_to_frames
from engine.transitions.tape_stop import _read_variable_rate

# Impact ≠ tape: короткий «провал времени» у стыка, не длинный motor-stop.
IMPACT_DIP_SEC = 1.35
IMPACT_SNAP_SEC = 0.24
IMPACT_RATE_FLOOR = 0.18
IMPACT_MIN_DIP_FRAMES = 4000


def _dip_zone_fade_out(audio: np.ndarray, *, dip_start_frame: int) -> np.ndarray:
  audio = _ensure_2d(audio).astype(np.float32, copy=True)
  length = len(audio)
  dip_start = min(max(dip_start_frame, 0), length)
  dip_len = length - dip_start
  if dip_len <= 1:
    return audio
  phase = np.linspace(0.0, 1.0, dip_len, dtype=np.float32)
  ramp = 0.5 * (1.0 + np.cos(phase * np.pi))
  env = np.power(ramp, 1.22)
  audio[dip_start:] *= env.reshape(-1, 1)
  return audio


def impact_junction_frame(overlap: int) -> int:
  """Стык: конец pitch-dip / старт snap-up (не середина overlap)."""
  if overlap <= 0:
    return 0
  dip_frames = min(
    max(sec_to_frames(IMPACT_DIP_SEC), IMPACT_MIN_DIP_FRAMES // 2),
    overlap - 1,
  )
  dip_frames = min(dip_frames, max(overlap // 2, 1))
  return max(overlap - dip_frames, 1)


def impact_rate_plunge(progress: np.ndarray) -> np.ndarray:
  """Крутое падение скорости только в коротком dip-окне (не cosine tape-stop)."""
  curved = np.power(np.clip(progress, 0.0, 1.0), 2.4)
  return (IMPACT_RATE_FLOOR + (1.0 - IMPACT_RATE_FLOOR) * (1.0 - curved)).astype(
    np.float32, copy=False
  )


def impact_rate_snap_up(progress: np.ndarray) -> np.ndarray:
  """Резкий cinematic snap — быстрее и короче, чем tape spin."""
  curved = np.power(np.clip(progress, 0.0, 1.0), 0.18)
  return (IMPACT_RATE_FLOOR + (1.0 - IMPACT_RATE_FLOOR) * curved).astype(
    np.float32, copy=False
  )


def _apply_rate_curve(audio: np.ndarray, rates: np.ndarray) -> np.ndarray:
  audio = _ensure_2d(audio)
  length = len(audio)
  if length < 2:
    return audio.astype(np.float32, copy=False)

  channels = audio.shape[1]
  out = np.empty((length, channels), dtype=np.float32)
  local_rates = rates[:length].astype(np.float32, copy=False)
  mean_rate = float(np.mean(local_rates))

  for channel in range(channels):
    out[:, channel] = _read_variable_rate(audio[:, channel], local_rates, length)

  return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def impact_pitch_down_outgoing(tail: np.ndarray, *, junction_frame: int) -> np.ndarray:
  """
  A играет нормально до dip-окна; только последние ~1.1 с — крутой pitch-down к «дну».
  """
  tail = _ensure_2d(tail)
  overlap = len(tail)
  if overlap < 64:
    return tail.astype(np.float32, copy=False)

  junction = min(max(junction_frame, 1), overlap)
  out = tail.astype(np.float32, copy=True)

  dip_len = overlap - junction
  if dip_len < 8:
    return out

  dip_progress = np.linspace(0.0, 1.0, dip_len, dtype=np.float32)
  dip_rates = impact_rate_plunge(dip_progress)
  out[junction:] = _apply_rate_curve(tail[junction:], dip_rates)
  out = _dip_zone_fade_out(out, dip_start_frame=junction)
  return out


def impact_snap_up_incoming(head: np.ndarray, *, junction_frame: int) -> np.ndarray:
  """B: snap-up только с стыка, короткий разгон (не tape motor spin на всю голову)."""
  head = _ensure_2d(head)
  overlap = len(head)
  if overlap < 64:
    return head.astype(np.float32, copy=False)

  junction = min(max(junction_frame, 0), overlap)
  out = head.astype(np.float32, copy=True)
  blend_len = overlap - junction
  if blend_len < 8:
    return out

  snap_frames = min(sec_to_frames(IMPACT_SNAP_SEC), blend_len)
  snap_progress = np.linspace(0.0, 1.0, snap_frames, dtype=np.float32)
  snap_rates = impact_rate_snap_up(snap_progress)
  snap_part = _apply_rate_curve(head[junction : junction + snap_frames], snap_rates)
  out[junction : junction + snap_frames] = snap_part
  out[-1] = head[-1]
  return out


def build_impact_crossfade_gains(
  overlap: int,
  junction_frame: int,
) -> tuple[np.ndarray, np.ndarray]:
  """Cosine crossfade с стыка; до стыка A на полной громкости."""
  junction = min(max(junction_frame, 0), overlap)
  blend = overlap - junction

  out_gain = np.ones(overlap, dtype=np.float32)
  in_gain = np.zeros(overlap, dtype=np.float32)

  if blend > 0:
    phase = np.linspace(0.0, np.pi, blend, dtype=np.float32)
    out_gain[junction:] = 0.5 * (1.0 + np.cos(phase))
    in_gain[junction:] = 0.5 * (1.0 - np.cos(phase))

  return out_gain.reshape(-1, 1), in_gain.reshape(-1, 1)
