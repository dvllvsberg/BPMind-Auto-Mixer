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
from engine.playback.incoming_main import load_incoming_main_audio
from engine.playback.segment_envelope import apply_opening_track_main_envelope
from engine.playback.smart_skip import (
  can_smart_skip,
  smart_skip_fade_sec,
  smart_skip_tail_window,
)
from engine.playback.timeline_plan import SessionTimeline, TrackOutputPlan, build_session_timeline
from engine.transitions.crossfade import resample_audio
from engine.transitions.playback_rules import (
  incoming_play_start_sec,
  outgoing_tape_brake_sec,
  outgoing_tape_tail_sec,
  transition_is_reverse_overlay,
  transition_is_solo_tail,
)
from engine.transitions.reverse_swell_motor import (
  reverse_overlap_output_frames,
  reverse_playback_skip_frames,
)
from engine.transitions.render_overlap import render_transition_overlap
from engine.transitions.tape_handoff import blend_tape_track_seam

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
    self._smart_skip_requested = False
    self._jump_requested: int | None = None
    self._seek_local_output_sec: float | None = None
    self._volume = 1.0
    self._session_position_sec = 0.0
    self._track_local_output_sec = 0.0
    self._timeline: SessionTimeline | None = None
    self._lock = threading.Lock()
    self._thread: threading.Thread | None = None
    self._preload_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="bpmind-preload")
    self._handoff_consumed_index: int | None = None
    self._incoming_preload_index: int | None = None
    self._incoming_preload_future: Future[np.ndarray] | None = None
    self._incoming_preload_cache: dict[int, np.ndarray] = {}
    self._loop_session = False

  @property
  def loop_session(self) -> bool:
    with self._lock:
      return self._loop_session

  def set_loop_session(self, enabled: bool) -> None:
    with self._lock:
      self._loop_session = enabled

  def _restart_session_loop(self) -> None:
    self._index = 0
    self._frame_position = 0
    self._session_position_sec = 0.0
    self._track_local_output_sec = 0.0
    self._handoff_consumed_index = None
    self._clear_incoming_preload()
    if self._timeline is not None and self._timeline.tracks:
      self._session_position_sec = self._timeline.tracks[0].session_offset_sec

  @property
  def state(self) -> PlayerState:
    with self._lock:
      return self._state

  def _resolved_track_index(self) -> int:
    """Трек, соответствующий session_position_sec (актуален при continuous handoff)."""
    if self._state is PlayerState.STOPPED or self._timeline is None or not self._timeline.tracks:
      return self._index
    return self._timeline.locate(self._session_position_sec).track_index

  @property
  def current_index(self) -> int:
    with self._lock:
      return self._resolved_track_index()

  @property
  def timeline(self) -> SessionTimeline | None:
    with self._lock:
      return self._timeline

  def playback_status(self) -> PlaybackStatus:
    with self._lock:
      total = self._timeline.total_duration_sec if self._timeline else 0.0
      track_output = 0.0
      resolved = self._resolved_track_index()
      if self._timeline and 0 <= resolved < len(self._timeline.tracks):
        track_output = self._timeline.tracks[resolved].output_duration_sec
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
      self._handoff_consumed_index = None
      return True

  def now_playing(self) -> NowPlaying | None:
    with self._lock:
      index = self._resolved_track_index()
      if index < 0 or index >= len(self._session.tracks):
        return None
      item = self._session.tracks[index]
      track = self._tracks_by_id.get(item.track_id)
      if track is None:
        return None
      return NowPlaying(
        index=index + 1,
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
      self._handoff_consumed_index = None
      self._clear_incoming_preload()
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
      self._smart_skip_requested = True
      self._frame_position = 0
      return True

  def previous_track(self) -> bool:
    with self._lock:
      if self._index <= 0:
        self._frame_position = 0
        self._jump_requested = 0
        self._skip_requested = True
        self._smart_skip_requested = False
        return True
      self._jump_requested = self._index - 1
      self._frame_position = 0
      self._skip_requested = True
      self._smart_skip_requested = False
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
      self._clear_incoming_preload()
      self._handoff_consumed_index = None
      self._skip_requested = True
      self._smart_skip_requested = False
      if self._timeline is not None and index < len(self._timeline.tracks):
        self._session_position_sec = self._timeline.tracks[index].session_offset_sec
        self._track_local_output_sec = 0.0
      return True

  def wait_until_finished(self) -> None:
    if self._thread and self._thread.is_alive():
      self._thread.join()

  def _transition_from(self, track_id: int) -> PlannedTransition | None:
    return self._transitions_by_from.get(track_id)

  def _clear_incoming_preload(self) -> None:
    future = self._incoming_preload_future
    self._incoming_preload_index = None
    self._incoming_preload_future = None
    self._incoming_preload_cache.clear()
    if future is not None and not future.done():
      future.cancel()

  def _track_output_plan(self, index: int) -> TrackOutputPlan | None:
    with self._lock:
      timeline = self._timeline
    if timeline is None or index < 0 or index >= len(timeline.tracks):
      return None
    return timeline.tracks[index]

  def _warmup_futures(self, *futures: Future | None) -> None:
    for future in futures:
      if future is not None and not future.done():
        future.result()

  def _outgoing_transition_to_next(self, index: int, *, skip_crossfade: bool) -> PlannedTransition | None:
    if skip_crossfade or not self._enable_crossfade or index + 1 >= len(self._session.tracks):
      return None
    return self._transition_from(self._session.tracks[index].track_id)

  def _continuous_handoff_to_next(self, index: int, *, skip_crossfade: bool) -> bool:
    return self._outgoing_transition_to_next(index, skip_crossfade=skip_crossfade) is not None

  def _tape_handoff_to_next(self, index: int, *, skip_crossfade: bool) -> bool:
    next_transition = self._outgoing_transition_to_next(index, skip_crossfade=skip_crossfade)
    return next_transition is not None and transition_is_solo_tail(next_transition.type)

  def _ensure_incoming_preload_complete(self, index: int) -> None:
    cached = self._incoming_preload_cache.get(index)
    if cached is not None:
      return
    future = self._incoming_preload_future
    if future is None or self._incoming_preload_index != index:
      return
    self._incoming_preload_index = None
    self._incoming_preload_future = None
    try:
      self._incoming_preload_cache[index] = future.result()
    except Exception:
      pass

  def _build_incoming_main_for_index(self, index: int, *, skip_crossfade: bool) -> np.ndarray:
    item = self._session.tracks[index]
    track = self._tracks_by_id.get(item.track_id)
    if track is None:
      return np.zeros((0, OUTPUT_CHANNELS), dtype=np.float32)

    load_from_sec = item.play_from_sec
    output_skip_frames = 0
    prev_transition: PlannedTransition | None = None
    if index > 0 and self._enable_crossfade and not skip_crossfade:
      prev_item = self._session.tracks[index - 1]
      prev_transition = self._transition_from(prev_item.track_id)
      if prev_transition is not None and transition_is_reverse_overlay(prev_transition.type):
        prev_track = self._tracks_by_id.get(prev_item.track_id)
        prev_until = self._effective_until(prev_item, prev_track) if prev_track else None
        if prev_until is not None:
          overlap_frames = reverse_overlap_output_frames(
            play_from_sec=item.play_from_sec,
            crossfade_duration_sec=prev_transition.crossfade_duration_sec,
            outgoing_until_sec=prev_until,
          )
          output_skip_frames = reverse_playback_skip_frames(
            track_path=track.path,
            play_from_sec=item.play_from_sec,
            crossfade_duration_sec=prev_transition.crossfade_duration_sec,
            overlap_frames=overlap_frames,
          )
      else:
        load_from_sec = incoming_play_start_sec(
          item.play_from_sec,
          prev_transition,
          enable_crossfade=True,
          incoming_track_id=item.track_id,
        )
      start_sec = load_from_sec
    else:
      start_sec = item.play_from_sec

    until_sec = self._effective_until(item, track)
    next_transition = self._transition_from(item.track_id) if index + 1 < len(self._session.tracks) else None
    fade_sec = next_transition.crossfade_duration_sec if next_transition and self._enable_crossfade else 0.0
    if next_transition is not None and self._enable_crossfade and transition_is_solo_tail(next_transition.type):
      fade_sec = outgoing_tape_tail_sec(next_transition)
    if skip_crossfade:
      fade_sec = 0.0

    main_end = until_sec
    if until_sec is not None and fade_sec > 0:
      main_end = max(load_from_sec, until_sec - fade_sec)
    if main_end is None or main_end <= load_from_sec:
      return np.zeros((0, OUTPUT_CHANNELS), dtype=np.float32)

    audio = load_incoming_main_audio(
      track.path,
      load_from_sec,
      main_end,
      prev_transition,
      enable_crossfade=self._enable_crossfade and not skip_crossfade,
      incoming_track_id=item.track_id,
      normalize_fn=_normalize_audio,
      output_skip_frames=output_skip_frames,
    )
    if index == 0 and len(audio) > 0:
      has_next_transition = (
        next_transition is not None
        and self._enable_crossfade
        and not skip_crossfade
        and index + 1 < len(self._session.tracks)
        and fade_sec > 0
      )
      audio = apply_opening_track_main_envelope(
        audio,
        apply_fade_out=not has_next_transition,
      )
    return audio

  def _schedule_incoming_preload(self, index: int, *, skip_crossfade: bool) -> None:
    if skip_crossfade or not self._enable_crossfade:
      return
    if index + 1 >= len(self._session.tracks):
      return
    self._clear_incoming_preload()
    next_index = index + 1
    self._incoming_preload_index = next_index
    self._incoming_preload_future = self._preload_executor.submit(
      self._build_incoming_main_for_index,
      next_index,
      skip_crossfade=skip_crossfade,
    )

  def _load_incoming_main_for_index(self, index: int, *, skip_crossfade: bool) -> np.ndarray:
    cached = self._incoming_preload_cache.pop(index, None)
    if cached is not None:
      return cached
    future = self._incoming_preload_future
    if (
      not skip_crossfade
      and future is not None
      and self._incoming_preload_index == index
    ):
      self._incoming_preload_index = None
      self._incoming_preload_future = None
      try:
        return future.result()
      except Exception:
        pass
    return self._build_incoming_main_for_index(index, skip_crossfade=skip_crossfade)

  def _effective_until(self, item: MixSessionTrack, track: Track) -> float | None:
    if item.play_until_sec is not None:
      return item.play_until_sec
    return track.duration

  def _play_smart_skip_transition(self, index: int, stream: sd.OutputStream) -> bool:
    if index + 1 >= len(self._session.tracks):
      return False

    item = self._session.tracks[index]
    track = self._tracks_by_id.get(item.track_id)
    if track is None:
      return False

    transition = self._transition_from(item.track_id)
    if not can_smart_skip(transition, enable_crossfade=self._enable_crossfade):
      return False

    until_sec = self._effective_until(item, track)
    if until_sec is None:
      return False

    next_item = self._session.tracks[index + 1]
    next_track = self._tracks_by_id.get(next_item.track_id)
    if next_track is None:
      return False

    with self._lock:
      local_sec = self._track_local_output_sec

    fade_sec = smart_skip_fade_sec(transition)
    window = smart_skip_tail_window(item.play_from_sec, until_sec, local_sec, fade_sec)
    if window is None:
      return False

    tail_start, tail_end, effective_fade = window
    mixed = self._build_transition_audio(
      track,
      next_track,
      transition,
      tail_start,
      tail_end,
      next_item.play_from_sec,
      effective_fade,
    )
    if len(mixed) == 0:
      return False

    return self._play_audio(mixed, stream, output_offset_sec=local_sec)

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
              if self._loop_session:
                self._restart_session_loop()
                continue
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
            skip_crossfade = self._skip_requested and not self._smart_skip_requested

          seek_local: float | None = None
          with self._lock:
            if self._seek_local_output_sec is not None:
              seek_local = self._seek_local_output_sec
              self._seek_local_output_sec = None
              skip_crossfade = False

          try:
            if not self._play_track_segment(
              index,
              item,
              track,
              stream,
              skip_crossfade=skip_crossfade,
              seek_local=seek_local,
            ):
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

          skip_index: int | None = None
          smart_skip = False
          with self._lock:
            if self._jump_requested is not None:
              self._index = self._jump_requested
              self._jump_requested = None
              self._skip_requested = False
              self._clear_incoming_preload()
              self._handoff_consumed_index = None
              self._frame_position = 0
            elif self._skip_requested:
              smart_skip = self._smart_skip_requested
              skip_index = self._index
              self._skip_requested = False
              self._smart_skip_requested = False
              self._clear_incoming_preload()
              self._handoff_consumed_index = None
              self._frame_position = 0
            else:
              self._index += 1
              self._frame_position = 0

          if skip_index is not None:
            played_transition = False
            if (
              smart_skip
              and skip_index + 1 < len(self._session.tracks)
            ):
              played_transition = self._play_smart_skip_transition(skip_index, stream)
            with self._lock:
              if played_transition:
                self._handoff_consumed_index = skip_index + 1
              if skip_index + 1 < len(self._session.tracks):
                self._index = skip_index + 1
              elif self._loop_session:
                self._restart_session_loop()
              else:
                self._state = PlayerState.STOPPED
                return
              self._frame_position = 0
    finally:
      self._preload_executor.shutdown(wait=False, cancel_futures=True)

  def _build_transition_audio(
    self,
    outgoing_track: Track,
    incoming_track: Track,
    transition: PlannedTransition,
    main_end: float,
    until_sec: float,
    incoming_from_sec: float,
    fade_sec: float,
  ) -> np.ndarray:
    tail_end = until_sec
    if transition_is_solo_tail(transition.type):
      tail_end = main_end + outgoing_tape_brake_sec(transition)

    tail, sr_tail = load_audio_segment(outgoing_track.path, main_end, tail_end)

    if len(tail) == 0:
      return np.zeros((0, OUTPUT_CHANNELS), dtype=np.float32)

    tail = _normalize_audio(tail, sr_tail)

    if transition_is_solo_tail(transition.type):
      return render_transition_overlap(transition, tail, np.zeros((0, OUTPUT_CHANNELS), dtype=np.float32))

    head, sr_head = load_audio_segment(incoming_track.path, incoming_from_sec, incoming_from_sec + fade_sec)
    if len(head) == 0:
      return np.zeros((0, OUTPUT_CHANNELS), dtype=np.float32)

    head = _normalize_audio(head, sr_head)
    return render_transition_overlap(transition, tail, head)

  def _play_track_segment(
    self,
    index: int,
    item: MixSessionTrack,
    track: Track,
    stream: sd.OutputStream,
    *,
    skip_crossfade: bool,
    seek_local: float | None = None,
  ) -> bool:
    start_sec = item.play_from_sec
    prev_transition: PlannedTransition | None = None

    if index > 0 and self._enable_crossfade and not skip_crossfade:
      prev_item = self._session.tracks[index - 1]
      prev_transition = self._transition_from(prev_item.track_id)
      start_sec = incoming_play_start_sec(
        item.play_from_sec,
        prev_transition,
        enable_crossfade=True,
        incoming_track_id=item.track_id,
      )

    until_sec = self._effective_until(item, track)
    next_transition = self._transition_from(item.track_id) if index + 1 < len(self._session.tracks) else None
    fade_sec = next_transition.crossfade_duration_sec if next_transition and self._enable_crossfade else 0.0
    if next_transition is not None and self._enable_crossfade and transition_is_solo_tail(next_transition.type):
      fade_sec = outgoing_tape_tail_sec(next_transition)

    if skip_crossfade:
      fade_sec = 0.0

    main_end = until_sec
    if until_sec is not None and fade_sec > 0:
      main_end = max(start_sec, until_sec - fade_sec)

    plan = self._track_output_plan(index)
    if plan is not None and not skip_crossfade:
      main_duration = plan.main_duration_sec
      fade_sec = plan.crossfade_duration_sec
    else:
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
          self._build_transition_audio,
          track,
          next_track,
          next_transition,
          main_end,
          until_sec,
          next_item.play_from_sec,
          fade_sec,
        )
        self._schedule_incoming_preload(index, skip_crossfade=skip_crossfade)
    elif (
      not skip_crossfade
      and self._enable_crossfade
      and index + 1 < len(self._session.tracks)
      and main_end is not None
      and main_end > start_sec
    ):
      self._schedule_incoming_preload(index, skip_crossfade=skip_crossfade)

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
      skip_incoming_main = seek_local is None and self._handoff_consumed_index == index
      if skip_incoming_main:
        self._handoff_consumed_index = None
      if not skip_incoming_main:
        main_audio = self._load_incoming_main_for_index(index, skip_crossfade=skip_crossfade)
        if len(main_audio) > 0:
          initial_frame = 0
          if seek_local is not None:
            initial_frame = int(min(seek_local, main_duration) * OUTPUT_SR)
          warmup: list[Future | None] = [crossfade_future]
          if self._continuous_handoff_to_next(index, skip_crossfade=skip_crossfade):
            warmup.append(self._incoming_preload_future)
          if not self._play_audio(
            main_audio,
            stream,
            output_offset_sec=0.0,
            initial_frame=initial_frame,
            warmup_futures=tuple(warmup),
          ):
            return False
          with self._lock:
            if self._skip_requested:
              return True

    if crossfade_future is not None:
      with self._lock:
        if self._skip_requested:
          return True
      continuous_handoff = self._continuous_handoff_to_next(index, skip_crossfade=skip_crossfade)
      is_tape_handoff = self._tape_handoff_to_next(index, skip_crossfade=skip_crossfade)
      if continuous_handoff:
        self._ensure_incoming_preload_complete(index + 1)
      self._warmup_futures(crossfade_future)
      mixed = crossfade_future.result()
      incoming_audio: np.ndarray | None = None
      next_plan: TrackOutputPlan | None = None
      if continuous_handoff:
        incoming_audio = self._load_incoming_main_for_index(index + 1, skip_crossfade=skip_crossfade)
        next_plan = self._track_output_plan(index + 1)
      if len(mixed) > 0:
        handoff_tail: np.ndarray | None = None
        if is_tape_handoff:
          overlap = int(round(0.14 * OUTPUT_SR))
          if len(mixed) > overlap:
            handoff_tail = mixed[-overlap:].copy()
            mixed = mixed[:-overlap]
        if len(mixed) > 0 and not self._play_audio(mixed, stream, output_offset_sec=main_duration):
          return False
        if continuous_handoff and incoming_audio is not None and len(incoming_audio) > 0:
          if is_tape_handoff and handoff_tail is not None:
            incoming_audio = blend_tape_track_seam(handoff_tail, incoming_audio)
          if not self._play_audio(
            incoming_audio,
            stream,
            output_offset_sec=0.0,
            position_plan=next_plan,
          ):
            return False
          self._handoff_consumed_index = index + 1

    return True

  def _play_audio(
    self,
    audio: np.ndarray,
    stream: sd.OutputStream,
    *,
    output_offset_sec: float = 0.0,
    initial_frame: int = 0,
    position_plan: TrackOutputPlan | None = None,
    warmup_futures: tuple[Future | None, ...] = (),
  ) -> bool:
    with self._lock:
      start_frame = initial_frame if initial_frame > 0 else self._frame_position
      self._frame_position = 0
      plan = position_plan
      if plan is None and self._timeline and 0 <= self._index < len(self._timeline.tracks):
        plan = self._timeline.tracks[self._index]

    if audio.ndim == 1:
      audio = audio.reshape(-1, 1)
    if audio.shape[1] == 1:
      audio = np.repeat(audio, 2, axis=1)

    position = start_frame
    warmup_started = False
    warmup_frame = max(0, len(audio) - int(2.0 * OUTPUT_SR))

    while position < len(audio):
      if (
        not warmup_started
        and warmup_futures
        and position >= warmup_frame
      ):
        self._warmup_futures(*warmup_futures)
        warmup_started = True
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
