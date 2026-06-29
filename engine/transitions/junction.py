from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import soundfile as sf

from engine.domain.enums import TransitionType
from engine.domain.models import PlannedTransition
from engine.transitions.bass_swap import render_bass_swap_junction
from engine.transitions.crossfade import render_crossfade_junction
from engine.transitions.echo_out import render_echo_out_junction
from engine.transitions.filter_sweep import render_filter_sweep_junction
from engine.transitions.impact import render_impact_junction
from engine.transitions.lanes import JunctionRender
from engine.transitions.overlap_utils import OVERLAP_SR
from engine.transitions.reverse_swell import render_reverse_swell_junction
from engine.transitions.tape_stop import tape_stop_mix
from engine.transitions.vinyl_brake import render_vinyl_brake_junction

JunctionRenderer = Callable[[np.ndarray, np.ndarray], JunctionRender]

_JUNCTION_RENDERERS: dict[TransitionType, JunctionRenderer] = {
  TransitionType.SMOOTH_BLEND: render_crossfade_junction,
  TransitionType.CROSSFADE: render_crossfade_junction,
  TransitionType.FILTER_SWEEP: render_filter_sweep_junction,
  TransitionType.ECHO_OUT: render_echo_out_junction,
  TransitionType.BASS_SWAP: render_bass_swap_junction,
  TransitionType.VINYL_BRAKE: render_vinyl_brake_junction,
  TransitionType.REVERSE_SWELL: render_reverse_swell_junction,
  TransitionType.IMPACT: render_impact_junction,
}


def render_transition_junction(
  transition_type: TransitionType,
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> JunctionRender:
  kind = transition_type.normalized()

  if len(outgoing) == 0:
    return JunctionRender(incoming.astype(np.float32, copy=False))
  if len(incoming) == 0:
    if kind is TransitionType.TAPE_STOP:
      overlap = tape_stop_mix(outgoing, incoming)
      return JunctionRender(overlap.astype(np.float32, copy=False))
    return JunctionRender(outgoing.astype(np.float32, copy=False))

  if kind is TransitionType.NONE:
    audio = np.concatenate([outgoing, incoming], axis=0).astype(np.float32, copy=False)
    return JunctionRender(audio, incoming_main_skip_sec=0.0)

  if kind is TransitionType.TAPE_STOP:
    overlap = tape_stop_mix(outgoing, incoming)
    return JunctionRender(overlap.astype(np.float32, copy=False))

  handler = _JUNCTION_RENDERERS.get(kind)
  if handler is not None:
    return handler(outgoing, incoming)

  return render_crossfade_junction(outgoing, incoming)


def render_transition_junction_for_planned(
  transition: PlannedTransition,
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> JunctionRender:
  return render_transition_junction(transition.type, outgoing, incoming)


def write_junction_debug_wavs(
  render: JunctionRender,
  directory: Path,
  *,
  prefix: str = "junction",
  sr: int = OVERLAP_SR,
) -> list[Path]:
  """Экспорт mix и отдельных дорожек для отладки перехода."""
  directory.mkdir(parents=True, exist_ok=True)
  written: list[Path] = []

  mix_path = directory / f"{prefix}_mix.wav"
  sf.write(mix_path, render.overlap_audio, sr, subtype="PCM_16")
  written.append(mix_path)

  for label, audio in render.lane_outputs():
    safe_label = label.replace("/", "_")
    lane_path = directory / f"{prefix}_{safe_label}.wav"
    sf.write(lane_path, audio, sr, subtype="PCM_16")
    written.append(lane_path)

  return written
