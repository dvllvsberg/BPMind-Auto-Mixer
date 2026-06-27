from __future__ import annotations

from engine.domain.enums import TransitionType
from engine.domain.models import PlannedTransition


def transition_is_solo_tail(transition_type: TransitionType) -> bool:
  """Переход на уходящем треке без overlap с входящим (tape stop → тишина → новый трек)."""
  return transition_type.normalized() is TransitionType.TAPE_STOP


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


def incoming_play_start_sec(
  play_from_sec: float,
  prev_transition: PlannedTransition | None,
  *,
  enable_crossfade: bool,
  incoming_track_id: int,
) -> float:
  if not enable_crossfade or prev_transition is None:
    return play_from_sec
  if prev_transition.to_track_id != incoming_track_id:
    return play_from_sec
  if transition_is_solo_tail(prev_transition.type):
    return play_from_sec
  return play_from_sec + prev_transition.crossfade_duration_sec
