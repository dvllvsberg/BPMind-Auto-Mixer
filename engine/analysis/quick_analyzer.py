from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np

from engine.analysis.silence_detection import detect_content_bounds

HOP_LENGTH = 512
MIN_BPM = 55.0
MAX_BPM = 200.0


@dataclass(frozen=True)
class QuickAnalysisResult:
  duration: float
  bpm: float
  loudness_avg: float
  loudness_peak: float
  content_start_sec: float = 0.0
  content_end_sec: float | None = None


def _tempo_strength(onset_env: np.ndarray, sr: int, bpm: float) -> float:
  if bpm <= 0:
    return 0.0
  ac = librosa.autocorrelate(onset_env, max_size=len(onset_env))
  lag = int(round((60.0 / bpm) * sr / HOP_LENGTH))
  if lag < 1 or lag >= len(ac):
    return 0.0
  return float(ac[lag])


def _collect_tempo_candidates(*tempos: float) -> list[float]:
  candidates: set[float] = set()
  for tempo in tempos:
    if not np.isfinite(tempo) or tempo <= 0:
      continue
    for factor in (0.5, 1.0, 2.0):
      bpm = tempo * factor
      if MIN_BPM <= bpm <= MAX_BPM:
        candidates.add(bpm)
  return sorted(candidates)


def _resolve_half_time_ambiguity(scored: list[tuple[float, float]]) -> float:
  """Если 68 и 136 почти равны по score — предпочитаем медленнее (типично для hip-hop)."""
  scored = sorted(scored, key=lambda item: item[1], reverse=True)
  best_bpm, best_score = scored[0]

  for bpm, score in scored:
    if bpm >= best_bpm:
      continue
    ratio = best_bpm / bpm
    if 1.8 <= ratio <= 2.2 and score >= best_score * 0.72:
      return round(bpm, 1)

  return round(best_bpm, 1)


def estimate_bpm(y: np.ndarray, sr: int) -> float:
  y_perc = librosa.effects.hpss(y)[1]
  onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr, hop_length=HOP_LENGTH)

  tempo_bt, beats = librosa.beat.beat_track(
    y=y_perc,
    sr=sr,
    hop_length=HOP_LENGTH,
    onset_envelope=onset_env,
  )
  tempo_bt = float(np.asarray(tempo_bt).squeeze())

  tempo_med = float(
    np.asarray(
      librosa.feature.rhythm.tempo(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=HOP_LENGTH,
        aggregate=np.median,
      )
    ).squeeze()
  )

  beat_times = librosa.frames_to_time(beats, sr=sr, hop_length=HOP_LENGTH)
  tempo_intervals = tempo_bt
  if len(beat_times) >= 2:
    intervals = np.diff(beat_times)
    intervals = intervals[(intervals > 0.25) & (intervals < 2.5)]
    if len(intervals) > 0:
      tempo_intervals = 60.0 / float(np.median(intervals))

  candidates = _collect_tempo_candidates(tempo_bt, tempo_med, tempo_intervals)
  if not candidates:
    return round(float(np.clip(tempo_bt, MIN_BPM, MAX_BPM)), 1)

  scored = [(bpm, _tempo_strength(onset_env, sr, bpm)) for bpm in candidates]
  return _resolve_half_time_ambiguity(scored)


def analyze_track(path: str | Path) -> QuickAnalysisResult:
  file_path = Path(path)
  if not file_path.is_file():
    raise FileNotFoundError(f"Файл не найден: {file_path}")

  y, sr = librosa.load(file_path, sr=None, mono=True)
  duration = float(librosa.get_duration(y=y, sr=sr))
  bpm = estimate_bpm(y, sr)

  rms = librosa.feature.rms(y=y)[0]
  rms_db = librosa.amplitude_to_db(rms, ref=np.max)
  loudness_avg = float(np.mean(rms_db))

  peak = float(np.max(np.abs(y)))
  loudness_peak = float(librosa.amplitude_to_db(np.array([peak]), ref=1.0)[0])

  content_start, content_end = detect_content_bounds(y, sr)

  return QuickAnalysisResult(
    duration=duration,
    bpm=bpm,
    loudness_avg=loudness_avg,
    loudness_peak=loudness_peak,
    content_start_sec=content_start,
    content_end_sec=content_end,
  )
