from __future__ import annotations

import random
from dataclasses import dataclass

from engine.domain.enums import StartMode
from engine.domain.models import MixSession, MixSessionTrack, Track
from engine.mix_generator.scoring import _track_energy, score_candidate
from engine.mix_generator.transition_points import planning_crossfade_sec, resolve_play_until
from engine.mix_generator.wave_energy import scoring_energy_weight, wave_target_energy


@dataclass(frozen=True)
class MixGeneratorConfig:
  session_length: int = 12
  crossfade_duration_sec: float = 8.0
  track_play_ratio: float = 0.75
  groove_weight: float = 0.35
  bpm_max_distance: float = 20.0
  full_track_playback: bool = False


class MixGeneratorError(Exception):
  pass


def _target_energy(step: int, total_steps: int, mode: StartMode) -> float | None:
  if total_steps <= 1 or mode == StartMode.RANDOM:
    return None

  progress = step / max(total_steps - 1, 1)

  if mode == StartMode.WAVE:
    return wave_target_energy(step, total_steps)

  if mode == StartMode.CALM:
    # спокойно → разгон → пик → спад
    if progress < 0.25:
      return -28.0 + progress * 4.0 * 8.0
    if progress < 0.55:
      return -20.0 + (progress - 0.25) / 0.3 * 10.0
    if progress < 0.8:
      return -10.0
    return -10.0 - (progress - 0.8) / 0.2 * 8.0

  if mode == StartMode.PEAK:
    if progress < 0.15:
      return -12.0
    if progress < 0.7:
      return -8.0
    return -8.0 - (progress - 0.7) / 0.3 * 10.0

  return None


def _pick_start_track(
  tracks: list[Track],
  mode: StartMode,
  *,
  start_track_id: int | None,
  rng: random.Random,
) -> Track:
  if start_track_id is not None:
    for track in tracks:
      if track.id == start_track_id:
        return track
    raise MixGeneratorError(f"Стартовый трек не найден: id={start_track_id}")

  if mode == StartMode.RANDOM:
    return rng.choice(tracks)

  if mode == StartMode.CALM:
    return min(tracks, key=_track_energy)

  if mode == StartMode.PEAK:
    return max(tracks, key=_track_energy)

  if mode == StartMode.WAVE:
    start_target = wave_target_energy(0, max(len(tracks), 2))
    return min(tracks, key=lambda track: abs(_track_energy(track) - start_target))

  if mode == StartMode.FROM_TRACK:
    raise MixGeneratorError("Для режима from_track укажите start_track_id")

  raise MixGeneratorError(f"Неизвестный режим: {mode}")


def _content_bounds(track: Track) -> tuple[float, float]:
  start = track.content_start_sec if track.content_start_sec is not None else 0.0
  end = track.content_end_sec if track.content_end_sec is not None else track.duration
  if end is None:
    end = track.duration or start
  return start, float(end)


def _default_play_until(track: Track, crossfade_duration: float, *, play_ratio: float) -> float | None:
  """Точка начала перехода внутри музыкальной части трека (без тишины в конце)."""
  return resolve_play_until(track, crossfade_duration, play_ratio=play_ratio)


class MixGenerator:
  def __init__(self, config: MixGeneratorConfig | None = None) -> None:
    self._config = config or MixGeneratorConfig()

  def generate(
    self,
    tracks: list[Track],
    start_mode: StartMode,
    *,
    start_track_id: int | None = None,
    seed: int | None = None,
  ) -> MixSession:
    eligible = [t for t in tracks if t.id is not None and t.bpm is not None]
    if not eligible:
      raise MixGeneratorError("Нет треков с BPM. Сначала выполните analyze.")

    rng = random.Random(seed)
    target_length = min(self._config.session_length, len(eligible))

    start = _pick_start_track(eligible, start_mode, start_track_id=start_track_id, rng=rng)

    ordered: list[Track] = [start]
    used_ids = {start.id}

    while len(ordered) < target_length:
      current = ordered[-1]
      pool = [t for t in eligible if t.id not in used_ids]
      if not pool:
        break

      step = len(ordered)
      target_energy = _target_energy(step, target_length, start_mode)
      energy_weight = scoring_energy_weight(start_mode)

      best = max(
        pool,
        key=lambda candidate: (
          score_candidate(
            current,
            candidate,
            target_energy=target_energy,
            energy_weight=energy_weight,
            groove_weight=self._config.groove_weight,
          ),
          rng.random(),
        ),
      )
      ordered.append(best)
      used_ids.add(best.id)

    session_tracks: list[MixSessionTrack] = []

    for index, track in enumerate(ordered):
      assert track.id is not None
      content_start, content_end = _content_bounds(track)
      if self._config.full_track_playback:
        play_until = round(content_end, 3)
      else:
        play_until = _default_play_until(
          track,
          planning_crossfade_sec(self._config.crossfade_duration_sec),
          play_ratio=self._config.track_play_ratio,
        )
      session_tracks.append(
        MixSessionTrack(
          track_id=track.id,
          play_from_sec=content_start,
          play_until_sec=play_until,
        )
      )

    return MixSession(
      tracks=session_tracks,
      transitions=[],
      start_mode=start_mode,
    )
