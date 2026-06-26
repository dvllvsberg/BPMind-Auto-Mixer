from __future__ import annotations

from enum import Enum


class TransitionMode(str, Enum):
  AUTO = "auto"
  FIXED = "fixed"
  RANDOM = "random"
