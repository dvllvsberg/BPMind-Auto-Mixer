from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from engine.domain.enums import AnalysisLevel, StartMode, TransitionCandidateKind, TransitionType


@dataclass
class TransitionCandidate:
  id: int | None
  track_id: int
  position_sec: float
  kind: TransitionCandidateKind
  confidence: float = 1.0


@dataclass
class EnergySegment:
  start_sec: float
  end_sec: float
  energy: float


@dataclass
class Track:
  id: int | None
  path: str
  title: str
  artist: str
  duration: float | None
  file_size: int
  file_mtime: float
  bpm: float | None = None
  loudness_avg: float | None = None
  loudness_peak: float | None = None
  key: str | None = None
  content_start_sec: float | None = None
  content_end_sec: float | None = None
  analysis_level: AnalysisLevel = AnalysisLevel.NONE
  analyzed_at: datetime | None = None
  transition_candidates: list[TransitionCandidate] = field(default_factory=list)
  energy_map: list[EnergySegment] = field(default_factory=list)


@dataclass
class MixSessionTrack:
  track_id: int
  play_from_sec: float = 0.0
  play_until_sec: float | None = None


@dataclass
class PlannedTransition:
  from_track_id: int
  to_track_id: int
  type: TransitionType
  start_at_sec: float
  crossfade_duration_sec: float = 8.0


@dataclass
class MixSession:
  tracks: list[MixSessionTrack]
  transitions: list[PlannedTransition]
  start_mode: StartMode
  created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ScanResult:
  added: int = 0
  updated: int = 0
  unchanged: int = 0
  removed: int = 0
  total: int = 0
