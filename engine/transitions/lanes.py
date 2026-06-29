from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.transitions.overlap_utils import OVERLAP_SR, align_overlap, sec_to_frames


@dataclass(frozen=True)
class JunctionLane:
  """Одна дорожка на стыке: аудио + покадровая огибающая той же длины."""

  audio: np.ndarray
  gain: np.ndarray

  @property
  def length(self) -> int:
    return len(self.audio)


@dataclass(frozen=True)
class JunctionRender:
  """
  Результат multi-lane рендера перехода.

  overlap_audio — микс всех дорожек на зоне overlap.
  incoming_main_skip_sec — сколько секунд головы входящего уже «съедено» в overlap
  (main body начинается с play_from + skip).
  lanes / lane_labels — для отладочного экспорта дорожек.
  """

  overlap_audio: np.ndarray
  incoming_main_skip_sec: float = 0.0
  lanes: tuple[JunctionLane, ...] = ()
  lane_labels: tuple[str, ...] = ()

  def as_overlap_chunk(self) -> np.ndarray:
    return self.overlap_audio

  def lane_outputs(self) -> list[tuple[str, np.ndarray]]:
    labels = self.lane_labels or tuple(f"lane_{index}" for index in range(len(self.lanes)))
    outputs: list[tuple[str, np.ndarray]] = []
    for label, lane in zip(labels, self.lanes):
      gain = _ensure_gain(lane.gain, lane.length)
      audio = _ensure_2d(lane.audio)
      outputs.append((label, (audio * gain).astype(np.float32, copy=False)))
    return outputs


def _ensure_2d(audio: np.ndarray) -> np.ndarray:
  if audio.ndim == 1:
    return audio.reshape(-1, 1)
  return audio


def _ensure_gain(gain: np.ndarray, length: int) -> np.ndarray:
  if gain.ndim == 1:
    gain = gain.reshape(-1, 1)
  if len(gain) != length:
    raise ValueError(f"gain length {len(gain)} != audio length {length}")
  return gain.astype(np.float32, copy=False)


def mix_lanes(lanes: list[JunctionLane]) -> np.ndarray:
  """Суммирует дорожки: sum(audio_i * gain_i). Пустой список → пустой буфер."""
  if not lanes:
    return np.zeros((0, 2), dtype=np.float32)

  length = lanes[0].length
  if length == 0:
    channels = lanes[0].audio.shape[1] if lanes[0].audio.ndim > 1 else 1
    return np.zeros((0, channels), dtype=np.float32)

  reference = _ensure_2d(lanes[0].audio)
  channels = reference.shape[1]
  mixed = np.zeros((length, channels), dtype=np.float32)

  for lane in lanes:
    audio = _ensure_2d(lane.audio)
    if len(audio) != length:
      raise ValueError("all lanes must have the same length")
    if audio.shape[1] != channels:
      raise ValueError("all lanes must have the same channel count")
    gain = _ensure_gain(lane.gain, length)
    mixed += audio * gain

  return mixed.astype(np.float32, copy=False)


def pin_overlap_tail(mixed: np.ndarray, sample: np.ndarray) -> np.ndarray:
  """Фиксирует последний сэмпл overlap для бесшовного стыка с main body."""
  if len(mixed) == 0:
    return mixed
  out = mixed.astype(np.float32, copy=True)
  out[-1] = np.asarray(sample, dtype=np.float32).reshape(-1)
  return out


def build_staged_gains(
  overlap: int,
  blend_frames: int,
  *,
  incoming_fade_power: float = 0.72,
  outgoing_fade_power: float = 1.05,
) -> tuple[np.ndarray, np.ndarray]:
  """Огибающие staged crossfade: сначала solo outgoing, в конце blend с incoming."""
  blend_frames = min(max(0, blend_frames), overlap)
  solo_frames = overlap - blend_frames

  out_gain = np.ones(overlap, dtype=np.float32)
  in_gain = np.zeros(overlap, dtype=np.float32)

  if blend_frames > 0:
    phase = np.linspace(0.0, np.pi, blend_frames, dtype=np.float32)
    in_gain[solo_frames:] = 0.5 * (1.0 - np.cos(phase))
    out_gain[solo_frames:] = 0.5 * (1.0 + np.cos(phase))

  return out_gain.reshape(-1, 1), in_gain.reshape(-1, 1)


def render_staged_blend(
  outgoing_processed: np.ndarray,
  incoming_head: np.ndarray,
  *,
  incoming_blend_sec: float,
  incoming_fade_power: float = 0.72,
  outgoing_fade_power: float = 1.05,
  solo_incoming: np.ndarray | None = None,
  pin_tail_to_incoming: bool = True,
) -> JunctionRender:
  """
  Две дорожки: processed outgoing + incoming head со staged огибающими.
  Эквивалент staged_tail_blend, но через multi-lane mix.
  """
  outgoing_processed = _ensure_2d(outgoing_processed)
  incoming_head = _ensure_2d(incoming_head)
  overlap = len(outgoing_processed)
  if overlap == 0:
    return JunctionRender(np.zeros((0, outgoing_processed.shape[1]), dtype=np.float32))

  blend_frames = min(sec_to_frames(incoming_blend_sec), overlap)
  solo_frames = max(0, overlap - blend_frames)

  outgoing_audio = outgoing_processed.astype(np.float32, copy=True)
  if solo_incoming is not None and solo_frames > 0:
    solo_slice = _ensure_2d(solo_incoming)[:solo_frames]
    if solo_slice.shape == outgoing_audio[:solo_frames].shape:
      outgoing_audio[:solo_frames] = (
        outgoing_audio[:solo_frames] * 0.55 + solo_slice * 0.45
      ).astype(np.float32, copy=False)

  out_gain, in_gain = build_staged_gains(
    overlap,
    blend_frames,
    incoming_fade_power=incoming_fade_power,
    outgoing_fade_power=outgoing_fade_power,
  )

  mixed = mix_lanes(
    [
      JunctionLane(outgoing_audio, out_gain),
      JunctionLane(incoming_head, in_gain),
    ]
  )

  if pin_tail_to_incoming and overlap > 0:
    mixed = pin_overlap_tail(mixed, incoming_head[-1])

  lanes = (
    JunctionLane(outgoing_audio, out_gain),
    JunctionLane(incoming_head, in_gain),
  )
  return JunctionRender(
    overlap_audio=mixed,
    incoming_main_skip_sec=overlap / OVERLAP_SR,
    lanes=lanes,
    lane_labels=("outgoing", "incoming"),
  )


def align_junction(
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int]:
  """Обёртка над align_overlap для единой точки входа multi-lane рендера."""
  return align_overlap(outgoing, incoming)


def empty_junction_render(channels: int = 2) -> JunctionRender:
  return JunctionRender(np.zeros((0, channels), dtype=np.float32))
