from __future__ import annotations

from collections import Counter

from engine.domain.enums import TransitionType
from engine.domain.models import MixSession, PlannedTransition

_PROFILE_LABELS: dict[TransitionType, str] = {
  TransitionType.SMOOTH_BLEND: "плавный",
  TransitionType.CUT: "резкий",
  TransitionType.FILTER_SWEEP: "фильтр (LP)",
}


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

  counts: Counter[str] = Counter()
  for transition in session.transitions:
    counts[transition_profile_label(transition.type)] += 1

  parts = [f"{name} ×{count}" for name, count in counts.most_common()]
  return "Переходы (авто): " + ", ".join(parts)
