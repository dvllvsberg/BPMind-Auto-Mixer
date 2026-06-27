from __future__ import annotations

from dataclasses import dataclass

from engine.domain.enums import TransitionCandidateKind, TransitionType
from engine.domain.models import Track
from engine.mix_generator.bpm_utils import bpm_distance
from engine.mix_generator.groove_similarity import groove_similarity, has_groove_profile


@dataclass(frozen=True)
class TransitionContext:
  from_track: Track
  to_track: Track
  delta_bpm: float
  loudness_delta: float
  groove_score: float
  has_quiet_outro: bool
  has_energy_drop_outro: bool
  incoming_louder: bool
  bpm_close: bool
  has_groove_data: bool
  recent_profiles: tuple[TransitionType, ...]
  step_index: int = 0
  total_steps: int = 1


def consecutive_smooth_count(recent_profiles: tuple[TransitionType, ...]) -> int:
  count = 0
  for profile in reversed(recent_profiles):
    if profile.normalized() is TransitionType.SMOOTH_BLEND:
      count += 1
    else:
      break
  return count


def _track_loudness(track: Track) -> float:
  return track.loudness_avg if track.loudness_avg is not None else -18.0


def _has_quiet_outro(track: Track) -> bool:
  for candidate in track.transition_candidates:
    if candidate.kind == TransitionCandidateKind.QUIET:
      return True
  return False


def _has_energy_drop_outro(track: Track) -> bool:
  for candidate in track.transition_candidates:
    if candidate.kind == TransitionCandidateKind.ENERGY_DROP:
      return True
  return False


def build_transition_context(
  from_track: Track,
  to_track: Track,
  *,
  recent_profiles: tuple[TransitionType, ...] = (),
  step_index: int = 0,
  total_steps: int = 1,
) -> TransitionContext:
  bpm_a = from_track.bpm or 0.0
  bpm_b = to_track.bpm or 0.0
  delta_bpm = bpm_distance(bpm_a, bpm_b)
  from_loud = _track_loudness(from_track)
  to_loud = _track_loudness(to_track)
  groove = groove_similarity(from_track, to_track) / 100.0

  return TransitionContext(
    from_track=from_track,
    to_track=to_track,
    delta_bpm=delta_bpm,
    loudness_delta=abs(from_loud - to_loud),
    groove_score=groove,
    has_quiet_outro=_has_quiet_outro(from_track),
    has_energy_drop_outro=_has_energy_drop_outro(from_track),
    incoming_louder=to_loud > from_loud + 2.0,
    bpm_close=delta_bpm <= 4.0,
    has_groove_data=has_groove_profile(from_track) and has_groove_profile(to_track),
    recent_profiles=recent_profiles,
    step_index=step_index,
    total_steps=total_steps,
  )
