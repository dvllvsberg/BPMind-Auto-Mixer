# BPMind Auto Mixer

Локальный авто-миксер для своей музыкальной библиотеки: анализ треков, сбор сета с кроссфейдами, воспроизведение и экспорт в WAV/MP3.

Репозиторий: [github.com/dvllvsberg/BPMind-Auto-Mixer](https://github.com/dvllvsberg/BPMind-Auto-Mixer)

## Требования

- Windows 10/11 (разрабатывалось под Windows; Linux/macOS возможны, но не проверялись)
- Python 3.11+
- Аудиофайлы: MP3, FLAC, WAV и другие форматы, которые читает `soundfile` / `librosa`

## Установка

```powershell
cd "BPMind Auto Mixer"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy settings\default.json.example settings\default.json
```

В `settings/default.json` укажите `library_path` — папку с музыкой.

## Запуск (GUI)

```powershell
python run_app.py
```

### Быстрый сценарий

1. Выберите папку с музыкой
2. **Сканировать и анализировать** (включите «Глубокий анализ» при первом запуске)
3. Выберите режим (calm / peak / wave / random) → **Построить микс**
4. **Play**

Параметры микса подстраиваются автоматически (см. строку под кнопкой «Построить микс»). Ручная подкрутка — в **▸ Дополнительно**.

### Рецепты и экспорт

| Действие | Описание |
|----------|----------|
| **Сохранить сет** | Рецепт в `mixes/` (порядок, тайминги, параметры) |
| **Открыть сет** | Загрузить сохранённый рецепт |
| **Экспорт аудио** | MP3 (320 kbps) или WAV в `exports/` |

## CLI

```powershell
python run_engine.py scan "D:/Music"
python run_engine.py analyze
python run_engine.py deep-analyze
python run_engine.py mix --mode wave
python run_engine.py play
python run_engine.py export --format mp3
```

## Режимы микса

| Режим | Суть |
|-------|------|
| **calm** | Спокойная дуга энергии, длиннее фрагменты треков |
| **peak** | Ближе к пику громкости, сильнее groove-пары |
| **wave** | Синусоидальная волна: тихо → пик в середине → тихий финал |
| **random** | Без целевой дуги, умный скоринг BPM/groove |
| **from_track** | Сет с выбранного трека |

## Структура проекта

```
app/          # GUI (PySide6)
engine/       # анализ, генерация микса, плеер, экспорт
cache/        # SQLite-библиотека, последний микс (локально)
mixes/        # сохранённые рецепты
exports/      # экспортированные WAV/MP3
settings/     # настройки пользователя
tests/        # pytest
docs/         # архитектура (Transition Engine и др.)
```

Подробнее о планируемом движке переходов: [docs/transition-engine.md](docs/transition-engine.md).

## Тесты

```powershell
pytest tests/
```

## Лицензия

Пока без лицензии — личный проект. При публикации можно добавить MIT.
