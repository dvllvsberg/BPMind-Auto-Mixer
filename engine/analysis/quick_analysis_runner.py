from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from engine.analysis.quick_analyzer import QuickAnalysisResult, analyze_track
from engine.database.repository import TrackRepository
from engine.domain.models import Track


@dataclass
class QuickAnalysisBatchResult:
  total: int = 0
  analyzed: int = 0
  skipped: int = 0
  failed: int = 0
  errors: list[str] = field(default_factory=list)


class QuickAnalysisRunner:
  def __init__(self, repository: TrackRepository) -> None:
    self._repo = repository

  def run(
    self,
    *,
    force: bool = False,
    on_track_start: Callable[[Track, int, int], None] | None = None,
    on_track_done: Callable[[Track, QuickAnalysisResult | None, str | None], None] | None = None,
  ) -> QuickAnalysisBatchResult:
    tracks = self._repo.list_for_quick_analysis(include_analyzed=force)
    result = QuickAnalysisBatchResult(total=len(tracks))
    total = len(tracks)

    for index, track in enumerate(tracks, start=1):
      assert track.id is not None
      label = track.title or track.path

      if on_track_start:
        on_track_start(track, index, total)

      try:
        analysis = analyze_track(track.path)
        self._repo.save_quick_analysis(
          track_id=track.id,
          duration=analysis.duration,
          bpm=analysis.bpm,
          loudness_avg=analysis.loudness_avg,
          loudness_peak=analysis.loudness_peak,
          content_start_sec=analysis.content_start_sec,
          content_end_sec=analysis.content_end_sec,
        )
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
