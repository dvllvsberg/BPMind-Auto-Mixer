from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np

from engine.domain.enums import TransitionCandidateKind
from engine.domain.models import EnergySegment, TransitionCandidate

SEGMENT_SEC = 4.0
TAIL_REGION_RATIO = 0.45
QUIET_BELOW_MEDIAN_DB = 5.0
ENERGY_DROP_DB = 4.0
OUTRO_ENERGY_RATIO = 0.72


@dataclass(frozen=True)
class DeepAnalysisResult:
  energy_map: list[EnergySegment]
  transition_candidates: list[TransitionCandidate]


def build_energy_map(
  y: np.ndarray,
  sr: int,
  content_start: float,
  content_end: float,
  *,
  segment_sec: float = SEGMENT_SEC,
) -> list[EnergySegment]:
  if content_end <= content_start:
    return []

  start_sample = int(content_start * sr)
  end_sample = max(start_sample + 1, int(content_end * sr))
  y_content = y[start_sample:end_sample]
  if len(y_content) == 0:
    return []

  hop = max(1, int(sr * 0.25))
  rms = librosa.feature.rms(y=y_content, hop_length=hop)[0]
  rms_db = librosa.amplitude_to_db(rms, ref=np.max(rms) if np.max(rms) > 0 else 1.0)
  onset_env = librosa.onset.onset_strength(y=y_content, sr=sr, hop_length=hop)
  onset_peak = float(np.max(onset_env)) if len(onset_env) else 0.0
  onset_db = librosa.amplitude_to_db(
    onset_env,
    ref=onset_peak if onset_peak > 0 else 1.0,
  )
  frame_sec = hop / sr

  segments: list[EnergySegment] = []
  cursor = 0.0
  content_len = content_end - content_start

  while cursor < content_len - 0.5:
    seg_end = min(cursor + segment_sec, content_len)
    start_frame = int(cursor / frame_sec)
    end_frame = max(start_frame + 1, int(seg_end / frame_sec))
    end_frame = min(end_frame, len(rms_db), len(onset_db))
    rms_part = float(np.mean(rms_db[start_frame:end_frame]))
    onset_part = float(np.mean(onset_db[start_frame:end_frame]))
    energy = 0.65 * rms_part + 0.35 * onset_part
    segments.append(
      EnergySegment(
        start_sec=round(content_start + cursor, 3),
        end_sec=round(content_start + seg_end, 3),
        energy=energy,
      )
    )
    cursor += segment_sec

  return segments


def find_transition_candidates(
  energy_map: list[EnergySegment],
  content_start: float,
  content_end: float,
) -> list[TransitionCandidate]:
  if len(energy_map) < 3:
    return []

  tail_start = content_start + (content_end - content_start) * (1.0 - TAIL_REGION_RATIO)
  tail_segments = [segment for segment in energy_map if segment.start_sec >= tail_start]
  if len(tail_segments) < 2:
    tail_segments = energy_map[-max(2, len(energy_map) // 3) :]

  energies = [segment.energy for segment in energy_map]
  median_energy = float(np.median(energies))
  peak_energy = float(np.max(energies))
  candidates: list[TransitionCandidate] = []

  for index, segment in enumerate(tail_segments):
    center = (segment.start_sec + segment.end_sec) / 2.0
    if segment.energy <= median_energy - QUIET_BELOW_MEDIAN_DB:
      confidence = min(1.0, (median_energy - segment.energy) / 12.0)
      candidates.append(
        TransitionCandidate(
          id=None,
          track_id=0,
          position_sec=round(center, 3),
          kind=TransitionCandidateKind.QUIET,
          confidence=confidence,
        )
      )

    if index > 0:
      prev = tail_segments[index - 1]
      drop = prev.energy - segment.energy
      if drop >= ENERGY_DROP_DB:
        boundary = prev.end_sec
        confidence = min(1.0, drop / 10.0)
        candidates.append(
          TransitionCandidate(
            id=None,
            track_id=0,
            position_sec=round(boundary, 3),
            kind=TransitionCandidateKind.ENERGY_DROP,
            confidence=confidence,
          )
        )

  rolling: list[float] = []
  outro_index: int | None = None
  for index, segment in enumerate(tail_segments):
    rolling.append(segment.energy)
    if len(rolling) > 3:
      rolling.pop(0)
    if len(rolling) < 3:
      continue
    if float(np.mean(rolling)) <= peak_energy - (1.0 - OUTRO_ENERGY_RATIO) * abs(peak_energy):
      outro_index = index
      break

  if outro_index is not None:
    segment = tail_segments[outro_index]
    candidates.append(
      TransitionCandidate(
        id=None,
        track_id=0,
        position_sec=round(segment.start_sec, 3),
        kind=TransitionCandidateKind.OUTRO_START,
        confidence=0.85,
      )
    )

  deduped: dict[tuple[str, int], TransitionCandidate] = {}
  for candidate in candidates:
    bucket = int(candidate.position_sec)
    key = (candidate.kind.value, bucket)
    existing = deduped.get(key)
    if existing is None or candidate.confidence > existing.confidence:
      deduped[key] = candidate

  return sorted(deduped.values(), key=lambda item: item.position_sec)


def analyze_track_deep(
  path: str | Path,
  *,
  content_start_sec: float = 0.0,
  content_end_sec: float | None = None,
  duration: float | None = None,
) -> DeepAnalysisResult:
  file_path = Path(path)
  if not file_path.is_file():
    raise FileNotFoundError(f"Файл не найден: {file_path}")

  y, sr = librosa.load(file_path, sr=None, mono=True)
  track_duration = duration if duration is not None else float(librosa.get_duration(y=y, sr=sr))
  content_end = content_end_sec if content_end_sec is not None else track_duration
  content_end = min(content_end, track_duration)
  content_start = max(0.0, min(content_start_sec, content_end))

  energy_map = build_energy_map(y, sr, content_start, content_end)
  candidates = find_transition_candidates(energy_map, content_start, content_end)
  return DeepAnalysisResult(energy_map=energy_map, transition_candidates=candidates)
