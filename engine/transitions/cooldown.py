from __future__ import annotations

from collections import deque

from engine.domain.enums import TransitionType


class CooldownTracker:
  def __init__(self, *, window: int = 4) -> None:
    self._window = window
    self._recent: deque[TransitionType] = deque(maxlen=window)

  def recent(self) -> tuple[TransitionType, ...]:
    return tuple(self._recent)

  def record(self, profile: TransitionType) -> None:
    self._recent.append(profile.normalized())

  def uses_count(self, profile: TransitionType, *, lookback: int | None = None) -> int:
    normalized = profile.normalized()
    items = list(self._recent)
    if lookback is not None:
      items = items[-lookback:]
    return sum(1 for item in items if item == normalized)
