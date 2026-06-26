from __future__ import annotations

import math

from engine.domain.enums import StartMode

WAVE_QUIET_DB = -27.0
WAVE_LOUD_DB = -10.0
WAVE_SPAN_DB = WAVE_LOUD_DB - WAVE_QUIET_DB


def wave_target_energy(step: int, total_steps: int) -> float:
  progress = step / max(total_steps - 1, 1)
  wave = math.sin(progress * math.pi)
  return WAVE_QUIET_DB + wave * WAVE_SPAN_DB


def scoring_energy_weight(mode: StartMode) -> float:
  if mode == StartMode.WAVE:
    return 0.38
  if mode in (StartMode.CALM, StartMode.PEAK):
    return 0.30
  return 0.30
