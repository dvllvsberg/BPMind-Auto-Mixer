from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

RECIPE_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class MixRecipeMetadata:
  name: str | None = None
  track_play_ratio: float | None = None
  groove_weight: float | None = None
  crossfade_duration_sec: float | None = None
  session_length_tracks: int | None = None
  mix_settings_manual: bool | None = None
  saved_at: datetime | None = None
