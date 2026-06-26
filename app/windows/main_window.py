from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
  QCheckBox,
  QComboBox,
  QDoubleSpinBox,
  QFileDialog,
  QGroupBox,
  QHBoxLayout,
  QInputDialog,
  QLabel,
  QLineEdit,
  QListWidget,
  QMessageBox,
  QProgressBar,
  QPushButton,
  QSlider,
  QSpinBox,
  QVBoxLayout,
  QWidget,
)

from app.mix_settings import format_auto_profile_hint, uses_auto_mix_settings
from app.paths import (
  default_db_path,
  default_library_profile_path,
  default_mix_path,
  exports_dir,
  load_settings,
  mixes_dir,
  save_settings,
)
from app.ui.timeline_widget import MixTimelineWidget, format_time
from app.workers import ExportAudioWorker, MixBuildWorker, ScanAnalyzeWorker, track_label
from engine.database.repository import TrackRepository
from engine.domain.enums import AnalysisLevel, StartMode
from engine.domain.models import MixSession, Track
from engine.library.library_profile import (
  compute_library_profile,
  load_library_profile,
  profile_tuning_for_mode,
  save_library_profile,
)
from engine.mix_generator.recipe_library import (
  recipe_file_stem,
  recipe_path_for_name,
  sanitize_recipe_name,
  validate_recipe_tracks,
)
from engine.mix_generator.recipe_metadata import MixRecipeMetadata
from engine.mix_generator.session_store import load_mix_recipe, load_mix_session, save_mix_recipe
from engine.playback.session_player import PlayerState, SessionPlayer
from engine.playback.timeline_plan import SessionTimeline, build_session_timeline


def _start_track_combo_label(track: Track, *, list_index: int) -> str:
  bpm = f"{track.bpm:.1f}" if track.bpm else "?"
  return f"{list_index}. {bpm} BPM  {track_label(track)}"


def _mix_list_label(track: Track, *, list_index: int) -> str:
  return _start_track_combo_label(track, list_index=list_index)


