from __future__ import annotations

import numpy as np

from engine.domain.models import PlannedTransition
from engine.transitions.junction import (
  render_transition_junction_for_planned,
  write_junction_debug_wavs,
)
from engine.transitions.lanes import JunctionRender
from engine.transitions.playback_rules import (
  outgoing_tape_silence_sec,
  transition_is_solo_tail,
)
from engine.transitions.tape_stop import tape_motor_stop_outgoing


def _append_tape_silence(audio: np.ndarray, silence_sec: float) -> np.ndarray:
  from engine.transitions.tape_stop import TAPE_STOP_SR

  if silence_sec <= 0.0 or audio.size == 0:
    return audio
  channels = audio.shape[1] if audio.ndim > 1 else 1
  silence_frames = int(round(silence_sec * TAPE_STOP_SR))
  if silence_frames <= 0:
    return audio
  padding = np.zeros((silence_frames, channels), dtype=np.float32)
  return np.concatenate([audio, padding], axis=0)


def render_transition_overlap(
  transition: PlannedTransition,
  outgoing_tail: np.ndarray,
  incoming_head: np.ndarray,
) -> np.ndarray:
  return render_transition_overlap_junction(
    transition,
    outgoing_tail,
    incoming_head,
  ).as_overlap_chunk()


def render_transition_overlap_junction(
  transition: PlannedTransition,
  outgoing_tail: np.ndarray,
  incoming_head: np.ndarray,
) -> JunctionRender:
  """Полный multi-lane результат (для отладки и таймлайна)."""
  if transition_is_solo_tail(transition.type):
    if outgoing_tail.size == 0:
      channels = incoming_head.shape[1] if incoming_head.ndim > 1 else 1
      silence = np.zeros((0, channels), dtype=np.float32)
      padded = _append_tape_silence(silence, outgoing_tape_silence_sec(transition))
      return JunctionRender(padded)
    processed = tape_motor_stop_outgoing(outgoing_tail)
    padded = _append_tape_silence(processed, outgoing_tape_silence_sec(transition))
    return JunctionRender(padded.astype(np.float32, copy=False))

  return render_transition_junction_for_planned(transition, outgoing_tail, incoming_head)


__all__ = [
  "render_transition_overlap",
  "render_transition_overlap_junction",
  "write_junction_debug_wavs",
]
