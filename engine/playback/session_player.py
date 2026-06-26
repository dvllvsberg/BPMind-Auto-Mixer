from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum

import numpy as np
import sounddevice as sd

from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition, Track
from engine.playback.audio_loader import load_audio_segment
from engine.playback.timeline_plan import SessionTimeline, build_session_timeline
from engine.transitions.crossfade import crossfade_segments, resample_audio

OUTPUT_SR = 44100
OUTPUT_CHANNELS = 2
BLOCK_SIZE = 2048


class PlayerState(str, Enum):
  STOPPED = "stopped"
  PLAYING = "playing"
  PAUSED = "paused"


@dataclass(frozen=True)
class NowPlaying:
  index: int
  total: int
  track: Track
  session_item: MixSessionTrack


@dataclass(frozen=True)
class PlaybackStatus:
  session_position_sec: float
  session_duration_sec: float
  track_local_output_sec: float
  track_output_duration_sec: float
  volume: float


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


class SessionPlayer:
  def __init__(
    self,
    session: MixSession,
    tracks_by_id: dict[int, Track],
    *,
    enable_crossfade: bool = True,
  ) -> None:
    self._session = session
    self._tracks_by_id = tracks_by_id
    self._enable_crossfade = enable_crossfade
    self._transitions_by_from = {t.from_track_id: t for t in session.transitions}
    self._index = 0
    self._frame_position = 0
    self._state = PlayerState.STOPPED
    self._stop_requested = False
    self._skip_requested = False
    self._jump_requested: int | None = None
    self._seek_local_output_sec: float | None = None
    self._volume = 1.0
    self._session_position_sec = 0.0
    self._track_local_output_sec = 0.0
    self._timeline: SessionTimeline | None = None
    self._lock = threading.Lock()
    self._thread: threading.Thread | None = None
    self._preload_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bpmind-preload")

  @property
  def state(self) -> PlayerState:
    with self._lock:
      return self._state

  @property
  def current_index(self) -> int:
    with self._lock:
      return self._index

  @property
  def timeline(self) -> SessionTimeline | None:
    with self._lock:
      return self._timeline

  def playback_status(self) -> PlaybackStatus:
    with self._lock:
      total = self._timeline.total_duration_sec if self._timeline else 0.0
      track_output = 0.0
      if self._timeline and 0 <= self._index < len(self._timeline.tracks):
        track_output = self._timeline.tracks[self._index].output_duration_sec
      return PlaybackStatus(
        session_position_sec=self._session_position_sec,
        session_duration_sec=total,
        track_local_output_sec=self._track_local_output_sec,
        track_output_duration_sec=track_output,
        volume=self._volume,
      )

  def set_volume(self, volume: float) -> None:
    with self._lock:
      self._volume = max(0.0, min(1.0, volume))

  def seek_to_session(self, session_sec: float) -> bool:
    with self._lock:
      if self._timeline is None or self._state == PlayerState.STOPPED:
        return False
      location = self._timeline.locate(session_sec)
      self._jump_requested = location.track_index
      self._seek_local_output_sec = location.local_output_sec
      self._frame_position = 0
      self._skip_requested = True
      self._session_position_sec = max(0.0, min(session_sec, self._timeline.total_duration_sec))
      return True

  def now_playing(self) -> NowPlaying | None:
    with self._lock:
      if self._index < 0 or self._index >= len(self._session.tracks):
        return None
      item = self._session.tracks[self._index]
      track = self._tracks_by_id.get(item.track_id)
      if track is None:
        return None
      return NowPlaying(
        index=self._index + 1,
        total=len(self._session.tracks),
        track=track,
        session_item=item,
      )

  def play(self, *, start_index: int = 0) -> None:
    with self._lock:
      if self._state == PlayerState.PLAYING:
        return
      if self._state == PlayerState.PAUSED:
        self._state = PlayerState.PLAYING
        return
      self._stop_requested = False
      self._skip_requested = False
      self._jump_requested = None
      self._frame_position = 0
      if self._session.tracks:
        self._index = max(0, min(start_index, len(self._session.tracks) - 1))
      else:
        self._index = 0
      self._timeline = build_session_timeline(
        self._session,
        self._tracks_by_id,
        enable_crossfade=self._enable_crossfade,
      )
      self._session_position_sec = 0.0
      if self._timeline.tracks and start_index < len(self._timeline.tracks):
        self._session_position_sec = self._timeline.tracks[start_index].session_offset_sec
      self._track_local_output_sec = 0.0
      self._seek_local_output_sec = None
      self._state = PlayerState.PLAYING
      self._thread = threading.Thread(target=self._run, daemon=True)
      self._thread.start()

  def pause(self) -> None:
    with self._lock:
      if self._state == PlayerState.PLAYING:
        self._state = PlayerState.PAUSED

  def resume(self) -> None:
    with self._lock:
      if self._state == PlayerState.PAUSED:
        self._state = PlayerState.PLAYING

  def toggle_pause(self) -> PlayerState:
    with self._lock:
      if self._state == PlayerState.PLAYING:
        self._state = PlayerState.PAUSED
      elif self._state == PlayerState.PAUSED:
        self._state = PlayerState.PLAYING
      return self._state

  def stop(self) -> None:
    with self._lock:
      self._stop_requested = True
      self._state = PlayerState.STOPPED
    if self._thread and self._thread.is_alive():
      self._thread.join(timeout=2.0)
    with self._lock:
      self._thread = None

  def next_track(self) -> bool:
    with self._lock:
      if self._index + 1 >= len(self._session.tracks):
        self._stop_requested = True
        self._state = PlayerState.STOPPED
        return False
      self._skip_requested = True
      self._frame_position = 0
      return True

  def previous_track(self) -> bool:
    with self._lock:
      if self._index <= 0:
        self._frame_position = 0
        self._jump_requested = 0
        self._skip_requested = True
        return True
      self._jump_requested = self._index - 1
      self._frame_position = 0
      self._skip_requested = True
      return True

  def jump_to_track(self, index: int) -> bool:
    with self._lock:
      if index < 0 or index >= len(self._session.tracks):
        return False
      if self._state == PlayerState.STOPPED and self._thread is None:
        return False
      self._jump_requested = index
      self._frame_position = 0
      self._seek_local_output_sec = None
      self._skip_requested = True
      if self._timeline is not None and index < len(self._timeline.tracks):
        self._session_position_sec = self._timeline.tracks[index].session_offset_sec
        self._track_local_output_sec = 0.0
      return True

  def wait_until_finished(self) -> None:
    if self._thread and self._thread.is_alive():
      self._thread.join()

  def _transition_from(self, track_id: int) -> PlannedTransition | None:
    return self._transitions_by_from.get(track_id)

  def _effective_until(self, item: MixSessionTrack, track: Track) -> float | None:
    if item.play_until_sec is not None:
      return item.play_until_sec
    return track.duration

  def _run(self) -> None:
    try:
      with sd.OutputStream(
        samplerate=OUTPUT_SR,
        channels=OUTPUT_CHANNELS,
        dtype="float32",
        blocksize=BLOCK_SIZE,
      ) as stream:
        while True:
          with self._lock:
            if self._stop_requested:
              self._state = PlayerState.STOPPED
              return
            index = self._index

          if index >= len(self._session.tracks):
            with self._lock:
              self._state = PlayerState.STOPPED
            return

          item = self._session.tracks[index]
          track = self._tracks_by_id.get(item.track_id)
          if track is None:
            with self._lock:
              self._index += 1
              self._frame_position = 0
            continue

          with self._lock:
            skip_crossfade = self._skip_requested

          try:
            if not self._play_track_segment(index, item, track, stream, skip_crossfade=skip_crossfade):
              return
          except sd.PortAudioError:
            with self._lock:
              self._state = PlayerState.STOPPED
            raise
          except Exception:
            with self._lock:
              self._index += 1
              self._frame_position = 0
            continue

          with self._lock:
            if self._jump_requested is not None:
              self._index = self._jump_requested
              self._jump_requested = None
              self._skip_requested = False
            elif self._skip_requested:
              self._skip_requested = False
              if self._index + 1 < len(self._session.tracks):
                self._index += 1
              else:
                self._state = PlayerState.STOPPED
                return
            else:
              self._index += 1
            self._frame_position = 0
    finally:
      self._preload_executor.shutdown(wait=False, cancel_futures=True)

  def _build_crossfade_audio(
    self,
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

  def _play_track_segment(
    self,
    index: int,
    item: MixSessionTrack,
    track: Track,
    stream: sd.OutputStream,
    *,
    skip_crossfade: bool,
  ) -> bool:
    start_sec = item.play_from_sec

    if index > 0 and self._enable_crossfade and not skip_crossfade:
      prev_item = self._session.tracks[index - 1]
      prev_transition = self._transition_from(prev_item.track_id)
      if prev_transition and prev_transition.to_track_id == item.track_id:
        start_sec = item.play_from_sec + prev_transition.crossfade_duration_sec

    until_sec = self._effective_until(item, track)
    next_transition = self._transition_from(item.track_id) if index + 1 < len(self._session.tracks) else None
    fade_sec = next_transition.crossfade_duration_sec if next_transition and self._enable_crossfade else 0.0

    if skip_crossfade:
      fade_sec = 0.0

    main_end = until_sec
    if until_sec is not None and fade_sec > 0:
      main_end = max(start_sec, until_sec - fade_sec)

    main_duration = 0.0
    if main_end is not None and main_end > start_sec:
      main_duration = main_end - start_sec

    crossfade_future: Future[np.ndarray] | None = None
    if (
      next_transition
      and self._enable_crossfade
      and not skip_crossfade
      and index + 1 < len(self._session.tracks)
      and until_sec is not None
      and fade_sec > 0
    ):
      next_item = self._session.tracks[index + 1]
      next_track = self._tracks_by_id.get(next_item.track_id)
      if next_track is not None:
        crossfade_future = self._preload_executor.submit(
          self._build_crossfade_audio,
          track,
          next_track,
          main_end,
          until_sec,
          next_item.play_from_sec,
          fade_sec,
        )

    seek_local: float | None = None
    with self._lock:
      if self._seek_local_output_sec is not None:
        seek_local = self._seek_local_output_sec
        self._seek_local_output_sec = None

    if seek_local is not None and seek_local >= main_duration and crossfade_future is not None:
      mixed = crossfade_future.result()
      if len(mixed) > 0:
        cf_start = int(max(0.0, seek_local - main_duration) * OUTPUT_SR)
        if not self._play_audio(
          mixed,
          stream,
          output_offset_sec=main_duration,
          initial_frame=cf_start,
        ):
          return False
      return True

    if main_end is None or main_end > start_sec:
      main_audio, sr = load_audio_segment(track.path, start_sec, main_end)
      main_audio = _normalize_audio(main_audio, sr)
      if len(main_audio) > 0:
        initial_frame = 0
        if seek_local is not None:
          initial_frame = int(min(seek_local, main_duration) * OUTPUT_SR)
        if not self._play_audio(
          main_audio,
          stream,
          output_offset_sec=0.0,
          initial_frame=initial_frame,
        ):
          return False

    if crossfade_future is not None:
      mixed = crossfade_future.result()
      if len(mixed) > 0 and not self._play_audio(mixed, stream, output_offset_sec=main_duration):
        return False

    return True

  def _play_audio(
    self,
    audio: np.ndarray,
    stream: sd.OutputStream,
    *,
    output_offset_sec: float = 0.0,
    initial_frame: int = 0,
  ) -> bool:
    with self._lock:
      start_frame = initial_frame if initial_frame > 0 else self._frame_position
      self._frame_position = 0
      plan = None
      if self._timeline and 0 <= self._index < len(self._timeline.tracks):
        plan = self._timeline.tracks[self._index]

    if audio.ndim == 1:
      audio = audio.reshape(-1, 1)
    if audio.shape[1] == 1:
      audio = np.repeat(audio, 2, axis=1)

    position = start_frame

    while position < len(audio):
      with self._lock:
        if self._stop_requested:
          self._state = PlayerState.STOPPED
          return False
        if self._skip_requested:
          return True
        if self._state == PlayerState.PAUSED:
          self._frame_position = position
          time.sleep(0.05)
          continue
        volume = self._volume
        local_sec = output_offset_sec + (position / OUTPUT_SR)
        self._track_local_output_sec = local_sec
        if plan is not None:
          self._session_position_sec = plan.session_offset_sec + local_sec

      end = min(position + BLOCK_SIZE, len(audio))
      chunk = audio[position:end] * volume
      stream.write(chunk)
      position = end

    return True
