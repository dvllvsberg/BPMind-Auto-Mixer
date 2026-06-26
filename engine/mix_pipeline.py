from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from engine.domain.enums import StartMode
from engine.domain.models import MixSession, Track
from engine.mix_generator.mix_generator import MixGenerator, MixGeneratorConfig
from engine.transitions.modes import TransitionMode
from engine.transitions.planner import TransitionPlanConfig, TransitionPlanner


def build_mix_session(
  tracks: list[Track],
  start_mode: StartMode,
  generator_config: MixGeneratorConfig,
  *,
  start_track_id: int | None = None,
  mix_seed: int | None = None,
  transition_mode: TransitionMode = TransitionMode.AUTO,
  transition_plan_config: TransitionPlanConfig | None = None,
) -> MixSession:
  generator = MixGenerator(generator_config)
  ordered = generator.generate(
    tracks,
    start_mode,
    start_track_id=start_track_id,
    seed=mix_seed,
  )

  tracks_by_id = {track.id: track for track in tracks if track.id is not None}
  plan_config = transition_plan_config or TransitionPlanConfig(
    mode=transition_mode,
    crossfade_duration_sec=generator_config.crossfade_duration_sec,
    seed=mix_seed if transition_mode is TransitionMode.RANDOM else None,
  )
  if plan_config.mode is not transition_mode:
    plan_config = replace(plan_config, mode=transition_mode)

  transitions = TransitionPlanner().plan(ordered, tracks_by_id, plan_config)

  return MixSession(
    tracks=ordered.tracks,
    transitions=transitions,
    start_mode=ordered.start_mode,
    created_at=ordered.created_at or datetime.now(),
  )
