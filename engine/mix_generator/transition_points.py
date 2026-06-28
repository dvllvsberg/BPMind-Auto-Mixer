from __future__ import annotations

from engine.domain.enums import TransitionCandidateKind
from engine.domain.models import Track

_KIND_PRIORITY = {
  TransitionCandidateKind.OUTRO_START: 3,
  TransitionCandidateKind.ENERGY_DROP: 2,
  TransitionCandidateKind.QUIET: 1,
}


def _content_bounds(track: Track) -> tuple[float, float]:
  start = track.content_start_sec if track.content_start_sec is not None else 0.0
  end = track.content_end_sec if track.content_end_sec is not None else track.duration
  if end is None:
    end = track.duration or start
  return start, float(end)


def _ratio_until(start: float, end: float, play_ratio: float) -> float:
  return start + (end - start) * play_ratio


def _default_play_until(
  track: Track,
  crossfade_duration: float,
  *,
  play_ratio: float,
) -> float | None:
  start, end = _content_bounds(track)
  content_length = end - start
  if content_length <= crossfade_duration:
    return end
  target = _ratio_until(start, end, play_ratio)
  return max(start, min(target, end - crossfade_duration))


def planning_crossfade_sec(global_crossfade_sec: float) -> float:
  """Запас для resolve_play_until до планирования переходов (auto-duration)."""
  return max(global_crossfade_sec, 10.0)


def resolve_play_until(
  track: Track,
  crossfade_duration: float,
  *,
  play_ratio: float = 0.75,
) -> float | None:
  play_ratio = max(0.5, min(0.95, play_ratio))
  start, end = _content_bounds(track)
  if not track.transition_candidates:
    return round(_default_play_until(track, crossfade_duration, play_ratio=play_ratio) or end, 3)

  min_play = start + min(30.0, (end - start) * 0.25)
  latest = end - crossfade_duration
  ratio_floor = min(_ratio_until(start, end, play_ratio), latest)
  if latest <= min_play:
    return round(_default_play_until(track, crossfade_duration, play_ratio=play_ratio) or end, 3)

  valid = [
    candidate
    for candidate in track.transition_candidates
    if min_play <= candidate.position_sec <= latest
  ]
  if not valid:
    return round(max(ratio_floor, min_play), 3)

  best = max(
    valid,
    key=lambda candidate: (
      _KIND_PRIORITY.get(candidate.kind, 0),
      candidate.confidence,
      candidate.position_sec,
    ),
  )
  play_until = max(best.position_sec, ratio_floor)
  play_until = min(play_until, latest)
  return round(play_until, 3)
