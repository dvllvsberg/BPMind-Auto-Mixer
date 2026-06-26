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
  CROSSFADE = "crossfade"


class TransitionCandidateKind(str, Enum):
  QUIET = "quiet"
  ENERGY_DROP = "energy_drop"
  OUTRO_START = "outro_start"


class ScanAction(str, Enum):
  ADDED = "added"
  UPDATED = "updated"
  UNCHANGED = "unchanged"
