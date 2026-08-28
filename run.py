#!/usr/bin/env python3
"""Запуск приложения: python3 run.py [порт]

Порт по умолчанию — 8000. Переменная HOST задаёт адрес прослушивания:
в контейнере нужен 0.0.0.0, локально по умолчанию 127.0.0.1.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from animal_translator.web import serve  # noqa: E402

if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8000,
          os.environ.get("HOST", "127.0.0.1"))
