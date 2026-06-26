from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from engine.domain.enums import AnalysisLevel, StartMode
from engine.domain.models import Track

# Калибровка на hip-hop библиотеке с узким BPM-кластером и deep-анализом.
CALM_PLAY_RATIO = 0.90
CALM_GROOVE_WEIGHT = 0.22
PEAK_PLAY_RATIO = 0.75
PEAK_GROOVE_WEIGHT = 0.35
WAVE_PLAY_RATIO = 0.82
WAVE_GROOVE_WEIGHT = 0.28
BASE_CROSSFADE_SEC = 8.0
BASE_SESSION_LENGTH = 12

BASE_PLAY_RATIO = PEAK_PLAY_RATIO
BASE_GROOVE_WEIGHT = PEAK_GROOVE_WEIGHT


@dataclass(frozen=True)
class LibraryProfile:
  track_count: int
  deep_track_count: int
  bpm_min: float | None
  bpm_max: float | None
  bpm_spread: float | None
  avg_playable_sec: float | None
  deep_coverage: float
  calm_track_play_ratio: float
  calm_groove_weight: float
  peak_track_play_ratio: float
  peak_groove_weight: float
  wave_track_play_ratio: float
  wave_groove_weight: float
  track_play_ratio: float
  groove_weight: float
  crossfade_duration_sec: float
  session_length_tracks: int
  computed_at: str
  summary_ru: str


def _playable_duration(track: Track) -> float | None:
  if track.duration is None:
    return None
  start = track.content_start_sec or 0.0
  end = track.content_end_sec if track.content_end_sec is not None else track.duration
  playable = end - start
  return playable if playable > 0 else None


def _avg_transition_position_ratio(tracks: list[Track]) -> float | None:
  ratios: list[float] = []
  for track in tracks:
    if not track.transition_candidates or track.duration is None or track.duration <= 0:
      continue
    best = max(track.transition_candidates, key=lambda item: item.confidence)
    ratios.append(best.position_sec / track.duration)
  if not ratios:
    return None
  return statistics.mean(ratios)


def _clamp(value: float, low: float, high: float) -> float:
  return max(low, min(high, value))


def profile_tuning_for_mode(profile: LibraryProfile, mode: StartMode) -> tuple[float, float]:
  if mode == StartMode.CALM:
    return profile.calm_track_play_ratio, profile.calm_groove_weight
  if mode == StartMode.PEAK:
    return profile.peak_track_play_ratio, profile.peak_groove_weight
  if mode == StartMode.WAVE:
    return profile.wave_track_play_ratio, profile.wave_groove_weight

  play = (profile.calm_track_play_ratio + profile.peak_track_play_ratio) / 2
  groove = (profile.calm_groove_weight + profile.peak_groove_weight) / 2
  return round(play, 2), round(groove, 2)


def _mode_label_ru(mode: StartMode) -> str:
  labels = {
    StartMode.CALM: "calm",
    StartMode.PEAK: "peak",
    StartMode.WAVE: "wave",
    StartMode.RANDOM: "random",
    StartMode.FROM_TRACK: "from_track",
  }
  return labels.get(mode, mode.value)


