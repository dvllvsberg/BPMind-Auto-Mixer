from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import soundfile as sf

from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition, Track
from engine.playback.audio_loader import load_audio_segment
from engine.playback.timeline_plan import build_session_timeline
from engine.transitions.crossfade import crossfade_segments, resample_audio

OUTPUT_SR = 44100
OUTPUT_CHANNELS = 2


class SessionExportError(Exception):
  pass


def _normalize_audio(audio: np.ndarray, sr: int, output_sr: int = OUTPUT_SR) -> np.ndarray:
  if audio.size == 0:
    return np.zeros((0, OUTPUT_CHANNELS), dtype=np.float32)

  if audio.ndim == 1:
    audio = audio.reshape(-1, 1)

  if sr != output_sr:
    audio = resample_audio(audio, sr, output_sr)

  if audio.shape[1] == 1:
    audio = np.repeat(audio, 2, axis=1)

  return audio.astype(np.float32, copy=False)


def _transition_map(session: MixSession) -> dict[int, PlannedTransition]:
  return {transition.from_track_id: transition for transition in session.transitions}


def _effective_until(item: MixSessionTrack, track: Track) -> float | None:
  if item.play_until_sec is not None:
    return item.play_until_sec
  return track.duration


def _build_crossfade_audio(
  outgoing_track: Track,
  incoming_track: Track,
  main_end: float,
  until_sec: float,
  incoming_from_sec: float,
  fade_sec: float,
) -> np.ndarray:
  tail, sr_tail = load_audio_segment(outgoing_track.path, main_end, until_sec)
  head, sr_head = load_audio_segment(incoming_track.path, incoming_from_sec, incoming_from_sec + fade_sec)

  if len(tail) == 0 or len(head) == 0:
    return np.zeros((0, OUTPUT_CHANNELS), dtype=np.float32)

  tail = _normalize_audio(tail, sr_tail)
  head = _normalize_audio(head, sr_head)
  return crossfade_segments(tail, head)


def _render_track_segment(
  index: int,
  session: MixSession,
  tracks_by_id: dict[int, Track],
  transitions_by_from: dict[int, PlannedTransition],
  *,
  enable_crossfade: bool,
) -> np.ndarray:
  item = session.tracks[index]
  track = tracks_by_id[item.track_id]

  start_sec = item.play_from_sec
  if index > 0 and enable_crossfade:
    prev_item = session.tracks[index - 1]
    prev_transition = transitions_by_from.get(prev_item.track_id)
    if prev_transition and prev_transition.to_track_id == item.track_id:
      start_sec = item.play_from_sec + prev_transition.crossfade_duration_sec

  until_sec = _effective_until(item, track)
  next_transition = transitions_by_from.get(item.track_id) if index + 1 < len(session.tracks) else None
  fade_sec = next_transition.crossfade_duration_sec if next_transition and enable_crossfade else 0.0

  main_end = until_sec
  if until_sec is not None and fade_sec > 0:
    main_end = max(start_sec, until_sec - fade_sec)

  parts: list[np.ndarray] = []

  if main_end is not None and main_end > start_sec:
    main_audio, sr = load_audio_segment(track.path, start_sec, main_end)
    main_audio = _normalize_audio(main_audio, sr)
    if len(main_audio) > 0:
      parts.append(main_audio)

  if (
    next_transition
    and enable_crossfade
    and index + 1 < len(session.tracks)
    and until_sec is not None
    and fade_sec > 0
  ):
    next_item = session.tracks[index + 1]
    next_track = tracks_by_id.get(next_item.track_id)
    if next_track is not None and main_end is not None:
      mixed = _build_crossfade_audio(
        track,
        next_track,
        main_end,
        until_sec,
        next_item.play_from_sec,
        fade_sec,
      )
      if len(mixed) > 0:
        parts.append(mixed)

  if not parts:
    return np.zeros((0, OUTPUT_CHANNELS), dtype=np.float32)

  return np.concatenate(parts, axis=0)