class MainWindow(QWidget):
  def __init__(self) -> None:
    super().__init__()
    self.setWindowTitle("BPMind Auto Mixer")
    self.setMinimumWidth(560)

    self._player: SessionPlayer | None = None
    self._tracks_by_id: dict[int, object] = {}
    self._mix_track_ids: list[int] = []
    self._scan_worker: ScanAnalyzeWorker | None = None
    self._mix_worker: MixBuildWorker | None = None
    self._export_worker: ExportAudioWorker | None = None
    self._ending_session = False
    self._session_timeline: SessionTimeline | None = None
    self._applying_profile = False

    settings = load_settings()
    saved_folder = settings.get("library_path", "")

    self._folder_edit = QLineEdit(saved_folder)
    self._folder_edit.setPlaceholderText("Папка с музыкой")
    self._folder_edit.setReadOnly(True)

    browse_btn = QPushButton("Выбрать папку")
    browse_btn.clicked.connect(self._choose_folder)

    self._force_analyze_cb = QCheckBox("Пересчитать анализ")
    self._force_analyze_cb.setToolTip("Как --force в CLI: переанализировать все треки")

    self._deep_analyze_cb = QCheckBox("Глубокий анализ")
    self._deep_analyze_cb.setToolTip("Энергия, точки перехода и groove-профиль для лучшего микса")

    self._scan_btn = QPushButton("Сканировать и анализировать")
    self._scan_btn.clicked.connect(self._start_scan_analyze)

    self._mode_combo = QComboBox()
    self._mode_combo.addItem("Спокойный (calm)", StartMode.CALM.value)
    self._mode_combo.addItem("Пик (peak)", StartMode.PEAK.value)
    self._mode_combo.addItem("Волна (wave)", StartMode.WAVE.value)
    self._mode_combo.addItem("Случайный (random)", StartMode.RANDOM.value)
    self._mode_combo.addItem("С трека (from_track)", StartMode.FROM_TRACK.value)
    self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

    self._start_track_combo = QComboBox()
    self._start_track_combo.setVisible(False)
    self._start_track_combo.setMinimumWidth(220)

    self._mix_btn = QPushButton("Построить микс")
    self._mix_btn.clicked.connect(self._start_build_mix)

    self._save_recipe_btn = QPushButton("Сохранить сет")
    self._save_recipe_btn.setToolTip("Сохранить текущий микс как рецепт (порядок, тайминги, параметры)")
    self._save_recipe_btn.clicked.connect(self._save_current_recipe)

    self._open_recipe_btn = QPushButton("Открыть сет")
    self._open_recipe_btn.setToolTip("Загрузить сохранённый рецепт и воспроизвести тот же микс")
    self._open_recipe_btn.clicked.connect(self._open_saved_recipe)

    self._export_audio_btn = QPushButton("Экспорт аудио")
    self._export_audio_btn.setToolTip("Сохранить микс в MP3 (320 kbps) или WAV (44.1 kHz, 16-bit)")
    self._export_audio_btn.clicked.connect(self._export_current_mix_audio)

    self._length_spin = QSpinBox()
    self._length_spin.setRange(2, 50)
    self._length_spin.setValue(int(settings.get("session_length_tracks", 12)))
    self._length_spin.setSuffix(" тр.")
    self._length_spin.valueChanged.connect(self._save_mix_settings)

    self._crossfade_spin = QDoubleSpinBox()
    self._crossfade_spin.setRange(2.0, 30.0)
    self._crossfade_spin.setSingleStep(0.5)
    self._crossfade_spin.setDecimals(1)
    self._crossfade_spin.setSuffix(" с")
    self._crossfade_spin.setValue(float(settings.get("crossfade_duration_sec", 8.0)))
    self._crossfade_spin.valueChanged.connect(self._save_mix_settings)

    play_ratio_pct = int(float(settings.get("track_play_ratio", 0.75)) * 100)
    self._play_ratio_slider = QSlider(Qt.Orientation.Horizontal)
    self._play_ratio_slider.setRange(50, 95)
    self._play_ratio_slider.setValue(play_ratio_pct)
    self._play_ratio_slider.setToolTip(
      "Минимальная доля трека перед переходом. "
      "Ниже — короче фрагменты, выше — длиннее. Deep-анализ может сдвинуть точку позже."
    )
    self._play_ratio_slider.valueChanged.connect(self._on_play_ratio_changed)
    self._play_ratio_label = QLabel(f"{play_ratio_pct}%")

    groove_pct = int(float(settings.get("groove_weight", 0.35)) * 100)
    self._groove_slider = QSlider(Qt.Orientation.Horizontal)
    self._groove_slider.setRange(0, 35)
    self._groove_slider.setValue(groove_pct)
    self._groove_slider.setToolTip(
      "Насколько сильно подбирать пары по groove (хвост → голова следующего трека). "
      "0 — только BPM и громкость."
    )
    self._groove_slider.valueChanged.connect(self._on_groove_changed)
    self._groove_label = QLabel(f"{groove_pct}%")

    self._auto_profile_label = QLabel("")
    self._auto_profile_label.setWordWrap(True)
    self._auto_profile_label.setStyleSheet("color: palette(mid);")

    self._advanced_btn = QPushButton("▸ Дополнительно")
    self._advanced_btn.setFlat(True)
    self._advanced_btn.setCheckable(True)
    self._advanced_btn.setChecked(bool(settings.get("advanced_settings_expanded", False)))
    self._advanced_btn.toggled.connect(self._on_advanced_toggled)

    self._reset_auto_btn = QPushButton("Сбросить к авто")
    self._reset_auto_btn.setToolTip("Вернуть параметры микса, подобранные под библиотеку")
    self._reset_auto_btn.clicked.connect(self._reset_to_auto_profile)

    self._advanced_panel = QWidget()

    self._progress = QProgressBar()
    self._progress.setVisible(False)

    self._status = QLabel("Готов к работе")
    self._status.setWordWrap(True)

    self._now_label = QLabel("Сейчас: —")
    self._now_label.setWordWrap(True)
    self._next_label = QLabel("Далее: —")
    self._next_label.setWordWrap(True)

    self._time_label = QLabel("0:00 / 0:00")
    self._timeline_widget = MixTimelineWidget()
    self._timeline_widget.seek_requested.connect(self._on_timeline_seek)

    self._volume_slider = QSlider(Qt.Orientation.Horizontal)
    self._volume_slider.setRange(0, 100)
    self._volume_slider.setValue(int(settings.get("playback_volume", 100)))
    self._volume_slider.setToolTip("Громкость воспроизведения")
    self._volume_slider.valueChanged.connect(self._on_volume_changed)

    self._mix_list = QListWidget()
    self._mix_list.setMinimumHeight(140)
    self._mix_list.setToolTip("Клик — перейти к треку (или начать с него, если плеер остановлен)")
    self._mix_list.itemClicked.connect(self._on_mix_track_clicked)

    self._play_btn = QPushButton("Play")
    self._pause_btn = QPushButton("Pause")
    self._next_btn = QPushButton("Next")
    self._prev_btn = QPushButton("Prev")
    self._stop_btn = QPushButton("Stop")

    self._play_btn.clicked.connect(self._play)
    self._pause_btn.clicked.connect(self._toggle_pause)
    self._next_btn.clicked.connect(self._next_track)
    self._prev_btn.clicked.connect(self._prev_track)
    self._stop_btn.clicked.connect(self._stop_playback)

    self._set_playback_enabled(False)

    folder_row = QHBoxLayout()
    folder_row.addWidget(self._folder_edit, stretch=1)
    folder_row.addWidget(browse_btn)

    scan_row = QHBoxLayout()
    scan_row.addWidget(self._scan_btn)
    scan_row.addWidget(self._force_analyze_cb)
    scan_row.addWidget(self._deep_analyze_cb)
    scan_row.addStretch()

    mix_row = QHBoxLayout()
    mix_row.addWidget(self._mode_combo)
    mix_row.addWidget(self._start_track_combo, stretch=1)
    mix_row.addWidget(self._mix_btn)
    mix_row.addWidget(self._save_recipe_btn)
    mix_row.addWidget(self._open_recipe_btn)
    mix_row.addWidget(self._export_audio_btn)

    settings_row = QHBoxLayout()
    settings_row.addWidget(QLabel("Длина сета:"))
    settings_row.addWidget(self._length_spin)
    settings_row.addSpacing(12)
    settings_row.addWidget(QLabel("Кроссфейд:"))
    settings_row.addWidget(self._crossfade_spin)
    settings_row.addStretch()

    play_ratio_row = QHBoxLayout()
    play_ratio_row.addWidget(QLabel("Играть трека:"))
    play_ratio_row.addWidget(self._play_ratio_slider, stretch=1)
    play_ratio_row.addWidget(self._play_ratio_label)

    groove_row = QHBoxLayout()
    groove_row.addWidget(QLabel("Groove / пары:"))
    groove_row.addWidget(self._groove_slider, stretch=1)
    groove_row.addWidget(self._groove_label)

    advanced_layout = QVBoxLayout(self._advanced_panel)
    advanced_layout.setContentsMargins(16, 0, 0, 0)
    advanced_layout.addLayout(settings_row)
    advanced_layout.addLayout(play_ratio_row)
    advanced_layout.addLayout(groove_row)
    reset_row = QHBoxLayout()
    reset_row.addWidget(self._reset_auto_btn)
    reset_row.addStretch()
    advanced_layout.addLayout(reset_row)

    self._advanced_panel.setVisible(self._advanced_btn.isChecked())
    self._on_advanced_toggled(self._advanced_btn.isChecked())

    transport_row = QHBoxLayout()
    transport_row.addWidget(self._play_btn)
    transport_row.addWidget(self._pause_btn)
    transport_row.addWidget(self._prev_btn)
    transport_row.addWidget(self._next_btn)
    transport_row.addWidget(self._stop_btn)

    playback_box = QGroupBox("Воспроизведение")
    playback_layout = QVBoxLayout(playback_box)
    playback_layout.addWidget(self._now_label)
    playback_layout.addWidget(self._next_label)
    playback_layout.addWidget(self._time_label)
    playback_layout.addWidget(self._timeline_widget)
    volume_row = QHBoxLayout()
    volume_row.addWidget(QLabel("Громкость"))
    volume_row.addWidget(self._volume_slider)
    playback_layout.addLayout(volume_row)
    playback_layout.addLayout(transport_row)

    mix_box = QGroupBox("Сет")
    mix_layout = QVBoxLayout(mix_box)
    mix_layout.addWidget(self._mix_list)

    layout = QVBoxLayout(self)
    layout.addLayout(folder_row)
    layout.addLayout(scan_row)
    layout.addLayout(mix_row)
    layout.addWidget(self._auto_profile_label)
    layout.addWidget(self._advanced_btn)
    layout.addWidget(self._advanced_panel)
    layout.addWidget(self._progress)
    layout.addWidget(self._status)
    layout.addWidget(mix_box)
    layout.addWidget(playback_box)

    self._ui_timer = QTimer(self)
    self._ui_timer.setInterval(400)
    self._ui_timer.timeout.connect(self._refresh_playback_ui)

    self._refresh_start_track_combo()
    self._reload_library_profile_ui()

    if default_mix_path().exists():
      self._load_mix_plan()
      self._status.setText("Найден сохранённый микс. Можно нажать Play.")

  def closeEvent(self, event) -> None:  # noqa: N802
    self._stop_playback()
    super().closeEvent(event)

  def _save_mix_settings(self) -> None:
    if self._applying_profile:
      return
    settings = load_settings()
    settings["session_length_tracks"] = self._length_spin.value()
    settings["crossfade_duration_sec"] = self._crossfade_spin.value()
    settings["track_play_ratio"] = self._play_ratio_slider.value() / 100.0
    settings["groove_weight"] = self._groove_slider.value() / 100.0
    settings["mix_settings_manual"] = True
    save_settings(settings)
    self._refresh_auto_profile_hint()

  def _on_play_ratio_changed(self, value: int) -> None:
    self._play_ratio_label.setText(f"{value}%")
    self._save_mix_settings()

  def _on_groove_changed(self, value: int) -> None:
    self._groove_label.setText(f"{value}%")
    self._save_mix_settings()

  def _on_advanced_toggled(self, expanded: bool) -> None:
    self._advanced_panel.setVisible(expanded)
    self._advanced_btn.setText("▾ Дополнительно" if expanded else "▸ Дополнительно")
    settings = load_settings()
    settings["advanced_settings_expanded"] = expanded
    save_settings(settings)

  def _current_library_profile(self):
    profile_path = default_library_profile_path()
    profile = load_library_profile(profile_path)
    if profile is not None:
      return profile
    if not default_db_path().exists():
      return None
    with TrackRepository(default_db_path()) as repo:
      mixable = repo.list_mixable()
    if not mixable:
      return None
    profile = compute_library_profile(mixable)
    save_library_profile(profile, profile_path)
    return profile

  def _apply_profile_to_controls(self, profile) -> None:
    mode = StartMode(self._mode_combo.currentData())
    play_ratio, groove_weight = profile_tuning_for_mode(profile, mode)
    self._applying_profile = True
    try:
      self._length_spin.blockSignals(True)
      self._crossfade_spin.blockSignals(True)
      self._play_ratio_slider.blockSignals(True)
      self._groove_slider.blockSignals(True)

      self._length_spin.setValue(profile.session_length_tracks)
      self._crossfade_spin.setValue(profile.crossfade_duration_sec)
      play_ratio_pct = int(play_ratio * 100)
      groove_pct = int(groove_weight * 100)
      self._play_ratio_slider.setValue(play_ratio_pct)
      self._groove_slider.setValue(groove_pct)
      self._play_ratio_label.setText(f"{play_ratio_pct}%")
      self._groove_label.setText(f"{groove_pct}%")
    finally:
      self._length_spin.blockSignals(False)
      self._crossfade_spin.blockSignals(False)
      self._play_ratio_slider.blockSignals(False)
      self._groove_slider.blockSignals(False)
      self._applying_profile = False

  def _refresh_auto_profile_hint(self) -> None:
    settings = load_settings()
    profile = self._current_library_profile()
    mode = StartMode(self._mode_combo.currentData())
    if profile is None:
      self._auto_profile_label.setText("Просканируйте библиотеку — параметры микса подстроятся автоматически.")
      self._reset_auto_btn.setEnabled(False)
      return

    self._reset_auto_btn.setEnabled(True)
    hint = format_auto_profile_hint(profile, mode)
    if uses_auto_mix_settings(settings):
      self._auto_profile_label.setText(hint)
    else:
      self._auto_profile_label.setText(f"Ручная настройка. Авто: {hint}")

  def _reload_library_profile_ui(self) -> None:
    settings = load_settings()
    profile = self._current_library_profile()
    if profile is not None and uses_auto_mix_settings(settings):
      self._apply_profile_to_controls(profile)
    self._refresh_auto_profile_hint()

  def _reset_to_auto_profile(self) -> None:
    profile = self._current_library_profile()
    if profile is None:
      QMessageBox.information(
        self,
        "BPMind",
        "Сначала просканируйте и проанализируйте библиотеку.",
      )
      return

    mode = StartMode(self._mode_combo.currentData())
    play_ratio, groove_weight = profile_tuning_for_mode(profile, mode)
    settings = load_settings()
    settings["mix_settings_manual"] = False
    settings["session_length_tracks"] = profile.session_length_tracks
    settings["crossfade_duration_sec"] = profile.crossfade_duration_sec
    settings["track_play_ratio"] = play_ratio
    settings["groove_weight"] = groove_weight
    save_settings(settings)
    self._apply_profile_to_controls(profile)
    self._refresh_auto_profile_hint()
    self._status.setText("Параметры микса сброшены к авто-профилю библиотеки.")

  def _set_mode_combo(self, mode: StartMode) -> None:
    index = self._mode_combo.findData(mode.value)
    if index < 0:
      return
    self._mode_combo.blockSignals(True)
    self._mode_combo.setCurrentIndex(index)
    self._mode_combo.blockSignals(False)
    self._start_track_combo.setVisible(mode == StartMode.FROM_TRACK)

  def _apply_recipe_metadata_to_ui(self, metadata: MixRecipeMetadata, session: MixSession) -> None:
    self._set_mode_combo(session.start_mode)
    self._applying_profile = True
    try:
      settings = load_settings()
      if metadata.mix_settings_manual is not None:
        settings["mix_settings_manual"] = metadata.mix_settings_manual
      if metadata.session_length_tracks is not None:
        settings["session_length_tracks"] = metadata.session_length_tracks
        self._length_spin.setValue(metadata.session_length_tracks)
      if metadata.crossfade_duration_sec is not None:
        settings["crossfade_duration_sec"] = metadata.crossfade_duration_sec
        self._crossfade_spin.setValue(metadata.crossfade_duration_sec)
      if metadata.track_play_ratio is not None:
        settings["track_play_ratio"] = metadata.track_play_ratio
        play_pct = int(metadata.track_play_ratio * 100)
        self._play_ratio_slider.setValue(play_pct)
        self._play_ratio_label.setText(f"{play_pct}%")
      if metadata.groove_weight is not None:
        settings["groove_weight"] = metadata.groove_weight
        groove_pct = int(metadata.groove_weight * 100)
        self._groove_slider.setValue(groove_pct)
        self._groove_label.setText(f"{groove_pct}%")
      save_settings(settings)
    finally:
      self._applying_profile = False
    self._refresh_auto_profile_hint()

  def _save_current_recipe(self) -> None:
    mix_path = default_mix_path()
    if not mix_path.exists():
      QMessageBox.warning(self, "BPMind", "Сначала постройте микс.")
      return

    session, metadata = load_mix_recipe(mix_path)
    default_name = metadata.name or f"{session.start_mode.value}"
    name, ok = QInputDialog.getText(
      self,
      "Сохранить сет",
      "Название:",
      text=default_name,
    )
    if not ok:
      return

    clean_name = sanitize_recipe_name(name)
    if not clean_name:
      QMessageBox.warning(self, "BPMind", "Укажите название сета.")
      return

    target_dir = mixes_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = recipe_path_for_name(clean_name, mixes_dir=target_dir)
    if target_path.exists():
      reply = QMessageBox.question(
        self,
        "BPMind",
        f"Сет «{clean_name}» уже существует. Перезаписать?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
      )
      if reply != QMessageBox.StandardButton.Yes:
        return

    recipe_metadata = MixRecipeMetadata(
      name=clean_name,
      track_play_ratio=metadata.track_play_ratio,
      groove_weight=metadata.groove_weight,
      crossfade_duration_sec=metadata.crossfade_duration_sec,
      session_length_tracks=metadata.session_length_tracks,
      mix_settings_manual=metadata.mix_settings_manual,
    )
    save_mix_recipe(session, target_path, metadata=recipe_metadata)
    self._status.setText(f"Сет сохранён: {target_path.name}")

  def _open_saved_recipe(self) -> None:
    start_dir = str(mixes_dir())
    if not mixes_dir().exists():
      mixes_dir().mkdir(parents=True, exist_ok=True)

    path, _ = QFileDialog.getOpenFileName(
      self,
      "Открыть сет",
      start_dir,
      "Рецепт микса (*.json)",
    )
    if not path:
      return

    recipe_path = Path(path)
    try:
      session, metadata = load_mix_recipe(recipe_path)
    except Exception as exc:
      QMessageBox.critical(self, "BPMind", f"Не удалось прочитать рецепт:\n{exc}")
      return

    if not default_db_path().exists():
      QMessageBox.warning(self, "BPMind", "База библиотеки не найдена. Сначала просканируйте папку.")
      return

    with TrackRepository(default_db_path()) as repo:
      problems = validate_recipe_tracks(session, repo)

    if problems:
      QMessageBox.warning(
        self,
        "BPMind",
        "Рецепт нельзя воспроизвести:\n\n" + "\n".join(f"• {item}" for item in problems[:8]),
      )
      return

    self._stop_playback()
    save_mix_recipe(session, default_mix_path(), metadata=metadata)
    self._apply_recipe_metadata_to_ui(metadata, session)
    self._load_mix_plan()

    label = metadata.name or recipe_path.stem
    self._status.setText(f"Открыт сет «{label}»: {len(session.tracks)} треков, режим {session.start_mode.value}.")

  def _suggested_export_path(self, *, extension: str = ".mp3") -> Path:
    exports_dir().mkdir(parents=True, exist_ok=True)
    if default_mix_path().exists():
      session, metadata = load_mix_recipe(default_mix_path())
      if metadata.name:
        return exports_dir() / f"{recipe_file_stem(metadata.name)}{extension}"
      return exports_dir() / f"bpmind_{session.start_mode.value}{extension}"
    return exports_dir() / f"bpmind_{datetime.now():%Y%m%d_%H%M}{extension}"

  def _export_current_mix_audio(self) -> None:
    if not default_mix_path().exists():
      QMessageBox.warning(self, "BPMind", "Сначала постройте или откройте микс.")
      return
    if self._export_worker and self._export_worker.isRunning():
      return

    suggested = str(self._suggested_export_path(extension=".mp3"))
    path, selected_filter = QFileDialog.getSaveFileName(
      self,
      "Экспорт аудио",
      suggested,
      "MP3 (*.mp3);;WAV (*.wav)",
      "MP3 (*.mp3)",
    )
    if not path:
      return
    lower = path.lower()
    if "wav" in selected_filter.lower():
      if not lower.endswith(".wav"):
        path += ".wav"
    elif not lower.endswith(".mp3") and not lower.endswith(".wav"):
      path += ".mp3"

    export_label = "MP3" if path.lower().endswith(".mp3") else "WAV"
    self._export_audio_btn.setEnabled(False)
    self._mix_btn.setEnabled(False)
    self._progress.setVisible(True)
    self._progress.setValue(0)
    self._status.setText(f"Экспорт {export_label}...")

    self._export_worker = ExportAudioWorker(Path(path))
    self._export_worker.progress.connect(self._on_export_progress)
    self._export_worker.finished_ok.connect(self._on_export_finished)
    self._export_worker.failed.connect(self._on_export_failed)
    self._export_worker.finished.connect(lambda: self._export_audio_btn.setEnabled(True))
    self._export_worker.finished.connect(lambda: self._mix_btn.setEnabled(True))
    self._export_worker.start()

  def _on_export_progress(self, index: int, total: int, label: str) -> None:
    self._progress.setMaximum(total)
    self._progress.setValue(index)
    short = label if len(label) <= 50 else label[:47] + "..."
    self._status.setText(f"Экспорт [{index}/{total}]: {short}")

  def _on_export_finished(self, path: str, duration_sec: float) -> None:
    self._progress.setVisible(False)
    minutes = duration_sec / 60.0
    ext = Path(path).suffix.lower().lstrip(".") or "audio"
    self._status.setText(f"{ext.upper()} готов: {Path(path).name} ({minutes:.1f} мин)")
    QMessageBox.information(
      self,
      "BPMind",
      f"Микс экспортирован ({ext.upper()}):\n{path}\n\nДлительность: {minutes:.1f} мин",
    )

  def _on_export_failed(self, message: str) -> None:
    self._progress.setVisible(False)
    self._status.setText(message)
    QMessageBox.critical(self, "BPMind", message)

  def _on_volume_changed(self, value: int) -> None:
    settings = load_settings()
    settings["playback_volume"] = value
    save_settings(settings)
    if self._player is not None:
      self._player.set_volume(value / 100.0)

  def _apply_player_volume(self) -> None:
    if self._player is not None:
      self._player.set_volume(self._volume_slider.value() / 100.0)

  def _update_time_label(self, position_sec: float) -> None:
    total = self._session_timeline.total_duration_sec if self._session_timeline else 0.0
    self._time_label.setText(f"{format_time(position_sec)} / {format_time(total)}")

  def _on_timeline_seek(self, session_sec: float) -> None:
    if self._player is None or self._player.state == PlayerState.STOPPED:
      return
    self._player.seek_to_session(session_sec)
    self._update_time_label(session_sec)

  def _on_mode_changed(self) -> None:
    is_from_track = self._mode_combo.currentData() == StartMode.FROM_TRACK.value
    self._start_track_combo.setVisible(is_from_track)
    if uses_auto_mix_settings(load_settings()):
      profile = self._current_library_profile()
      if profile is not None:
        self._apply_profile_to_controls(profile)
    self._refresh_auto_profile_hint()

  def _refresh_start_track_combo(self) -> None:
    self._start_track_combo.clear()
    if not default_db_path().exists():
      return

    with TrackRepository(default_db_path()) as repo:
      tracks = repo.list_mixable()

    for list_index, track in enumerate(tracks, start=1):
      if track.id is None:
        continue
      self._start_track_combo.addItem(
        _start_track_combo_label(track, list_index=list_index),
        track.id,
      )

  def _choose_folder(self) -> None:
    start = self._folder_edit.text() or str(Path.home())
    folder = QFileDialog.getExistingDirectory(self, "Выберите папку с музыкой", start)
    if not folder:
      return
    self._folder_edit.setText(folder)
    settings = load_settings()
    settings["library_path"] = folder
    save_settings(settings)
    self._status.setText(f"Папка: {folder}")

  def _start_scan_analyze(self) -> None:
    folder = self._folder_edit.text().strip()
    if not folder:
      QMessageBox.warning(self, "BPMind", "Сначала выберите папку с музыкой.")
      return
    if self._scan_worker and self._scan_worker.isRunning():
      return

    self._scan_btn.setEnabled(False)
    self._mix_btn.setEnabled(False)
    self._progress.setVisible(True)
    self._progress.setValue(0)
    self._status.setText("Запуск сканирования и анализа...")

    force = self._force_analyze_cb.isChecked()
    deep = self._deep_analyze_cb.isChecked()

    if deep and default_db_path().exists():
      with TrackRepository(default_db_path()) as repo:
        mixable = repo.list_mixable()
        deep_pending = repo.list_for_deep_analysis(include_analyzed=force)
        if not deep_pending and mixable and all(
          track.analysis_level == AnalysisLevel.DEEP for track in mixable
        ):
          QMessageBox.information(
            self,
            "BPMind",
            "Глубокий анализ уже выполнен для всех треков.\n\n"
            "Включите «Пересчитать анализ», если хотите прогнать его заново.",
          )

    self._scan_worker = ScanAnalyzeWorker(Path(folder), force=force, deep=deep)
    self._scan_worker.progress.connect(self._on_analyze_progress)
    self._scan_worker.status.connect(self._status.setText)
    self._scan_worker.finished_ok.connect(self._on_scan_finished)
    self._scan_worker.failed.connect(self._on_worker_failed)
    self._scan_worker.finished.connect(lambda: self._scan_btn.setEnabled(True))
    self._scan_worker.finished.connect(lambda: self._mix_btn.setEnabled(True))
    self._scan_worker.start()

  def _on_analyze_progress(self, index: int, total: int, label: str) -> None:
    self._progress.setMaximum(total)
    self._progress.setValue(index)
    short = label if len(label) <= 50 else label[:47] + "..."
    self._status.setText(f"Анализ [{index}/{total}]: {short}")

  def _on_scan_finished(self, total: int, analyzed: int, failed: int, summary: str) -> None:
    self._progress.setVisible(False)
    self._refresh_start_track_combo()
    self._reload_library_profile_ui()
    self._status.setText(summary)
    if failed > 0:
      QMessageBox.warning(
        self,
        "BPMind",
        f"{summary}\n\nОшибок при анализе: {failed}.",
      )
    elif analyzed == 0 and self._deep_analyze_cb.isChecked():
      QMessageBox.information(self, "BPMind", summary)

  def _start_build_mix(self) -> None:
    if self._mix_worker and self._mix_worker.isRunning():
      return

    mode_value = self._mode_combo.currentData()
    mode = StartMode(mode_value)

    start_track_id: int | None = None
    if mode == StartMode.FROM_TRACK:
      if self._start_track_combo.count() == 0:
        QMessageBox.warning(self, "BPMind", "Нет треков для старта. Сначала просканируйте и проанализируйте библиотеку.")
        return
      start_track_id = self._start_track_combo.currentData()
      if start_track_id is None:
        QMessageBox.warning(self, "BPMind", "Выберите стартовый трек.")
        return

    self._mix_btn.setEnabled(False)
    self._status.setText("Построение микса...")

    self._mix_worker = MixBuildWorker(mode, start_track_id=start_track_id)
    self._mix_worker.finished_ok.connect(self._on_mix_built)
    self._mix_worker.failed.connect(self._on_worker_failed)
    self._mix_worker.finished.connect(lambda: self._mix_btn.setEnabled(True))
    self._mix_worker.start()

  def _on_mix_built(self, count: int, mode_name: str) -> None:
    self._status.setText(f"Микс готов: {count} треков, режим {mode_name}.")
    self._load_mix_plan()
    QMessageBox.information(self, "BPMind", f"Mix Session собрана: {count} треков.")

  def _on_worker_failed(self, message: str) -> None:
    self._progress.setVisible(False)
    self._status.setText(message)
    QMessageBox.critical(self, "BPMind", message)

  def _load_mix_plan(self) -> None:
    mix_path = default_mix_path()
    if not mix_path.exists():
      self._mix_track_ids = []
      self._session_timeline = None
      self._timeline_widget.set_timeline(None)
      self._update_time_label(0.0)
      self._refresh_mix_list()
      return

    session = load_mix_session(mix_path)
    self._mix_track_ids = [item.track_id for item in session.tracks]

    if not default_db_path().exists():
      self._session_timeline = None
      self._timeline_widget.set_timeline(None)
      self._update_time_label(0.0)
      self._refresh_mix_list()
      return

    with TrackRepository(default_db_path()) as repo:
      self._tracks_by_id = {}
      for track_id in self._mix_track_ids:
        track = repo.get_by_id(track_id)
        if track is not None:
          self._tracks_by_id[track_id] = track

    self._session_timeline = build_session_timeline(session, self._tracks_by_id)
    self._timeline_widget.set_timeline(self._session_timeline)
    self._update_time_label(0.0)
    self._refresh_mix_list()

  def _refresh_mix_list(self) -> None:
    self._mix_list.clear()
    for list_index, track_id in enumerate(self._mix_track_ids, start=1):
      track = self._tracks_by_id.get(track_id)
      if track is None:
        self._mix_list.addItem(f"{list_index}. [трек {track_id} недоступен]")
        continue
      self._mix_list.addItem(_mix_list_label(track, list_index=list_index))

  def _highlight_mix_list_row(self, row: int | None) -> None:
    self._mix_list.blockSignals(True)
    if row is None or row < 0 or row >= self._mix_list.count():
      self._mix_list.clearSelection()
    else:
      self._mix_list.setCurrentRow(row)
    self._mix_list.blockSignals(False)

  def _on_mix_track_clicked(self, item) -> None:
    row = self._mix_list.row(item)
    if row < 0:
      return

    if self._player is not None and self._player.state != PlayerState.STOPPED:
      self._player.jump_to_track(row)
      self._refresh_playback_ui()
      return

    self._play_from_index(row)

  def _play_from_index(self, index: int) -> None:
    mix_path = default_mix_path()
    if not mix_path.exists():
      QMessageBox.warning(self, "BPMind", "Сначала постройте микс.")
      return

    self._load_mix_plan()
    session = load_mix_session(mix_path)
    if not self._tracks_by_id:
      QMessageBox.warning(self, "BPMind", "В миксе нет доступных треков.")
      return

    self._stop_playback()
    self._player = SessionPlayer(session, self._tracks_by_id)
    self._apply_player_volume()
    self._player.play(start_index=index)
    self._set_playback_enabled(True)
    self._ui_timer.start()
    self._status.setText("Воспроизведение")
    self._refresh_playback_ui()

  def _play(self) -> None:
    if self._player is not None:
      state = self._player.state
      if state == PlayerState.PLAYING:
        return
      if state == PlayerState.PAUSED:
        self._player.play()
        self._set_playback_enabled(True)
        self._ui_timer.start()
        self._status.setText("Воспроизведение")
        self._refresh_playback_ui()
        return

    mix_path = default_mix_path()
    if not mix_path.exists():
      QMessageBox.warning(self, "BPMind", "Сначала постройте микс.")
      return

    self._load_mix_plan()
    session = load_mix_session(mix_path)
    if not self._tracks_by_id:
      QMessageBox.warning(self, "BPMind", "В миксе нет доступных треков.")
      return

    self._stop_playback()
    self._player = SessionPlayer(session, self._tracks_by_id)
    self._apply_player_volume()
    self._player.play(start_index=0)
    self._set_playback_enabled(True)
    self._ui_timer.start()
    self._status.setText("Воспроизведение")
    self._refresh_playback_ui()

  def _toggle_pause(self) -> None:
    if self._player is None:
      return
    state = self._player.toggle_pause()
    self._status.setText("Пауза" if state == PlayerState.PAUSED else "Воспроизведение")

  def _next_track(self) -> None:
    if self._player is None:
      return
    if not self._player.next_track():
      self._end_session_naturally()

  def _prev_track(self) -> None:
    if self._player is None:
      return
    self._player.previous_track()

  def _stop_playback(self) -> None:
    self._ui_timer.stop()
    if self._player is not None:
      self._player.stop()
      self._player = None
    self._set_playback_enabled(False)
    self._now_label.setText("Сейчас: —")
    self._next_label.setText("Далее: —")
    self._highlight_mix_list_row(None)
    self._timeline_widget.set_position(0.0)
    self._update_time_label(0.0)

  def _end_session_naturally(self) -> None:
    if self._ending_session:
      return
    self._ending_session = True
    self._stop_playback()
    self._status.setText("Конец сета")

    reply = QMessageBox.question(
      self,
      "BPMind",
      "Сет закончился. Построить новый микс?",
      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
      QMessageBox.StandardButton.Yes,
    )
    self._ending_session = False
    if reply == QMessageBox.StandardButton.Yes:
      self._start_build_mix()

  def _set_playback_enabled(self, active: bool) -> None:
    self._pause_btn.setEnabled(active)
    self._next_btn.setEnabled(active)
    self._prev_btn.setEnabled(active)
    self._stop_btn.setEnabled(active)

  def _refresh_playback_ui(self) -> None:
    if self._player is None:
      return

    now = self._player.now_playing()
    if now is None:
      if self._player.state == PlayerState.STOPPED:
        self._end_session_naturally()
      return

    bpm = f"{now.track.bpm:.1f}" if now.track.bpm else "?"
    self._now_label.setText(f"Сейчас [{now.index}/{now.total}]  {bpm} BPM  {track_label(now.track)}")
    self._highlight_mix_list_row(self._player.current_index)

    status = self._player.playback_status()
    self._update_time_label(status.session_position_sec)
    if not self._timeline_widget.is_dragging():
      self._timeline_widget.set_position(status.session_position_sec)

    next_text = "Далее: —"
    if self._player.current_index + 1 < len(self._mix_track_ids):
      next_id = self._mix_track_ids[self._player.current_index + 1]
      next_track = self._tracks_by_id.get(next_id)
      if next_track is not None:
        nbpm = f"{next_track.bpm:.1f}" if next_track.bpm else "?"
        next_text = f"Далее: {nbpm} BPM  {track_label(next_track)}"
    self._next_label.setText(next_text)
