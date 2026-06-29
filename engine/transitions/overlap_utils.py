from __future__ import annotations

import numpy as np

OVERLAP_SR = 44100


def align_overlap(
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int]:
  if outgoing.ndim == 1:
    outgoing = outgoing.reshape(-1, 1)
  if incoming.ndim == 1:
    incoming = incoming.reshape(-1, 1)

  overlap = min(len(outgoing), len(incoming))
  if overlap <= 0:
    channels = outgoing.shape[1] if outgoing.size else incoming.shape[1]
    empty = np.zeros((0, channels), dtype=np.float32)
    return empty, empty, 0

  tail = outgoing[-overlap:].astype(np.float32, copy=False)
  head = incoming[:overlap].astype(np.float32, copy=False)
  return tail, head, overlap


def sec_to_frames(seconds: float, *, sr: int = OVERLAP_SR) -> int:
  return max(0, int(round(seconds * sr)))


def staged_tail_blend(
  outgoing_processed: np.ndarray,
  incoming_head: np.ndarray,
  *,
  incoming_blend_sec: float,
  incoming_fade_power: float = 0.72,
  outgoing_fade_power: float = 1.05,
  solo_incoming: np.ndarray | None = None,
) -> np.ndarray:
  """Сначала только outgoing (или solo_incoming поверх), в конце — crossfade с входящим."""
  from engine.transitions.lanes import render_staged_blend

  return render_staged_blend(
    outgoing_processed,
    incoming_head,
    incoming_blend_sec=incoming_blend_sec,
    incoming_fade_power=incoming_fade_power,
    outgoing_fade_power=outgoing_fade_power,
    solo_incoming=solo_incoming,
    pin_tail_to_incoming=False,
  ).as_overlap_chunk()


def blend_sec_for_overlap(overlap: int, *, min_sec: float, overlap_fraction: float) -> float:
  overlap_sec = overlap / OVERLAP_SR
  return max(min_sec, overlap_sec * overlap_fraction)


def dual_envelope_mix(
  outgoing: np.ndarray,
  incoming: np.ndarray,
  out_gain: np.ndarray,
  in_gain: np.ndarray,
) -> np.ndarray:
  """Покадровый mix; последний сэмпл incoming = incoming[-1] если in_gain[-1]==1."""
  if outgoing.ndim == 1:
    outgoing = outgoing.reshape(-1, 1)
  if incoming.ndim == 1:
    incoming = incoming.reshape(-1, 1)

  if out_gain.ndim == 1:
    out_gain = out_gain.reshape(-1, 1)
  if in_gain.ndim == 1:
    in_gain = in_gain.reshape(-1, 1)

  return (outgoing * out_gain + incoming * in_gain).astype(np.float32, copy=False)
