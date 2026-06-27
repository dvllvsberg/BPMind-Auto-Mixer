from enum import Enum


class StartMode(str, Enum):
  RANDOM = "random"
  FROM_TRACK = "from_track"
  CALM = "calm"
  PEAK = "peak"
  WAVE = "wave"


class AnalysisLevel(str, Enum):
  NONE = "none"
  QUICK = "quick"
  DEEP = "deep"


class TransitionType(str, Enum):
  SMOOTH_BLEND = "smooth_blend"
  CUT = "cut"
  FILTER_SWEEP = "filter_sweep"
  ECHO_OUT = "echo_out"
  BASS_SWAP = "bass_swap"
  TAPE_STOP = "tape_stop"
  VINYL_BRAKE = "vinyl_brake"
  REVERSE_SWELL = "reverse_swell"
  IMPACT = "impact"
  CROSSFADE = "crossfade"  # legacy alias → smooth_blend

  @classmethod
  def parse(cls, value: str) -> "TransitionType":
    if value == "crossfade":
      return cls.SMOOTH_BLEND
    return cls(value)

  def normalized(self) -> "TransitionType":
    if self is TransitionType.CROSSFADE:
      return TransitionType.SMOOTH_BLEND
    return self


class TransitionCandidateKind(str, Enum):
  QUIET = "quiet"
  ENERGY_DROP = "energy_drop"
  OUTRO_START = "outro_start"


class ScanAction(str, Enum):
  ADDED = "added"
  UPDATED = "updated"
  UNCHANGED = "unchanged"
