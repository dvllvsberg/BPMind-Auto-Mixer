from __future__ import annotations

from engine.domain.enums import StartMode
from engine.library.library_profile import (
  BASE_CROSSFADE_SEC,
  BASE_GROOVE_WEIGHT,
  BASE_PLAY_RATIO,
  BASE_SESSION_LENGTH,
  LibraryProfile,
  format_profile_hint_for_mode,
  profile_tuning_for_mode,
)
from engine.mix_generator.mix_generator import MixGeneratorConfig


def uses_auto_mix_settings(settings: dict) -> bool:
  return not settings.get("mix_settings_manual", False)


def resolve_mix_config(
  settings: dict,
  profile: LibraryProfile | None,
  *,
  mode: StartMode = StartMode.PEAK,
) -> MixGeneratorConfig:
  if uses_auto_mix_settings(settings) and profile is not None:
    play_ratio, groove_weight = profile_tuning_for_mode(profile, mode)
    return MixGeneratorConfig(
      session_length=profile.session_length_tracks,
      crossfade_duration_sec=profile.crossfade_duration_sec,
      track_play_ratio=play_ratio,
      groove_weight=groove_weight,
    )

  return MixGeneratorConfig(
    session_length=int(settings.get("session_length_tracks", BASE_SESSION_LENGTH)),
    crossfade_duration_sec=float(settings.get("crossfade_duration_sec", BASE_CROSSFADE_SEC)),
    track_play_ratio=float(settings.get("track_play_ratio", BASE_PLAY_RATIO)),
    groove_weight=float(settings.get("groove_weight", BASE_GROOVE_WEIGHT)),
  )


def format_auto_profile_hint(profile: LibraryProfile, mode: StartMode) -> str:
  return format_profile_hint_for_mode(profile, mode)
