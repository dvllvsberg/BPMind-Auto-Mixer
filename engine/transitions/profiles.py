from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from engine.domain.enums import TransitionType
from engine.transitions.context import TransitionContext, consecutive_smooth_count


@dataclass(frozen=True)
class TransitionProfile:
  type: TransitionType
  priority: int
  cooldown_lookback: int
  max_uses_in_lookback: int
  score: Callable[[TransitionContext], float]


def _smooth_streak_penalty(ctx: TransitionContext) -> float:
  streak = consecutive_smooth_count(ctx.recent_profiles)
  if streak >= 3:
    return 30.0
  if streak >= 2:
    return 18.0
  return 0.0


def _smooth_blend_score(ctx: TransitionContext) -> float:
  score = 28.0
  if ctx.delta_bpm <= 4.0:
    score += 12.0
  if ctx.groove_score >= 0.62:
    score += 22.0
  elif ctx.groove_score >= 0.52:
    score += 8.0
  else:
    score -= 8.0
  if ctx.loudness_delta <= 2.5:
    score += 8.0
  score -= _smooth_streak_penalty(ctx)
  return score


def _filter_sweep_score(ctx: TransitionContext) -> float:
  score = 24.0
  if ctx.delta_bpm >= 6.0:
    score += 14.0
  if ctx.delta_bpm <= 8.0 and ctx.has_groove_data and ctx.groove_score < 0.48:
    score += 26.0
  if ctx.loudness_delta >= 2.5:
    score += 16.0
  if ctx.loudness_delta >= 4.5:
    score += 10.0
  if not ctx.has_quiet_outro:
    score += 8.0
  if ctx.incoming_louder and ctx.bpm_close:
    score -= 14.0
  streak = consecutive_smooth_count(ctx.recent_profiles)
  if streak >= 2:
    score += 14.0
  if streak >= 3:
    score += 10.0
  return score


def _cut_score(ctx: TransitionContext) -> float:
  score = 12.0
  if ctx.delta_bpm >= 12.0:
    score += 18.0
  if ctx.groove_score < 0.38 and ctx.has_groove_data:
    score += 22.0
  if (
    ctx.has_groove_data
    and ctx.groove_score < 0.38
    and ctx.loudness_delta >= 3.5
  ):
    score += 14.0
  if (
    consecutive_smooth_count(ctx.recent_profiles) >= 3
    and ctx.has_groove_data
    and ctx.groove_score < 0.5
  ):
    score += 16.0
  return score


def _echo_out_score(ctx: TransitionContext) -> float:
  score = 14.0
  if ctx.loudness_delta >= 3.0:
    score += 18.0
  if ctx.delta_bpm >= 7.0:
    score += 12.0
  if ctx.has_quiet_outro:
    score += 10.0
  if ctx.groove_score < 0.5:
    score += 8.0
  if ctx.bpm_close and ctx.groove_score >= 0.55:
    score -= 14.0
  streak = consecutive_smooth_count(ctx.recent_profiles)
  if streak >= 2:
    score += 10.0
  return score


def _bass_swap_score(ctx: TransitionContext) -> float:
  score = 10.0
  if not ctx.has_groove_data:
    score -= 14.0
  if ctx.bpm_close:
    score += 24.0
  if ctx.groove_score >= 0.55:
    score += 20.0
  elif ctx.groove_score >= 0.48:
    score += 10.0
  if ctx.bpm_close and ctx.groove_score >= 0.62:
    score += 18.0
  if ctx.loudness_delta <= 3.5:
    score += 8.0
  if ctx.delta_bpm >= 8.0:
    score -= 18.0
  return score


def _impact_score(ctx: TransitionContext) -> float:
  score = 8.0
  if ctx.incoming_louder:
    score += 28.0
  if ctx.loudness_delta >= 4.0:
    score += 14.0
  if ctx.groove_score >= 0.5:
    score += 6.0
  if ctx.has_quiet_outro:
    score -= 10.0
  return score


def _tape_stop_score(ctx: TransitionContext) -> float:
  # Редкий «эффектный» переход: после провала энергии, при слабом groove. Не для chill quiet→quiet.
  score = 6.0
  if ctx.groove_score < 0.42 and ctx.has_groove_data:
    score += 20.0
  if ctx.has_energy_drop_outro:
    score += 16.0
  if consecutive_smooth_count(ctx.recent_profiles) >= 2:
    score += 12.0
  if ctx.bpm_close and ctx.groove_score >= 0.52:
    score -= 22.0
  if ctx.has_quiet_outro:
    score -= 8.0
  return score


