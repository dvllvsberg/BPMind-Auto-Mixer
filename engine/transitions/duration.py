from __future__ import annotations

import math
from dataclasses import dataclass

from engine.domain.enums import TransitionType
from engine.domain.models import MixSessionTrack, Track
from engine.transitions.context import TransitionContext

BEATS_PER_BAR = 4
DEFAULT_BPM = 120.0
MIN_MAIN_BODY_SEC = 30.0
MIN_MAIN_BODY_RATIO = 0.22
BAR_SNAP = 0.5


@dataclass(frozen=True)
class DurationPreset:
  min_bars: float
  target_bars: float
  max_bars: float
  max_cap_ratio: float = 1.0


_DURATION_PRESETS: dict[TransitionType, DurationPreset] = {
  TransitionType.SMOOTH_BLEND: DurationPreset(4.0, 8.0, 16.0, max_cap_ratio=1.0),
  TransitionType.FILTER_SWEEP: DurationPreset(3.0, 6.0, 10.0, max_cap_ratio=0.92),
  TransitionType.ECHO_OUT: DurationPreset(5.0, 8.0, 14.0, max_cap_ratio=1.0),
  TransitionType.BASS_SWAP: DurationPreset(3.0, 4.5, 6.0, max_cap_ratio=0.72),
  TransitionType.IMPACT: DurationPreset(1.5, 2.5, 3.5, max_cap_ratio=0.48),
  TransitionType.REVERSE_SWELL: DurationPreset(1.5, 2.5, 4.0, max_cap_ratio=0.38),
  TransitionType.TAPE_STOP: DurationPreset(4.0, 6.0, 10.0, max_cap_ratio=0.9),
  TransitionType.VINYL_BRAKE: DurationPreset(1.0, 1.5, 3.0, max_cap_ratio=0.4),
  TransitionType.NONE: DurationPreset(0.0, 0.0, 0.0, max_cap_ratio=0.0),
}


def bar_duration_sec(bpm: float) -> float:
  effective = bpm if bpm and bpm > 0 else DEFAULT_BPM
  return (60.0 / effective) * BEATS_PER_BAR


def _snap_bars(bars: float) -> float:
  if bars <= 0:
    return 0.0
  snapped = round(bars / BAR_SNAP) * BAR_SNAP
  return max(BAR_SNAP, snapped)


def _floor_snap_bars(bars: float) -> float:
  if bars <= 0:
    return 0.0
  return max(BAR_SNAP, math.floor(bars / BAR_SNAP) * BAR_SNAP)


def _effective_bpm(track_a: Track, track_b: Track) -> float:
  bpms = [value for value in (track_a.bpm, track_b.bpm) if value and value > 0]
  if not bpms:
    return DEFAULT_BPM
  return sum(bpms) / len(bpms)


def _available_fade_sec(
  item: MixSessionTrack,
  track: Track,
  *,
  play_until_sec: float,
) -> float:
  playable = max(0.0, play_until_sec - item.play_from_sec)
  if playable <= 0:
    return 0.0
  min_main = max(MIN_MAIN_BODY_SEC, playable * MIN_MAIN_BODY_RATIO)
  return max(0.0, playable - min_main)


def _context_target_bars(preset: DurationPreset, profile: TransitionType, ctx: TransitionContext) -> float:
  bars = preset.target_bars
  normalized = profile.normalized()

  if normalized is TransitionType.SMOOTH_BLEND:
    if ctx.bpm_close and ctx.groove_score >= 0.55:
      bars += 2.0
    elif ctx.delta_bpm >= 8.0:
      bars -= 1.5
  elif normalized is TransitionType.FILTER_SWEEP:
    if ctx.delta_bpm >= 6.0:
      bars += 1.0
    if ctx.loudness_delta >= 4.0:
      bars += 0.5
  elif normalized is TransitionType.ECHO_OUT:
    if ctx.has_quiet_outro:
      bars += 2.0
    if ctx.groove_score < 0.5:
      bars += 1.0
  elif normalized is TransitionType.BASS_SWAP:
    if ctx.bpm_close and ctx.groove_score >= 0.6:
      bars += 0.5
  elif normalized is TransitionType.IMPACT:
    if ctx.incoming_louder:
      bars += 0.5
  elif normalized is TransitionType.REVERSE_SWELL:
    if ctx.has_quiet_outro:
      bars += 1.5
  elif normalized is TransitionType.TAPE_STOP:
    if ctx.has_energy_drop_outro:
      bars += 1.0
    if ctx.bpm_close:
      bars -= 0.5
  elif normalized is TransitionType.VINYL_BRAKE:
    if ctx.delta_bpm >= 6.0:
      bars += 0.5

  return _snap_bars(max(preset.min_bars, min(preset.max_bars, bars)))


def get_duration_preset(profile: TransitionType) -> DurationPreset:
  normalized = profile.normalized()
  return _DURATION_PRESETS.get(normalized, _DURATION_PRESETS[TransitionType.SMOOTH_BLEND])


def compute_transition_duration_sec(
  profile: TransitionType,
  ctx: TransitionContext,
  *,
  outgoing_item: MixSessionTrack,
  outgoing_track: Track,
  play_until_sec: float,
  global_cap_sec: float,
  auto_duration: bool = True,
) -> float:
  normalized = profile.normalized()
  if normalized is TransitionType.NONE:
    return 0.0

  if not auto_duration:
    return max(0.0, global_cap_sec)

  preset = get_duration_preset(normalized)
  bpm = _effective_bpm(ctx.from_track, ctx.to_track)
  bar_sec = bar_duration_sec(bpm)
  target_bars = _context_target_bars(preset, normalized, ctx)
  target_bars = max(preset.min_bars, min(preset.max_bars, target_bars))

  max_bars = preset.max_bars
  if global_cap_sec > 0 and preset.max_cap_ratio > 0:
    cap_bars = (global_cap_sec * preset.max_cap_ratio) / bar_sec
    max_bars = min(max_bars, _floor_snap_bars(cap_bars))

  available = _available_fade_sec(outgoing_item, outgoing_track, play_until_sec=play_until_sec)
  if available > 0:
    max_bars = min(max_bars, _floor_snap_bars(available / bar_sec))

  if max_bars < BAR_SNAP:
    return 0.0

  target_bars = min(target_bars, max_bars)
  if target_bars < preset.min_bars:
    target_bars = min(max_bars, preset.min_bars)

  target_bars = _snap_bars(target_bars)
  target_bars = min(target_bars, max_bars)
  if target_bars < BAR_SNAP:
    return 0.0

  return round(target_bars * bar_sec, 2)
