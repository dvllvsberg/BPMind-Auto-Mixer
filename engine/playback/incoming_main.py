from __future__ import annotations

from collections.abc import Callable

import numpy as np

from engine.analysis.intro_entry import intro_skip_sec
from engine.domain.models import PlannedTransition
from engine.playback.audio_loader import load_audio_segment
from engine.transitions.playback_rules import incoming_tape_spin_sec, transition_is_solo_tail
from engine.transitions.tape_stop import tape_motor_start_incoming


def _incoming_tape_intro_skip_sec(
  track_path: str,
  play_from_sec: float,
  prev_transition: PlannedTransition | None,
  *,
  enable_crossfade: bool,
  incoming_track_id: int,
) -> float:
  spin_sec = incoming_tape_spin_sec(
    prev_transition,
    enable_crossfade=enable_crossfade,
    incoming_track_id=incoming_track_id,
  )
  if spin_sec <= 0.0:
    return 0.0
  scan_sec = min(max(spin_sec * 4.0, 12.0), 60.0)
  return intro_skip_sec(track_path, play_from_sec, scan_sec=scan_sec)


def load_incoming_main_audio(
  track_path: str,
  start_sec: float,
  end_sec: float,
  prev_transition: PlannedTransition | None,
  *,
  enable_crossfade: bool,
  incoming_track_id: int,
  normalize_fn: Callable[[np.ndarray, int], np.ndarray],
) -> np.ndarray:
  if end_sec <= start_sec:
    return np.zeros((0, 2), dtype=np.float32)

  spin_sec = incoming_tape_spin_sec(
    prev_transition,
    enable_crossfade=enable_crossfade,
    incoming_track_id=incoming_track_id,
  )
  intro_skip = _incoming_tape_intro_skip_sec(
    track_path,
    start_sec,
    prev_transition,
    enable_crossfade=enable_crossfade,
    incoming_track_id=incoming_track_id,
  )
  effective_start = start_sec + intro_skip

  if spin_sec <= 0.0:
    audio, sr = load_audio_segment(track_path, effective_start, end_sec)
    return normalize_fn(audio, sr)

  spin_end = min(effective_start + spin_sec, end_sec)
  head, sr_head = load_audio_segment(track_path, effective_start, spin_end)
  head = normalize_fn(head, sr_head)
  if len(head) > 0:
    head = tape_motor_start_incoming(head)

  if spin_end >= end_sec - 1e-6:
    return head

  body, sr_body = load_audio_segment(track_path, spin_end, end_sec)
  body = normalize_fn(body, sr_body)
  if len(head) == 0:
    return body
  if len(body) == 0:
    return head
  return np.concatenate([head, body], axis=0)
