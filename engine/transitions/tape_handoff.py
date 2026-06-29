"""Смягчение провала на стыке tape stop → spin (без изменения длины)."""

from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import _ensure_2d

TAPE_HANDOFF_SR = 44100
# Окно вокруг стыка: подтянуть провал, если brake ушёл в ноль, а spin ещё тихий.
_HANDOFF_WINDOW_SEC = 0.14
_HANDOFF_DIP_RATIO = 0.22
_HANDOFF_TARGET_RATIO = 0.52


def soften_tape_boundary_dip(
  audio: np.ndarray,
  boundary_frame: int,
  *,
  sr: int = TAPE_HANDOFF_SR,
) -> np.ndarray:
  audio = _ensure_2d(audio).astype(np.float32, copy=True)
  if audio.size == 0 or boundary_frame <= 0 or boundary_frame >= len(audio):
    return audio

  window = int(round(_HANDOFF_WINDOW_SEC * sr))
  window = min(window, boundary_frame, len(audio) - boundary_frame)
  if window < 32:
    return audio

  lo = max(0, boundary_frame - window)
  hi = min(len(audio), boundary_frame + window)
  segment = audio[lo:hi]
  segment_peak = float(np.max(np.abs(segment)))
  if segment_peak < 1e-7:
    return audio

  span = max(16, window // 8)
  pre = audio[max(lo, boundary_frame - span) : boundary_frame]
  post = audio[boundary_frame : min(hi, boundary_frame + span)]
  if len(pre) == 0 or len(post) == 0:
    return audio

  seam_peak = max(float(np.max(np.abs(pre))), float(np.max(np.abs(post))))
  if seam_peak >= segment_peak * _HANDOFF_DIP_RATIO:
    return audio

  target = segment_peak * _HANDOFF_TARGET_RATIO
  gain = min(3.0, target / max(seam_peak, 1e-8))
  c_lo = max(lo, boundary_frame - span)
  c_hi = min(hi, boundary_frame + span)
  audio[c_lo:c_hi] *= gain
  return audio


def blend_tape_track_seam(outgoing_tail: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  """Сшивка brake→spin в live/export: короткий crossfade без изменения длины."""
  incoming = _ensure_2d(incoming).astype(np.float32, copy=True)
  outgoing_tail = _ensure_2d(outgoing_tail)
  if incoming.size == 0 or outgoing_tail.size == 0:
    return incoming

  overlap = int(round(_HANDOFF_WINDOW_SEC * TAPE_HANDOFF_SR))
  overlap = min(overlap, len(incoming), len(outgoing_tail))
  if overlap < 16:
    return incoming

  fade_out = np.linspace(1.0, 0.0, overlap, dtype=np.float32).reshape(-1, 1)
  fade_in = np.linspace(0.0, 1.0, overlap, dtype=np.float32).reshape(-1, 1)
  incoming[:overlap] = (
    outgoing_tail[-overlap:] * fade_out + incoming[:overlap] * fade_in
  ).astype(np.float32, copy=False)
  return soften_tape_boundary_dip(incoming, overlap // 2, sr=TAPE_HANDOFF_SR)


REVERSE_HANDOFF_WINDOW_SEC = 0.12


def blend_reverse_track_seam(overlap_tail: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  """Сшивка overlap reverse → main body B без микро-обрыва на стыке чанков."""
  incoming = _ensure_2d(incoming).astype(np.float32, copy=True)
  overlap_tail = _ensure_2d(overlap_tail)
  if incoming.size == 0 or overlap_tail.size == 0:
    return incoming

  weld = int(round(REVERSE_HANDOFF_WINDOW_SEC * TAPE_HANDOFF_SR))
  weld = min(weld, len(incoming), len(overlap_tail))
  if weld < 32:
    return incoming

  fade_out = np.linspace(1.0, 0.0, weld, dtype=np.float32).reshape(-1, 1)
  fade_in = np.linspace(0.0, 1.0, weld, dtype=np.float32).reshape(-1, 1)
  incoming[:weld] = (
    overlap_tail[-weld:] * fade_out + incoming[:weld] * fade_in
  ).astype(np.float32, copy=False)
  return soften_tape_boundary_dip(incoming, weld // 2, sr=TAPE_HANDOFF_SR)


def weld_reverse_export_boundary(
  audio: np.ndarray,
  boundary: int,
  *,
  sr: int = TAPE_HANDOFF_SR,
) -> np.ndarray:
  """Сшивка overlap reverse → main body B в экспорте (короткий crossfade на стыке чанков)."""
  audio = _ensure_2d(audio).astype(np.float32, copy=True)
  weld = int(round(REVERSE_HANDOFF_WINDOW_SEC * sr))
  weld = min(weld, boundary, len(audio) - boundary)
  if weld < 32:
    return audio

  tail_end = audio[boundary - weld : boundary]
  head_start = audio[boundary : boundary + weld]
  fade_out = np.linspace(1.0, 0.0, weld, dtype=np.float32).reshape(-1, 1)
  fade_in = np.linspace(0.0, 1.0, weld, dtype=np.float32).reshape(-1, 1)
  cross = (tail_end * fade_out + head_start * fade_in).astype(np.float32, copy=False)
  audio[boundary : boundary + weld] = cross
  return soften_tape_boundary_dip(audio, boundary, sr=sr)
