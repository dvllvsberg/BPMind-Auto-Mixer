from __future__ import annotations

import random
from dataclasses import dataclass

from engine.domain.enums import TransitionType
from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition, Track
from engine.transitions.context import TransitionContext, build_transition_context
from engine.transitions.cooldown import CooldownTracker
from engine.transitions.duration import compute_transition_duration_sec
from engine.transitions.modes import TransitionMode
from engine.transitions.profiles import PROFILES_DEBUG, PROFILES_AUTO, decide_profile, get_profile


@dataclass(frozen=True)
class TransitionPlanConfig:
  mode: TransitionMode = TransitionMode.AUTO
  fixed_profile: TransitionType = TransitionType.SMOOTH_BLEND
  crossfade_duration_sec: float = 8.0
  auto_duration: bool = True
  seed: int | None = None


def _effective_until(item: MixSessionTrack, track: Track) -> float:
  if item.play_until_sec is not None:
    return item.play_until_sec
  return track.duration or item.play_from_sec


def _duration_for_transition(
  profile: TransitionType,
  ctx: TransitionContext,
  item_a: MixSessionTrack,
  track_a: Track,
  *,
  play_until_sec: float,
  config: TransitionPlanConfig,
) -> float:
  return compute_transition_duration_sec(
    profile,
    ctx,
    outgoing_item=item_a,
    outgoing_track=track_a,
    play_until_sec=play_until_sec,
    global_cap_sec=config.crossfade_duration_sec,
    auto_duration=config.auto_duration,
  )


class TransitionPlanner:
  def plan(
    self,
    session: MixSession,
    tracks_by_id: dict[int, Track],
    config: TransitionPlanConfig,
  ) -> list[PlannedTransition]:
    if len(session.tracks) < 2:
      return []

    cooldown = CooldownTracker()
    rng = random.Random(config.seed) if config.mode is TransitionMode.RANDOM else None
    transitions: list[PlannedTransition] = []

    for index in range(len(session.tracks) - 1):
      item_a = session.tracks[index]
      item_b = session.tracks[index + 1]
      track_a = tracks_by_id.get(item_a.track_id)
      track_b = tracks_by_id.get(item_b.track_id)
      if track_a is None or track_b is None:
        continue

      profile = self._pick_profile(
        track_a,
        track_b,
        config,
        cooldown,
        rng,
        step_index=index,
        total_steps=len(session.tracks) - 1,
      )
      start_at = _effective_until(item_a, track_a)
      ctx = build_transition_context(
        track_a,
        track_b,
        recent_profiles=cooldown.recent(),
        step_index=index,
        total_steps=len(session.tracks) - 1,
      )
      duration = _duration_for_transition(
        profile,
        ctx,
        item_a,
        track_a,
        play_until_sec=start_at,
        config=config,
      )

      transitions.append(
        PlannedTransition(
          from_track_id=item_a.track_id,
          to_track_id=item_b.track_id,
          type=profile,
          start_at_sec=start_at,
          crossfade_duration_sec=duration,
        )
      )
      cooldown.record(profile)

    return transitions

  def _pick_profile(
    self,
    track_a: Track,
    track_b: Track,
    config: TransitionPlanConfig,
    cooldown: CooldownTracker,
    rng: random.Random | None,
    *,
    step_index: int = 0,
    total_steps: int = 1,
  ) -> TransitionType:
    if config.mode is TransitionMode.NONE:
      return TransitionType.NONE

    if config.mode is TransitionMode.FIXED:
      return config.fixed_profile.normalized()

    if config.mode is TransitionMode.RANDOM:
      assert rng is not None
      return rng.choice([profile.type for profile in PROFILES_DEBUG])

    ctx = build_transition_context(
      track_a,
      track_b,
      recent_profiles=cooldown.recent(),
      step_index=step_index,
      total_steps=total_steps,
    )
    recent_uses = {
      profile.type: cooldown.uses_count(profile.type, lookback=profile.cooldown_lookback)
      for profile in PROFILES_AUTO
    }
    chosen = decide_profile(ctx, recent_uses_by_type=recent_uses)
    get_profile(chosen)
    return chosen
