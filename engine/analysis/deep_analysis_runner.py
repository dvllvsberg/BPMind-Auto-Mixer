from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from engine.analysis.deep_analyzer import DeepAnalysisResult, analyze_track_deep
from engine.database.repository import TrackRepository
from engine.domain.models import Track, TransitionCandidate


@dataclass
class DeepAnalysisBatchResult:
  total: int = 0
  analyzed: int = 0
  failed: int = 0
  errors: list[str] = field(default_factory=list)


class DeepAnalysisRunner:
  def __init__(self, repository: TrackRepository) -> None:
    self._repo = repository

  def run(
    self,
    *,
    force: bool = False,
    on_track_start: Callable[[Track, int, int], None] | None = None,
    on_track_done: Callable[[Track, DeepAnalysisResult | None, str | None], None] | None = None,
  ) -> DeepAnalysisBatchResult:
    tracks = self._repo.list_for_deep_analysis(include_analyzed=force)
    result = DeepAnalysisBatchResult(total=len(tracks))
    total = len(tracks)

    for index, track in enumerate(tracks, start=1):
      assert track.id is not None
      label = track.title or track.path

      if on_track_start:
        on_track_start(track, index, total)

      try:
        content_start = track.content_start_sec if track.content_start_sec is not None else 0.0
        content_end = track.content_end_sec if track.content_end_sec is not None else track.duration
        analysis = analyze_track_deep(
          track.path,
          content_start_sec=content_start,
          content_end_sec=content_end,
          duration=track.duration,
        )
        candidates = [
          TransitionCandidate(
            id=None,
            track_id=track.id,
            position_sec=candidate.position_sec,
            kind=candidate.kind,
            confidence=candidate.confidence,
          )
          for candidate in analysis.transition_candidates
        ]
        self._repo.save_deep_analysis(track.id, analysis.energy_map, candidates)
        result.analyzed += 1
        if on_track_done:
          on_track_done(track, analysis, None)
      except Exception as exc:
        result.failed += 1
        message = f"{label}: {exc}"
        result.errors.append(message)
        if on_track_done:
          on_track_done(track, None, message)

    return result
