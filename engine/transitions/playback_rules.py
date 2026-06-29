from __future__ import annotations

from engine.domain.enums import TransitionType
from engine.domain.models import PlannedTransition
from engine.transitions.overlap_utils import OVERLAP_SR, sec_to_frames
from engine.transitions.reverse_swell import reverse_incoming_skip_sec
from engine.transitions.reverse_swell_motor import reverse_incoming_skip_frames


def transition_is_solo_tail(transition_type: TransitionType) -> bool:
  """Переход на уходящем треке без overlap с входящим (tape stop → тишина → новый трек)."""
  return transition_type.normalized() is TransitionType.TAPE_STOP


def transition_is_reverse_overlay(transition_type: TransitionType) -> bool:
  """Reverse — отражение головы B на стыке; main body с head[1] после pivot head[0]."""
  return transition_type.normalized() is TransitionType.REVERSE_SWELL


def transition_is_disabled(transition_type: TransitionType) -> bool:
  """Без перехода: стык треков без overlap и DSP."""
  return transition_type.normalized() is TransitionType.NONE


def planned_incoming_main_skip_sec(transition: PlannedTransition) -> float:
  """Сколько секунд головы входящего уже отдано в overlap-чанк."""
  kind = transition.type.normalized()

  if transition_is_solo_tail(kind):
    return 0.0
  if transition_is_disabled(kind):
    return 0.0
  if kind is TransitionType.REVERSE_SWELL:
    return reverse_incoming_skip_sec(crossfade_duration_sec=transition.crossfade_duration_sec)
  return transition.crossfade_duration_sec


# Разгон на входящем — минимум в 2 раза короче торможения на уходящем.
INCOMING_TAPE_SPIN_FACTOR = 0.5

# Пауза между торможением и разгоном (0 = стык без явной тишины).
TAPE_STOP_SILENCE_SEC = 0.0


def outgoing_tape_brake_sec(transition: PlannedTransition) -> float:
  if not transition_is_solo_tail(transition.type):
    return transition.crossfade_duration_sec
  total = transition.crossfade_duration_sec
  return max(0.0, (total - TAPE_STOP_SILENCE_SEC) / (1.0 + INCOMING_TAPE_SPIN_FACTOR))


def outgoing_tape_silence_sec(transition: PlannedTransition) -> float:
  if not transition_is_solo_tail(transition.type):
    return 0.0
  return TAPE_STOP_SILENCE_SEC


def outgoing_tape_tail_sec(transition: PlannedTransition) -> float:
  if not transition_is_solo_tail(transition.type):
    return transition.crossfade_duration_sec
  return outgoing_tape_brake_sec(transition) + outgoing_tape_silence_sec(transition)


def incoming_tape_spin_sec(
  prev_transition: PlannedTransition | None,
  *,
  enable_crossfade: bool,
  incoming_track_id: int,
) -> float:
  if not enable_crossfade or prev_transition is None:
    return 0.0
  if prev_transition.to_track_id != incoming_track_id:
    return 0.0
  if not transition_is_solo_tail(prev_transition.type):
    return 0.0
  return outgoing_tape_brake_sec(prev_transition) * INCOMING_TAPE_SPIN_FACTOR


def incoming_play_start_frame(
  play_from_sec: float,
  prev_transition: PlannedTransition | None,
  *,
  enable_crossfade: bool,
  incoming_track_id: int,
  head_entry_frames: int = 0,
) -> int:
  base_frame = int(play_from_sec * OVERLAP_SR)
  if not enable_crossfade or prev_transition is None:
    return base_frame
  if prev_transition.to_track_id != incoming_track_id:
    return base_frame
  kind = prev_transition.type.normalized()
  if transition_is_solo_tail(kind):
    return base_frame
  if kind is TransitionType.REVERSE_SWELL:
    return base_frame + reverse_incoming_skip_frames(
      crossfade_duration_sec=prev_transition.crossfade_duration_sec,
      head_entry_frames=head_entry_frames,
    )
  return base_frame + sec_to_frames(prev_transition.crossfade_duration_sec)


def incoming_play_start_sec(
  play_from_sec: float,
  prev_transition: PlannedTransition | None,
  *,
  enable_crossfade: bool,
  incoming_track_id: int,
) -> float:
  return incoming_play_start_frame(
    play_from_sec,
    prev_transition,
    enable_crossfade=enable_crossfade,
    incoming_track_id=incoming_track_id,
  ) / OVERLAP_SR
