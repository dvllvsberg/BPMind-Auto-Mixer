from __future__ import annotations


def bpm_distance(a: float, b: float) -> float:
  """Минимальная разница BPM с учётом полтемпа и двойного темпа."""
  best = abs(a - b)
  for factor_a in (0.5, 1.0, 2.0):
    for factor_b in (0.5, 1.0, 2.0):
      best = min(best, abs(a * factor_a - b * factor_b))
  return best


def bpm_score(current_bpm: float, candidate_bpm: float, *, max_distance: float = 20.0) -> float:
  distance = bpm_distance(current_bpm, candidate_bpm)
  if distance >= max_distance:
    return 0.0
  return 100.0 * (1.0 - distance / max_distance)
