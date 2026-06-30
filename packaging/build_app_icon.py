"""Собрать packaging/app.ico из assets/icon-master.png (экспорт из Figma 1024×1024)."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "assets" / "icon-master.png"
TARGET = REPO_ROOT / "packaging" / "app.ico"


def main() -> int:
  if not SOURCE.exists():
    print(f"Нет файла: {SOURCE}")
    print("Экспортируй фрейм BPMind Icon из Figma как PNG 1024×1024.")
    return 1

  try:
    from PIL import Image
  except ImportError as exc:
    print("Нужен Pillow: pip install Pillow")
    raise SystemExit(1) from exc

  image = Image.open(SOURCE).convert("RGBA")
  sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
  TARGET.parent.mkdir(parents=True, exist_ok=True)
  image.save(TARGET, format="ICO", sizes=sizes)
  print(f"Готово: {TARGET}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
