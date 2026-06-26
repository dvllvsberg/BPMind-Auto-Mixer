from __future__ import annotations

from engine.domain.models import Track
from engine.mix_generator.bpm_utils import bpm_score
from engine.mix_generator.groove_similarity import groove_similarity, has_groove_profile


def _track_energy(track: Track) -> float:
  if track.loudness_avg is not None:
    return track.loudness_avg
  if track.loudness_peak is not None:
    return track.loudness_peak
  return -20.0


def score_candidate(
  current: Track,
  candidate: Track,
  *,
  target_energy: float | None = None,
  energy_weight: float = 0.30,
  groove_weight: float = 0.15,
) -> float:
  if current.bpm is None or candidate.bpm is None:
    return 0.0

  use_groove = groove_weight > 0 and has_groove_profile(current) and has_groove_profile(candidate)
  groove_part = groove_similarity(current, candidate) if use_groove else 50.0
  effective_groove_weight = groove_weight if use_groove else 0.0

  bpm_part = bpm_score(current.bpm, candidate.bpm)

  if target_energy is None:
    energy_part = 50.0
  else:
    energy = _track_energy(candidate)
    delta = abs(energy - target_energy)
    energy_part = max(0.0, 100.0 - delta * 4.0)

  bpm_weight = max(0.0, 1.0 - energy_weight - effective_groove_weight)
  return bpm_part * bpm_weight + energy_part * energy_weight + groove_part * effective_groove_weight
