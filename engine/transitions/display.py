from __future__ import annotations

from collections import Counter

from engine.domain.enums import TransitionType
from engine.domain.models import MixSession, PlannedTransition

_PROFILE_LABELS: dict[TransitionType, str] = {
  TransitionType.SMOOTH_BLEND: "плавный",
  TransitionType.NONE: "нет",
  TransitionType.FILTER_SWEEP: "фильтр (LP)",
  TransitionType.ECHO_OUT: "reverb",
  TransitionType.BASS_SWAP: "бас-своп",
  TransitionType.TAPE_STOP: "стоп ленты",
  TransitionType.VINYL_BRAKE: "винил",
  TransitionType.REVERSE_SWELL: "реверс",
  TransitionType.IMPACT: "удар",
}

# Порядок для GUI/CLI (тест редких профилей)
DEBUG_TRANSITION_PROFILES: tuple[TransitionType, ...] = (
  TransitionType.SMOOTH_BLEND,
  TransitionType.FILTER_SWEEP,
  TransitionType.ECHO_OUT,
  TransitionType.BASS_SWAP,
  TransitionType.IMPACT,
  TransitionType.REVERSE_SWELL,
  TransitionType.TAPE_STOP,
  TransitionType.VINYL_BRAKE,
)


def transition_profile_label(transition_type: TransitionType) -> str:
  return _PROFILE_LABELS.get(transition_type.normalized(), transition_type.value)


def format_transition_arrow(transition: PlannedTransition | None) -> str:
  if transition is None:
    return ""
  label = transition_profile_label(transition.type)
  if transition.crossfade_duration_sec <= 0:
    return f"  → {label}"
  duration = transition.crossfade_duration_sec
  if duration == int(duration):
    duration_text = f"{int(duration)} с"
  else:
    duration_text = f"{duration:g} с"
  return f"  → {label} ({duration_text})"


def summarize_session_transitions(session: MixSession) -> str:
  if not session.transitions:
    return "Переходы: нет данных — нажмите «Построить микс» заново"

  normalized_types = {transition.type.normalized() for transition in session.transitions}
  if len(normalized_types) == 1:
    only = transition_profile_label(session.transitions[0].type)
    count = len(session.transitions)
    return f"Переходы ({only}): ×{count}"

  counts: Counter[str] = Counter()
  for transition in session.transitions:
    counts[transition_profile_label(transition.type)] += 1

  parts = [f"{name} ×{count}" for name, count in counts.most_common()]
  return "Переходы (авто): " + ", ".join(parts)