def render_session_audio(
  session: MixSession,
  tracks_by_id: dict[int, Track],
  *,
  enable_crossfade: bool = True,
  on_progress: Callable[[int, int, str], None] | None = None,
) -> np.ndarray:
  transitions_by_from = _transition_map(session)
  chunks: list[np.ndarray] = []
  total = len(session.tracks)

  for index in range(total):
    item = session.tracks[index]
    track = tracks_by_id.get(item.track_id)
    if track is None:
      raise SessionExportError(f"Трек id={item.track_id} не найден в библиотеке")

    if on_progress is not None:
      label = track.title or Path(track.path).stem
      on_progress(index + 1, total, label)

    chunk = _render_track_segment(
      index,
      session,
      tracks_by_id,
      transitions_by_from,
      enable_crossfade=enable_crossfade,
    )
    chunks.append(chunk)

  if not chunks:
    raise SessionExportError("В миксе нет треков для экспорта")

  return np.concatenate(chunks, axis=0)


def _validate_rendered_audio(
  session: MixSession,
  tracks_by_id: dict[int, Track],
  audio: np.ndarray,
  *,
  enable_crossfade: bool,
) -> None:
  if audio.size == 0:
    raise SessionExportError("Пустой результат рендера")

  timeline = build_session_timeline(session, tracks_by_id, enable_crossfade=enable_crossfade)
  expected_frames = int(round(timeline.total_duration_sec * OUTPUT_SR))
  if expected_frames > 0 and abs(len(audio) - expected_frames) > OUTPUT_SR:
    raise SessionExportError(
      "Длина рендера не совпадает с планом сета. "
      f"Ожидалось ~{timeline.total_duration_sec:.1f} с, получено {len(audio) / OUTPUT_SR:.1f} с."
    )


def _encode_mp3(audio: np.ndarray, *, bitrate_kbps: int = 320) -> bytes:
  try:
    import lameenc
  except ImportError as exc:
    raise SessionExportError(
      "MP3-экспорт недоступен: не установлен пакет lameenc. "
      "Выполните: pip install -r requirements.txt"
    ) from exc

  clipped = np.clip(audio, -1.0, 1.0)
  pcm = (clipped * 32767.0).astype(np.int16)
  interleaved = pcm.reshape(-1).tobytes()

  encoder = lameenc.Encoder()
  encoder.set_bit_rate(bitrate_kbps)
  encoder.set_in_sample_rate(OUTPUT_SR)
  encoder.set_channels(OUTPUT_CHANNELS)
  encoder.set_quality(2)
  return encoder.encode(interleaved) + encoder.flush()


def export_session_wav(
  session: MixSession,
  tracks_by_id: dict[int, Track],
  output_path: Path,
  *,
  enable_crossfade: bool = True,
  on_progress: Callable[[int, int, str], None] | None = None,
) -> float:
  audio = render_session_audio(
    session,
    tracks_by_id,
    enable_crossfade=enable_crossfade,
    on_progress=on_progress,
  )
  _validate_rendered_audio(session, tracks_by_id, audio, enable_crossfade=enable_crossfade)

  output_path.parent.mkdir(parents=True, exist_ok=True)
  sf.write(output_path, audio, OUTPUT_SR, subtype="PCM_16")
  return len(audio) / OUTPUT_SR


def export_session_mp3(
  session: MixSession,
  tracks_by_id: dict[int, Track],
  output_path: Path,
  *,
  enable_crossfade: bool = True,
  on_progress: Callable[[int, int, str], None] | None = None,
  bitrate_kbps: int = 320,
) -> float:
  audio = render_session_audio(
    session,
    tracks_by_id,
    enable_crossfade=enable_crossfade,
    on_progress=on_progress,
  )
  _validate_rendered_audio(session, tracks_by_id, audio, enable_crossfade=enable_crossfade)

  output_path.parent.mkdir(parents=True, exist_ok=True)
  output_path.write_bytes(_encode_mp3(audio, bitrate_kbps=bitrate_kbps))
  return len(audio) / OUTPUT_SR


def export_session(
  session: MixSession,
  tracks_by_id: dict[int, Track],
  output_path: Path,
  *,
  enable_crossfade: bool = True,
  on_progress: Callable[[int, int, str], None] | None = None,
  bitrate_kbps: int = 320,
) -> float:
  suffix = output_path.suffix.lower()
  if suffix == ".mp3":
    return export_session_mp3(
      session,
      tracks_by_id,
      output_path,
      enable_crossfade=enable_crossfade,
      on_progress=on_progress,
      bitrate_kbps=bitrate_kbps,
    )
  if suffix in (".wav", ".wave"):
    return export_session_wav(
      session,
      tracks_by_id,
      output_path,
      enable_crossfade=enable_crossfade,
      on_progress=on_progress,
    )
  raise SessionExportError(f"Неподдерживаемый формат экспорта: {suffix or '(без расширения)'}")