def _vinyl_brake_score(ctx: TransitionContext) -> float:
  score = 5.0
  if ctx.groove_score < 0.48:
    score += 12.0
  if ctx.delta_bpm >= 5.0 and ctx.delta_bpm <= 10.0:
    score += 10.0
  if consecutive_smooth_count(ctx.recent_profiles) >= 1:
    score += 8.0
  if ctx.bpm_close and ctx.groove_score >= 0.55:
    score -= 16.0
  return score


def _reverse_swell_score(ctx: TransitionContext) -> float:
  score = 8.0
  if ctx.has_quiet_outro:
    score += 22.0
  if ctx.loudness_delta >= 3.5:
    score += 12.0
  if ctx.groove_score < 0.45:
    score += 8.0
  if ctx.incoming_louder and ctx.loudness_delta >= 5.0:
    score += 6.0
  return score


PROFILES_AUTO: tuple[TransitionProfile, ...] = (
  TransitionProfile(
    type=TransitionType.SMOOTH_BLEND,
    priority=10,
    cooldown_lookback=4,
    max_uses_in_lookback=3,
    score=_smooth_blend_score,
  ),
  TransitionProfile(
    type=TransitionType.FILTER_SWEEP,
    priority=20,
    cooldown_lookback=3,
    max_uses_in_lookback=1,
    score=_filter_sweep_score,
  ),
  TransitionProfile(
    type=TransitionType.ECHO_OUT,
    priority=25,
    cooldown_lookback=4,
    max_uses_in_lookback=1,
    score=_echo_out_score,
  ),
  TransitionProfile(
    type=TransitionType.BASS_SWAP,
    priority=22,
    cooldown_lookback=5,
    max_uses_in_lookback=1,
    score=_bass_swap_score,
  ),
  TransitionProfile(
    type=TransitionType.IMPACT,
    priority=24,
    cooldown_lookback=4,
    max_uses_in_lookback=1,
    score=_impact_score,
  ),
  TransitionProfile(
    type=TransitionType.REVERSE_SWELL,
    priority=26,
    cooldown_lookback=5,
    max_uses_in_lookback=1,
    score=_reverse_swell_score,
  ),
  TransitionProfile(
    type=TransitionType.TAPE_STOP,
    priority=28,
    cooldown_lookback=7,
    max_uses_in_lookback=1,
    score=_tape_stop_score,
  ),
  TransitionProfile(
    type=TransitionType.VINYL_BRAKE,
    priority=27,
    cooldown_lookback=6,
    max_uses_in_lookback=1,
    score=_vinyl_brake_score,
  ),
)

# cut — только CLI fixed/random; в авто не используется (топорный обрыв на 90% фрагмента)
PROFILES_DEBUG: tuple[TransitionProfile, ...] = PROFILES_AUTO + (
  TransitionProfile(
    type=TransitionType.CUT,
    priority=30,
    cooldown_lookback=4,
    max_uses_in_lookback=1,
    score=_cut_score,
  ),
)

PROFILES = PROFILES_DEBUG

_PROFILE_BY_TYPE = {profile.type: profile for profile in PROFILES}


def get_profile(transition_type: TransitionType) -> TransitionProfile:
  normalized = transition_type.normalized()
  profile = _PROFILE_BY_TYPE.get(normalized)
  if profile is None:
    raise KeyError(f"Unknown transition profile: {transition_type}")
  return profile


def score_profile(profile: TransitionProfile, ctx: TransitionContext, *, recent_uses: int) -> float:
  if recent_uses >= profile.max_uses_in_lookback:
    return float("-inf")
  return profile.score(ctx) + profile.priority * 0.01


def decide_profile(ctx: TransitionContext, *, recent_uses_by_type: dict[TransitionType, int]) -> TransitionType:
  best_type = TransitionType.SMOOTH_BLEND
  best_score = float("-inf")

  for profile in PROFILES_AUTO:
    uses = recent_uses_by_type.get(profile.type, 0)
    value = score_profile(profile, ctx, recent_uses=uses)
    if value > best_score:
      best_score = value
      best_type = profile.type

  return best_type
