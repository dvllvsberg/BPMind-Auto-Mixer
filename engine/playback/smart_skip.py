from __future__ import annotations

from engine.domain.models import PlannedTransition
from engine.transitions.playback_rules import (
  outgoing_tape_tail_sec,
  transition_is_disabled,
  transition_is_solo_tail,
)

SMART_SKIP_MAX_SEC = 4.0
SMART_SKIP_MIN_SEC = 0.75


def can_smart_skip(transition: PlannedTransition | None, *, enable_crossfade: bool) -> bool:
  if not enable_crossfade or transition is None:
    return False
  kind = transition.type.normalized()
  if transition_is_solo_tail(kind) or transition_is_disabled(kind):
    return False
  return True


def smart_skip_fade_sec(transition: PlannedTransition) -> float:
  planned = transition.crossfade_duration_sec or SMART_SKIP_MAX_SEC
  if transition_is_solo_tail(transition.type):
    planned = outgoing_tape_tail_sec(transition)
  return min(max(planned, SMART_SKIP_MIN_SEC), SMART_SKIP_MAX_SEC)


def smart_skip_tail_window(
  play_from_sec: float,
  until_sec: float,
  local_output_sec: float,
  fade_sec: float,
) -> tuple[float, float, float] | None:
  current_file_sec = play_from_sec + max(0.0, local_output_sec)
  tail_start = max(current_file_sec, until_sec - fade_sec)
  effective_fade = until_sec - tail_start
  if effective_fade < SMART_SKIP_MIN_SEC:
    return None
  return tail_start, until_sec, effective_fade