def compute_library_profile(tracks: list[Track]) -> LibraryProfile:
  mixable = [track for track in tracks if track.bpm is not None]
  count = len(mixable)
  deep_tracks = [track for track in mixable if track.analysis_level == AnalysisLevel.DEEP]
  deep_count = len(deep_tracks)
  deep_coverage = deep_count / count if count else 0.0

  bpms = [track.bpm for track in mixable if track.bpm is not None]
  bpm_min = min(bpms) if bpms else None
  bpm_max = max(bpms) if bpms else None
  bpm_spread = (bpm_max - bpm_min) if bpm_min is not None and bpm_max is not None else None

  playable = [value for track in mixable if (value := _playable_duration(track)) is not None]
  avg_playable = statistics.mean(playable) if playable else None

  calm_play = CALM_PLAY_RATIO
  calm_groove = CALM_GROOVE_WEIGHT
  peak_play = PEAK_PLAY_RATIO
  peak_groove = PEAK_GROOVE_WEIGHT
  wave_play = WAVE_PLAY_RATIO
  wave_groove = WAVE_GROOVE_WEIGHT
  crossfade = BASE_CROSSFADE_SEC

  if deep_coverage < 0.5:
    calm_play -= 0.08
    peak_play -= 0.05
    wave_play -= 0.06
    calm_groove = min(calm_groove, 0.18)
    peak_groove = min(peak_groove, 0.18)
    wave_groove = min(wave_groove, 0.18)
  elif deep_coverage < 0.8:
    calm_groove = round(calm_groove * 0.85, 2)
    peak_groove = round(peak_groove * 0.85, 2)
    wave_groove = round(wave_groove * 0.85, 2)

  if avg_playable is not None:
    if avg_playable < 150:
      calm_play -= 0.10
      peak_play -= 0.08
      wave_play -= 0.09
    elif avg_playable < 200:
      calm_play -= 0.04
      peak_play -= 0.04
      wave_play -= 0.04
    elif avg_playable > 280:
      calm_play = min(0.92, calm_play + 0.02)
      peak_play = min(0.82, peak_play + 0.04)
      wave_play = min(0.86, wave_play + 0.03)

  if bpm_spread is not None and bpm_spread > 15:
    peak_groove = 0.22
    peak_play = 0.72
    calm_groove = min(calm_groove, 0.22)

  transition_ratio = _avg_transition_position_ratio(deep_tracks)
  if transition_ratio is not None:
    if transition_ratio >= 0.72:
      calm_play = min(0.92, calm_play + 0.02)
      peak_play = min(0.82, peak_play + 0.03)
      wave_play = min(0.86, wave_play + 0.02)
    elif transition_ratio <= 0.55:
      calm_play = max(0.62, calm_play - 0.06)
      peak_play = max(0.58, peak_play - 0.05)
      wave_play = max(0.60, wave_play - 0.05)

  if bpms:
    bpm_mean = statistics.mean(bpms)
    crossfade = _clamp(BASE_CROSSFADE_SEC + (72.0 - bpm_mean) * 0.05, 6.0, 10.0)

  if count >= 2:
    session_length = min(max(2, count), 15)
    if count >= 8:
      session_length = min(count, 12)
  else:
    session_length = BASE_SESSION_LENGTH

  calm_play = round(_clamp(calm_play, 0.55, 0.92), 2)
  peak_play = round(_clamp(peak_play, 0.55, 0.85), 2)
  wave_play = round(_clamp(wave_play, 0.58, 0.88), 2)
  calm_groove = round(_clamp(calm_groove, 0.0, 0.35), 2)
  peak_groove = round(_clamp(peak_groove, 0.0, 0.35), 2)
  wave_groove = round(_clamp(wave_groove, 0.0, 0.35), 2)
  crossfade = round(crossfade * 2) / 2

  hints: list[str] = []
  if bpm_spread is not None and bpm_spread <= 10:
    hints.append("узкий BPM")
  if deep_coverage >= 0.8:
    hints.append("глубокий анализ")
  summary = "Подобрано под библиотеку"
  if hints:
    summary += f" ({', '.join(hints)})"

  return LibraryProfile(
    track_count=count,
    deep_track_count=deep_count,
    bpm_min=bpm_min,
    bpm_max=bpm_max,
    bpm_spread=bpm_spread,
    avg_playable_sec=round(avg_playable, 1) if avg_playable is not None else None,
    deep_coverage=round(deep_coverage, 2),
    calm_track_play_ratio=calm_play,
    calm_groove_weight=calm_groove,
    peak_track_play_ratio=peak_play,
    peak_groove_weight=peak_groove,
    wave_track_play_ratio=wave_play,
    wave_groove_weight=wave_groove,
    track_play_ratio=peak_play,
    groove_weight=peak_groove,
    crossfade_duration_sec=crossfade,
    session_length_tracks=session_length,
    computed_at=datetime.now().isoformat(timespec="seconds"),
    summary_ru=summary,
  )


def save_library_profile(profile: LibraryProfile, path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(asdict(profile), indent=2, ensure_ascii=False), encoding="utf-8")


def _migrate_profile_data(data: dict) -> dict:
  if "calm_track_play_ratio" not in data:
    data["calm_track_play_ratio"] = CALM_PLAY_RATIO
    data["calm_groove_weight"] = CALM_GROOVE_WEIGHT
    data["peak_track_play_ratio"] = data.get("track_play_ratio", PEAK_PLAY_RATIO)
    data["peak_groove_weight"] = data.get("groove_weight", PEAK_GROOVE_WEIGHT)
  if "wave_track_play_ratio" not in data:
    calm_play = data.get("calm_track_play_ratio", CALM_PLAY_RATIO)
    peak_play = data.get("peak_track_play_ratio", PEAK_PLAY_RATIO)
    calm_groove = data.get("calm_groove_weight", CALM_GROOVE_WEIGHT)
    peak_groove = data.get("peak_groove_weight", PEAK_GROOVE_WEIGHT)
    data["wave_track_play_ratio"] = round((calm_play + peak_play) / 2, 2)
    data["wave_groove_weight"] = round((calm_groove + peak_groove) / 2, 2)
  return data


def load_library_profile(path: Path) -> LibraryProfile | None:
  if not path.exists():
    return None
  data = _migrate_profile_data(json.loads(path.read_text(encoding="utf-8")))
  return LibraryProfile(**data)


def format_profile_hint_for_mode(profile: LibraryProfile, mode: StartMode) -> str:
  play_ratio, groove_weight = profile_tuning_for_mode(profile, mode)
  play_pct = int(play_ratio * 100)
  groove_pct = int(groove_weight * 100)
  return (
    f"{profile.summary_ru} [{_mode_label_ru(mode)}]: {profile.session_length_tracks} тр., "
    f"кроссфейд {profile.crossfade_duration_sec:g} с, "
    f"играть {play_pct}%, groove {groove_pct}%"
  )
