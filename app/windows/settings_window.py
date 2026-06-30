from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
  QCheckBox,
  QComboBox,
  QDialog,
  QDoubleSpinBox,
  QFrame,
  QGroupBox,
  QHBoxLayout,
  QLabel,
  QListWidget,
  QMessageBox,
  QPushButton,
  QScrollArea,
  QSlider,
  QSpinBox,
  QVBoxLayout,
  QWidget,
)

from app.mix_settings import format_auto_profile_hint, uses_auto_mix_settings
from app.paths import default_db_path, default_library_profile_path, load_settings, mixes_dir, save_settings
from engine.database.repository import TrackRepository
from engine.domain.enums import StartMode, TransitionType
from engine.domain.models import MixSession
from engine.library.library_profile import (
  compute_library_profile,
  load_library_profile,
  profile_tuning_for_mode,
  save_library_profile,
)
from engine.mix_generator.recipe_library import format_recipe_list_label, list_recipe_files
from engine.mix_generator.recipe_metadata import MixRecipeMetadata
from engine.transitions.display import DEBUG_TRANSITION_PROFILES, transition_profile_label
from engine.transitions.modes import TransitionMode


class SettingsWindow(QDialog):
  """Отдельное окно параметров микса, анализа и сохранённых сетов."""

  recipe_open_requested = Signal(Path)

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setWindowTitle("Настройки")
    self.setWindowFlags(Qt.WindowType.Window)
    self.setMinimumWidth(440)
    self.resize(480, 560)
    self._applying_profile = False

    settings = load_settings()

    self._force_analyze_cb = QCheckBox("Пересчитать анализ")
    self._force_analyze_cb.setToolTip("Как --force в CLI: переанализировать все треки")

    self._quick_only_cb = QCheckBox("Только быстрый анализ")
    self._quick_only_cb.setToolTip(
      "По умолчанию после скана выполняется и глубокий анализ (энергия, переходы, groove)"
    )
    self._quick_only_cb.setChecked(bool(settings.get("quick_analyze_only", False)))
    self._quick_only_cb.toggled.connect(self._on_quick_only_toggled)

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
    self._crossfade_spin.setToolTip(
      "Верхняя граница длины каждого перехода. Реальная длина зависит от типа эффекта и BPM. "
      "После изменения пересоберите микс."
    )
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

    self._use_seed_cb = QCheckBox("Повторять случайный порядок")
    self._use_seed_cb.setToolTip(
      "Только random/wave. Чтобы сохранить понравившийся микс — «Сохранить сет», не эта опция."
    )
    self._use_seed_cb.toggled.connect(self._on_use_seed_toggled)
    self._seed_spin = QSpinBox()
    self._seed_spin.setRange(1, 2_147_483_647)
    self._seed_spin.setEnabled(False)
    self._seed_spin.setToolTip("Номер варианта случайной сборки (для CLI и продвинутых сценариев)")
    self._seed_spin.valueChanged.connect(self._save_seed_settings)
    saved_seed = settings.get("mix_seed")
    if saved_seed is not None:
      self._use_seed_cb.setChecked(True)
      self._seed_spin.setEnabled(True)
      self._seed_spin.setValue(int(saved_seed))

    self._transition_mode_combo = QComboBox()
    self._transition_mode_combo.addItem("Авто (DJ)", TransitionMode.AUTO.value)
    self._transition_mode_combo.addItem("Фиксированный (тест)", TransitionMode.FIXED.value)
    self._transition_mode_combo.addItem("Случайный", TransitionMode.RANDOM.value)
    self._transition_mode_combo.addItem("Нет", TransitionMode.NONE.value)
    self._transition_mode_combo.setToolTip(
      "Авто — умный выбор переходов.\n"
      "Фиксированный — один профиль на все стыковки (удобно слушать tape, удар, реверс).\n"
      "Случайный — случайный профиль на каждый переход.\n"
      "Нет — без эффектов, треки целиком."
    )
    self._transition_mode_combo.currentIndexChanged.connect(self._on_transition_mode_changed)
    self._transition_mode_combo.currentIndexChanged.connect(self._save_transition_settings)

    self._transition_profile_combo = QComboBox()
    for profile in DEBUG_TRANSITION_PROFILES:
      self._transition_profile_combo.addItem(
        transition_profile_label(profile),
        profile.value,
      )
    self._transition_profile_combo.setToolTip("Профиль для режима «Фиксированный (тест)»")
    self._transition_profile_combo.currentIndexChanged.connect(self._save_transition_settings)

    saved_transition_mode = settings.get("transition_mode", TransitionMode.AUTO.value)
    saved_profile = settings.get("transition_profile", TransitionType.TAPE_STOP.value)
    if saved_profile in ("none", "cut") and saved_transition_mode == TransitionMode.FIXED.value:
      saved_transition_mode = TransitionMode.NONE.value
    mode_index = self._transition_mode_combo.findData(saved_transition_mode)
    if mode_index >= 0:
      self._transition_mode_combo.setCurrentIndex(mode_index)
    if saved_profile == "cut":
      saved_profile = TransitionType.TAPE_STOP.value
    profile_index = self._transition_profile_combo.findData(saved_profile)
    if profile_index >= 0:
      self._transition_profile_combo.setCurrentIndex(profile_index)
    self._on_transition_mode_changed(self._transition_mode_combo.currentIndex())

    self._reset_auto_btn = QPushButton("Сбросить к авто")
    self._reset_auto_btn.setToolTip("Вернуть параметры микса, подобранные под библиотеку")
    self._reset_auto_btn.clicked.connect(self._reset_to_auto_profile)

    self._auto_profile_label = QLabel("")
    self._auto_profile_label.setWordWrap(True)
    self._auto_profile_label.setStyleSheet("color: palette(mid);")

    self._saved_recipes_list = QListWidget()
    self._saved_recipes_list.setMinimumHeight(88)
    self._saved_recipes_list.setToolTip("Двойной клик — открыть сохранённый сет")
    self._saved_recipes_list.itemDoubleClicked.connect(self._on_saved_recipe_activated)

    mix_group = QGroupBox("Параметры микса")
    mix_layout = QVBoxLayout(mix_group)
    length_row = QHBoxLayout()
    length_row.addWidget(QLabel("Длина сета:"))
    length_row.addWidget(self._length_spin)
    length_row.addSpacing(12)
    length_row.addWidget(QLabel("Макс. переход:"))
    length_row.addWidget(self._crossfade_spin)
    length_row.addStretch()
    mix_layout.addLayout(length_row)

    play_ratio_row = QHBoxLayout()
    play_ratio_row.addWidget(QLabel("Играть трека:"))
    play_ratio_row.addWidget(self._play_ratio_slider, stretch=1)
    play_ratio_row.addWidget(self._play_ratio_label)
    mix_layout.addLayout(play_ratio_row)

    groove_row = QHBoxLayout()
    groove_row.addWidget(QLabel("Groove / пары:"))
    groove_row.addWidget(self._groove_slider, stretch=1)
    groove_row.addWidget(self._groove_label)
    mix_layout.addLayout(groove_row)

    seed_row = QHBoxLayout()
    seed_row.addWidget(self._use_seed_cb)
    seed_row.addWidget(self._seed_spin)
    seed_row.addStretch()
    mix_layout.addLayout(seed_row)

    transition_row = QHBoxLayout()
    transition_row.addWidget(QLabel("Переходы:"))
    transition_row.addWidget(self._transition_mode_combo, stretch=1)
    transition_row.addWidget(self._transition_profile_combo, stretch=1)
    mix_layout.addLayout(transition_row)

    reset_row = QHBoxLayout()
    reset_row.addWidget(self._reset_auto_btn)
    reset_row.addStretch()
    mix_layout.addLayout(reset_row)
    mix_layout.addWidget(self._auto_profile_label)

    scan_group = QGroupBox("Анализ")
    scan_layout = QHBoxLayout(scan_group)
    scan_layout.addWidget(self._force_analyze_cb)
    scan_layout.addWidget(self._quick_only_cb)
    scan_layout.addStretch()

    recipes_group = QGroupBox("Сохранённые сеты")
    recipes_layout = QVBoxLayout(recipes_group)
    recipes_layout.addWidget(self._saved_recipes_list)

    inner = QWidget()
    inner_layout = QVBoxLayout(inner)
    inner_layout.addWidget(scan_group)
    inner_layout.addWidget(mix_group)
    inner_layout.addWidget(recipes_group)
    inner_layout.addStretch()

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(inner)

    root = QVBoxLayout(self)
    root.addWidget(scroll)

    self.refresh_saved_recipes_list()
    self._refresh_auto_profile_hint(StartMode.CALM)

  @property
  def force_analyze(self) -> bool:
    return self._force_analyze_cb.isChecked()

  @property
  def deep_analyze(self) -> bool:
    return not self._quick_only_cb.isChecked()

  def current_transition_plan(self) -> tuple[TransitionMode, TransitionType]:
    mode_value = self._transition_mode_combo.currentData() or TransitionMode.AUTO.value
    transition_mode = TransitionMode(mode_value)
    profile_value = self._transition_profile_combo.currentData() or TransitionType.SMOOTH_BLEND.value
    try:
      fixed_profile = TransitionType.parse(profile_value)
    except ValueError:
      fixed_profile = TransitionType.SMOOTH_BLEND
    return transition_mode, fixed_profile

  def mix_seed(self, mode: StartMode) -> int | None:
    if mode not in (StartMode.RANDOM, StartMode.WAVE):
      return None
    if not self._use_seed_cb.isChecked():
      return None
    return self._seed_spin.value()

  def on_start_mode_changed(self, mode: StartMode) -> None:
    uses_seed = mode in (StartMode.RANDOM, StartMode.WAVE)
    self._use_seed_cb.setEnabled(uses_seed)
    if not uses_seed:
      self._seed_spin.setEnabled(False)
    elif self._use_seed_cb.isChecked():
      self._seed_spin.setEnabled(True)
    if uses_auto_mix_settings(load_settings()):
      profile = self._current_library_profile()
      if profile is not None:
        self._apply_profile_to_controls(profile, mode)
    self._refresh_auto_profile_hint(mode)

  def reload_library_profile_ui(self, mode: StartMode) -> None:
    settings = load_settings()
    profile = self._current_library_profile()
    if profile is not None and uses_auto_mix_settings(settings):
      self._apply_profile_to_controls(profile, mode)
    self._refresh_auto_profile_hint(mode)

  def refresh_saved_recipes_list(self) -> None:
    self._saved_recipes_list.clear()
    target_dir = mixes_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in list_recipe_files(target_dir):
      self._saved_recipes_list.addItem(format_recipe_list_label(path))
      row = self._saved_recipes_list.count() - 1
      self._saved_recipes_list.item(row).setData(Qt.ItemDataRole.UserRole, str(path))

  def apply_recipe_metadata(self, metadata: MixRecipeMetadata, session: MixSession) -> None:
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
      if metadata.seed is not None:
        settings["mix_seed"] = metadata.seed
        self._use_seed_cb.blockSignals(True)
        self._seed_spin.blockSignals(True)
        self._use_seed_cb.setChecked(True)
        self._seed_spin.setEnabled(True)
        self._seed_spin.setValue(metadata.seed)
        self._use_seed_cb.blockSignals(False)
        self._seed_spin.blockSignals(False)
      save_settings(settings)
    finally:
      self._applying_profile = False
    self._refresh_auto_profile_hint(session.start_mode)

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
    mode = StartMode.CALM
    parent = self.parent()
    if parent is not None and hasattr(parent, "current_start_mode"):
      mode = parent.current_start_mode()
    self._refresh_auto_profile_hint(mode)

  def _on_play_ratio_changed(self, value: int) -> None:
    self._play_ratio_label.setText(f"{value}%")
    self._save_mix_settings()

  def _on_groove_changed(self, value: int) -> None:
    self._groove_label.setText(f"{value}%")
    self._save_mix_settings()

  def _on_quick_only_toggled(self, checked: bool) -> None:
    settings = load_settings()
    settings["quick_analyze_only"] = checked
    save_settings(settings)

  def _on_use_seed_toggled(self, checked: bool) -> None:
    self._seed_spin.setEnabled(checked)
    self._save_seed_settings()

  def _save_seed_settings(self) -> None:
    settings = load_settings()
    if self._use_seed_cb.isChecked():
      settings["mix_seed"] = self._seed_spin.value()
    else:
      settings.pop("mix_seed", None)
    save_settings(settings)

  def _on_transition_mode_changed(self, _index: int) -> None:
    mode_value = self._transition_mode_combo.currentData()
    fixed = mode_value == TransitionMode.FIXED.value
    self._transition_profile_combo.setEnabled(fixed)
    self._transition_profile_combo.setVisible(fixed)

  def _save_transition_settings(self, *_args) -> None:
    settings = load_settings()
    mode_value = self._transition_mode_combo.currentData()
    if mode_value:
      settings["transition_mode"] = mode_value
    profile_value = self._transition_profile_combo.currentData()
    if profile_value:
      settings["transition_profile"] = profile_value
    save_settings(settings)

  def _on_saved_recipe_activated(self, item) -> None:
    path_text = item.data(Qt.ItemDataRole.UserRole)
    if not path_text:
      return
    self.recipe_open_requested.emit(Path(path_text))

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

  def _apply_profile_to_controls(self, profile, mode: StartMode) -> None:
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

  def _refresh_auto_profile_hint(self, mode: StartMode) -> None:
    settings = load_settings()
    profile = self._current_library_profile()
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

  def _reset_to_auto_profile(self) -> None:
    profile = self._current_library_profile()
    if profile is None:
      QMessageBox.information(
        self,
        "BPMind",
        "Сначала просканируйте и проанализируйте библиотеку.",
      )
      return

    parent = self.parent()
    mode = StartMode.CALM
    if parent is not None and hasattr(parent, "current_start_mode"):
      mode = parent.current_start_mode()
    play_ratio, groove_weight = profile_tuning_for_mode(profile, mode)
    settings = load_settings()
    settings["mix_settings_manual"] = False
    settings["session_length_tracks"] = profile.session_length_tracks
    settings["crossfade_duration_sec"] = profile.crossfade_duration_sec
    settings["track_play_ratio"] = play_ratio
    settings["groove_weight"] = groove_weight
    save_settings(settings)
    self._apply_profile_to_controls(profile, mode)
    self._refresh_auto_profile_hint(mode)
