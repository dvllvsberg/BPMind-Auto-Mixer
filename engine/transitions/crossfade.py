from __future__ import annotations

import numpy as np


def crossfade_segments(
  outgoing: np.ndarray,
  incoming: np.ndarray,
  *,
  incoming_delay: float = 1.0,
  outgoing_release: float = 1.0,
) -> np.ndarray:
  """Смешать хвост outgoing и начало incoming.

  incoming_delay < 1 — входящий заходит медленнее (эффект на уходящем слышен дольше).
  outgoing_release > 1 — уходящий гаснет быстрее.
  """
  if outgoing.ndim == 1:
    outgoing = outgoing.reshape(-1, 1)
  if incoming.ndim == 1:
    incoming = incoming.reshape(-1, 1)

  overlap = min(len(outgoing), len(incoming))
  if overlap == 0:
    return np.zeros((0, outgoing.shape[1]), dtype=np.float32)

  out_tail = outgoing[-overlap:]
  in_head = incoming[:overlap]

  ramp = np.linspace(0.0, 1.0, overlap, dtype=np.float32).reshape(-1, 1)
  fade_in = np.power(ramp, incoming_delay)
  fade_out = np.power(1.0 - ramp, outgoing_release)

  return (out_tail * fade_out + in_head * fade_in).astype(np.float32)


def resample_audio(audio: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
  if from_sr == to_sr:
    return audio
  if audio.size == 0:
    return audio

  import librosa

  if audio.ndim == 1:
    return librosa.resample(audio, orig_sr=from_sr, target_sr=to_sr).astype(np.float32)

  channels = [
    librosa.resample(audio[:, channel], orig_sr=from_sr, target_sr=to_sr)
    for channel in range(audio.shape[1])
  ]
  return np.stack(channels, axis=1).astype(np.float32)
