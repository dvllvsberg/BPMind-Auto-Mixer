from __future__ import annotations

from collections.abc import Callable

import numpy as np

from engine.transitions.dsp_utils import head_audible_entry_frame
from engine.transitions.overlap_utils import OVERLAP_SR, sec_to_frames

REVERSE_SWELL_SEC = 1.8
REVERSE_SWELL_MIX = 1.0
REVERSE_OUT_FADE_FRACTION = 0.28
# Dry forward хвост после reverse: head[1…] без crossfade-провала.
REVERSE_FORWARD_HANDOFF_SEC = 0.14
REVERSE_FORWARD_HANDOFF_MIN_FRACTION = 0.2
# Плавный rev→forward в конце body (закрывает ~30 ms «микрофриз»).
REVERSE_BODY_SEAM_SEC = 0.036
REVERSE_PIVOT_SKIP_FRAMES = 1


def reverse_body_seam_frames(*, body_len: int) -> int:
  seam = sec_to_frames(REVERSE_BODY_SEAM_SEC)
  return min(max(seam, 16), max(body_len - 8, 0))


def reverse_swell_frames(*, overlap: int, swell_sec: float = REVERSE_SWELL_SEC) -> int:
  return min(sec_to_frames(swell_sec), overlap)


def reverse_swell_start_frame(overlap: int, *, swell_sec: float = REVERSE_SWELL_SEC) -> int:
  swell_len = reverse_swell_frames(overlap=overlap, swell_sec=swell_sec)
  return max(0, overlap - swell_len)


def reverse_handoff_frames(*, swell_len: int) -> int:
  handoff = sec_to_frames(REVERSE_FORWARD_HANDOFF_SEC)
  min_glue = max(32, int(swell_len * REVERSE_FORWARD_HANDOFF_MIN_FRACTION))
  handoff = max(handoff, min_glue)
  return min(handoff, max(swell_len - 8, 0))


def reverse_skip_frames(*, overlap: int) -> int:
  swell_len = reverse_swell_frames(overlap=overlap)
  handoff = reverse_handoff_frames(swell_len=swell_len)
  body_len = max(0, swell_len - handoff)
  seam = reverse_body_seam_frames(body_len=body_len)
  return REVERSE_PIVOT_SKIP_FRAMES + seam + handoff


def reverse_forward_lead_frames(*, overlap: int) -> int:
  swell_len = reverse_swell_frames(overlap=overlap)
  handoff = reverse_handoff_frames(swell_len=swell_len)
  body_len = max(0, swell_len - handoff)
  return reverse_body_seam_frames(body_len=body_len)


def reverse_pivot_index(*, handoff_frames: int, head_len: int, seam_frames: int = 0) -> int:
  """Первый сэмпл main body после overlap."""
  return min(1 + seam_frames + handoff_frames, max(head_len - 1, 0))


def reverse_tail_index(*, handoff_frames: int, head_len: int) -> int:
  """Последний сэмпл forward-хвоста в overlap (head[handoff])."""
  return min(handoff_frames, max(head_len - 1, 0))


def reverse_pivot_skip_sec(*, handoff_frames: int = 0) -> float:
  return (REVERSE_PIVOT_SKIP_FRAMES + handoff_frames) / OVERLAP_SR


def reverse_pivot_skip_sec_for_overlap(*, overlap: int) -> float:
  return reverse_skip_frames(overlap=overlap) / OVERLAP_SR


