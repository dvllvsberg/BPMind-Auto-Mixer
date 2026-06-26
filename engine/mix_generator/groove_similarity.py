from __future__ import annotations

import numpy as np

from engine.domain.models import EnergySegment, Track

PROFILE_POINTS = 32
PAIR_POINTS = 16
TAIL_START_RATIO = 0.62
HEAD_END_RATIO = 0.38
TRANSITION_BLEND = 0.62


def _profile_correlation(left: np.ndarray, right: np.ndarray) -> float:
  if len(left) < 2 or len(right) < 2:
    return 50.0

  left = left - np.mean(left)
  right = right - np.mean(right)
  left_norm = np.linalg.norm(left)
  right_norm = np.linalg.norm(right)
  if left_norm <= 1e-6 or right_norm <= 1e-6:
    return 50.0

  min_len = min(len(left), len(right))
  left = left[:min_len]
  right = right[:min_len]
  correlation = float(np.dot(left, right) / (left_norm * right_norm))
  correlation = max(-1.0, min(1.0, correlation))
  return (correlation + 1.0) * 50.0


def _energy_profile(energy_map: list[EnergySegment], points: int = PROFILE_POINTS) -> np.ndarray | None:
  if len(energy_map) < 2:
    return None

  starts = np.array([segment.start_sec for segment in energy_map], dtype=np.float64)
  values = np.array([segment.energy for segment in energy_map], dtype=np.float64)
  total_start = float(starts[0])
  total_end = float(energy_map[-1].end_sec)
  if total_end <= total_start:
    return None

  grid = np.linspace(total_start, total_end, points)
  return np.interp(grid, starts, values)


def _region_profile(
  energy_map: list[EnergySegment],
  *,
  start_ratio: float,
  end_ratio: float,
  points: int = PAIR_POINTS,
) -> np.ndarray | None:
  if len(energy_map) < 2:
    return None

  total_start = float(energy_map[0].start_sec)
  total_end = float(energy_map[-1].end_sec)
  if total_end <= total_start:
    return None

  region_start = total_start + (total_end - total_start) * start_ratio
  region_end = total_start + (total_end - total_start) * end_ratio
  if region_end <= region_start:
    return None

  grid = np.linspace(region_start, region_end, points)
  starts = np.array([segment.start_sec for segment in energy_map], dtype=np.float64)
  values = np.array([segment.energy for segment in energy_map], dtype=np.float64)
  return np.interp(grid, starts, values)


def _full_groove_similarity(current: Track, candidate: Track) -> float:
  left = _energy_profile(current.energy_map)
  right = _energy_profile(candidate.energy_map)
  if left is None or right is None:
    return 50.0
  return _profile_correlation(left, right)


def _transition_pair_similarity(current: Track, candidate: Track) -> float:
  outgoing_tail = _region_profile(
    current.energy_map,
    start_ratio=TAIL_START_RATIO,
    end_ratio=1.0,
  )
  incoming_head = _region_profile(
    candidate.energy_map,
    start_ratio=0.0,
    end_ratio=HEAD_END_RATIO,
  )
  if outgoing_tail is None or incoming_head is None:
    return 50.0

  boundary_delta = abs(float(outgoing_tail[-1]) - float(incoming_head[0]))
  level_score = max(0.0, 100.0 - boundary_delta * 6.0)

  if len(outgoing_tail) > 1 and len(incoming_head) > 1:
    shape_score = _profile_correlation(np.diff(outgoing_tail), np.diff(incoming_head))
  else:
    shape_score = 50.0

  return level_score * 0.55 + shape_score * 0.45


def groove_similarity(current: Track, candidate: Track) -> float:
  if not has_groove_profile(current) or not has_groove_profile(candidate):
    return 50.0

  transition = _transition_pair_similarity(current, candidate)
  full = _full_groove_similarity(current, candidate)
  return transition * TRANSITION_BLEND + full * (1.0 - TRANSITION_BLEND)


def has_groove_profile(track: Track) -> bool:
  return len(track.energy_map) >= 2
