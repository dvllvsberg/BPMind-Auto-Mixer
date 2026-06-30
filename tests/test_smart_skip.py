from __future__ import annotations

from engine.domain.enums import TransitionType
from engine.domain.models import PlannedTransition
from engine.playback.smart_skip import (
  SMART_SKIP_MAX_SEC,
  can_smart_skip,
  smart_skip_fade_sec,
  smart_skip_tail_window,
)


def _transition(
  transition_type: TransitionType = TransitionType.SMOOTH_BLEND,
  crossfade: float = 8.0,
) -> PlannedTransition:
  return PlannedTransition(
    from_track_id=1,
    to_track_id=2,
    type=transition_type,
    start_at_sec=0.0,
    crossfade_duration_sec=crossfade,
  )


def test_can_smart_skip_rejects_none_and_tape():
  assert can_smart_skip(_transition(), enable_crossfade=True)
  assert not can_smart_skip(None, enable_crossfade=True)
  assert not can_smart_skip(_transition(TransitionType.NONE), enable_crossfade=True)
  assert not can_smart_skip(_transition(TransitionType.TAPE_STOP), enable_crossfade=True)
  assert not can_smart_skip(_transition(), enable_crossfade=False)


def test_smart_skip_fade_sec_is_capped():
  assert smart_skip_fade_sec(_transition(crossfade=16.0)) == SMART_SKIP_MAX_SEC
  assert smart_skip_fade_sec(_transition(crossfade=2.0)) == 2.0


def test_smart_skip_tail_window_from_current_position():
  window = smart_skip_tail_window(
    play_from_sec=0.0,
    until_sec=30.0,
    local_output_sec=20.0,
    fade_sec=4.0,
  )
  assert window == (26.0, 30.0, 4.0)


def test_smart_skip_tail_window_too_short_returns_none():
  assert smart_skip_tail_window(0.0, 30.0, 29.8, 4.0) is None