def build_reverse_junction_gains(
  swell_len: int,
  *,
  handoff_frames: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
  """
  Junction: outgoing → reverse swell → forward handoff (head[1…]).
  """
  if swell_len <= 0:
    empty = np.zeros(0, dtype=np.float32)
    return empty, empty, empty

  t = np.linspace(0.0, 1.0, swell_len, dtype=np.float32)
  handoff = min(max(handoff_frames, 0), swell_len - 1)
  body_len = swell_len - handoff

  out_gain = np.ones(swell_len, dtype=np.float32)
  rev_gain = np.zeros(swell_len, dtype=np.float32)
  fwd_gain = np.zeros(swell_len, dtype=np.float32)

  if body_len > 0:
    body_t = t[:body_len]
    fade_start = 1.0 - float(REVERSE_OUT_FADE_FRACTION)
    out_blend = np.clip((body_t - fade_start) / max(REVERSE_OUT_FADE_FRACTION, 1e-6), 0.0, 1.0)
    out_phase = out_blend * (np.pi * 0.5)
    out_gain[:body_len] = np.where(body_t < fade_start, 1.0, np.cos(out_phase))

    rev_phase = np.clip(body_t / 0.42, 0.0, 1.0) * (np.pi * 0.5)
    rev_gain[:body_len] = np.sin(rev_phase) * REVERSE_SWELL_MIX

    seam = reverse_body_seam_frames(body_len=body_len)
    if seam > 0 and handoff > 0:
      seam_t = np.linspace(0.0, 1.0, seam, dtype=np.float32)
      rev_fade = np.cos(seam_t * (np.pi * 0.5)) ** 2
      fwd_rise = np.sin(seam_t * (np.pi * 0.5)) ** 2
      rev_gain[body_len - seam : body_len] *= rev_fade
      fwd_gain[body_len - seam : body_len] = fwd_rise

  if handoff > 0:
    out_gain[body_len:] = 0.0
    rev_gain[body_len:] = 0.0
    fwd_gain[body_len:] = 1.0

  return out_gain, rev_gain, fwd_gain


def build_reverse_full_gains(
  overlap: int,
  *,
  swell_sec: float = REVERSE_SWELL_SEC,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
  swell_len = reverse_swell_frames(overlap=overlap, swell_sec=swell_sec)
  swell_start = reverse_swell_start_frame(overlap, swell_sec=swell_sec)
  handoff = reverse_handoff_frames(swell_len=swell_len)

  full_out = np.ones(overlap, dtype=np.float32)
  full_rev = np.zeros(overlap, dtype=np.float32)
  full_fwd = np.zeros(overlap, dtype=np.float32)

  if swell_len <= 0:
    return full_out, full_rev, full_fwd, 0

  out_j, rev_j, fwd_j = build_reverse_junction_gains(swell_len, handoff_frames=handoff)
  full_out[swell_start:] = out_j
  full_rev[swell_start:] = rev_j
  full_fwd[swell_start:] = fwd_j

  return full_out, full_rev, full_fwd, handoff


def reverse_overlap_output_frames(
  *,
  play_from_sec: float,
  crossfade_duration_sec: float,
  outgoing_until_sec: float,
  output_sr: int = OVERLAP_SR,
) -> int:
  tail_frames, head_frames = reverse_overlap_tail_head_frames(
    play_from_sec=play_from_sec,
    crossfade_duration_sec=crossfade_duration_sec,
    outgoing_until_sec=outgoing_until_sec,
    output_sr=output_sr,
  )
  return max(0, min(tail_frames, head_frames))


def reverse_overlap_tail_head_frames(
  *,
  play_from_sec: float,
  crossfade_duration_sec: float,
  outgoing_until_sec: float,
  output_sr: int = OVERLAP_SR,
) -> tuple[int, int]:
  outgoing_main_end = outgoing_until_sec - crossfade_duration_sec
  tail = int(outgoing_until_sec * output_sr) - int(outgoing_main_end * output_sr)
  head = int((play_from_sec + crossfade_duration_sec) * output_sr) - int(play_from_sec * output_sr)
  return max(0, tail), max(0, head)


def _load_normalized_crossfade_head(
  track_path: str,
  play_from_sec: float,
  crossfade_duration_sec: float,
) -> np.ndarray:
  from engine.playback.audio_loader import load_audio_segment
  from engine.transitions.crossfade import resample_audio

  head, sr = load_audio_segment(track_path, play_from_sec, play_from_sec + crossfade_duration_sec)
  if len(head) == 0:
    return np.zeros((0, 2), dtype=np.float32)
  if head.ndim == 1:
    head = head.reshape(-1, 1)
  if sr != OVERLAP_SR:
    head = resample_audio(head, sr, OVERLAP_SR)
  if head.shape[1] == 1:
    head = np.repeat(head, 2, axis=1)
  return head.astype(np.float32, copy=False)


def reverse_effective_overlap_frames(
  *,
  play_from_sec: float,
  crossfade_duration_sec: float,
  outgoing_until_sec: float,
  track_path: str | None = None,
  head: np.ndarray | None = None,
) -> int:
  """Длина overlap-чанка после trim тихого префикса головы incoming."""
  tail_frames, head_frames = reverse_overlap_tail_head_frames(
    play_from_sec=play_from_sec,
    crossfade_duration_sec=crossfade_duration_sec,
    outgoing_until_sec=outgoing_until_sec,
  )
  nominal = max(0, min(tail_frames, head_frames))
  if track_path is None and head is None:
    return nominal

  if head is None:
    head = _load_normalized_crossfade_head(track_path, play_from_sec, crossfade_duration_sec)
  if len(head) == 0:
    return nominal

  entry = reverse_head_entry_frames(head)
  return min(tail_frames, max(0, len(head) - entry))


def reverse_head_entry_frames(head: np.ndarray) -> int:
  return head_audible_entry_frame(head)


def reverse_effective_skip_frames(*, overlap: int, head: np.ndarray) -> int:
  entry = reverse_head_entry_frames(head)
  trimmed_len = max(0, len(head) - entry)
  effective_overlap = min(overlap, trimmed_len) if trimmed_len > 0 else overlap
  return entry + reverse_skip_frames(overlap=effective_overlap)


def reverse_playback_skip_frames(
  *,
  track_path: str,
  play_from_sec: float,
  crossfade_duration_sec: float,
  overlap_frames: int,
) -> int:
  head = _load_normalized_crossfade_head(track_path, play_from_sec, crossfade_duration_sec)
  if len(head) == 0:
    return reverse_incoming_skip_frames(
      crossfade_duration_sec=crossfade_duration_sec,
      overlap_frames=overlap_frames,
    )
  return reverse_effective_skip_frames(overlap=overlap_frames, head=head)


def reverse_head_entry_frames_for_path(
  track_path: str,
  play_from_sec: float,
  crossfade_duration_sec: float,
  *,
  load_fn: Callable[..., tuple[np.ndarray, int]] | None = None,
  normalize_fn: Callable[[np.ndarray, int], np.ndarray] | None = None,
) -> int:
  if load_fn is None or normalize_fn is None:
    from engine.playback.audio_loader import load_audio_segment

    from engine.transitions.crossfade import resample_audio

    def _load(path: str, start: float, end: float) -> tuple[np.ndarray, int]:
      return load_audio_segment(path, start, end)

    def _norm(audio: np.ndarray, sr: int) -> np.ndarray:
      if audio.size == 0:
        return audio.astype(np.float32, copy=False)
      if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
      if sr != OVERLAP_SR:
        audio = resample_audio(audio, sr, OVERLAP_SR)
      if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
      return audio.astype(np.float32, copy=False)

    load_fn = _load
    normalize_fn = _norm

  head, sr = load_fn(track_path, play_from_sec, play_from_sec + crossfade_duration_sec)
  if len(head) == 0:
    return 0
  return reverse_head_entry_frames(normalize_fn(head, sr))


def reverse_incoming_skip_frames(
  *,
  crossfade_duration_sec: float,
  overlap_frames: int | None = None,
  head_entry_frames: int = 0,
) -> int:
  overlap = (
    overlap_frames
    if overlap_frames is not None
    else sec_to_frames(crossfade_duration_sec)
  )
  return head_entry_frames + reverse_skip_frames(overlap=overlap)


def reverse_incoming_skip_sec(*, crossfade_duration_sec: float) -> float:
  return reverse_incoming_skip_frames(crossfade_duration_sec=crossfade_duration_sec) / OVERLAP_SR


def reverse_main_skip_sec(*, overlap: int) -> float:
  return reverse_pivot_skip_sec_for_overlap(overlap=overlap)
