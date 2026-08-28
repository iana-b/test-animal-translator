#!/usr/bin/env python3
"""Пересборка скриншотов для README.

Поднимает приложение на свободном порту, снимает страницы через headless Chrome
и складывает файлы в docs/screenshots.

    python3 scripts/screenshots.py
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
]

SHOTS = [
    ("01-species", "/", 1280, 900,
     "Выбор вида"),
    ("02-bee-full", "/species/honeybee?dance_type=waggle&waggle_run_duration_s=1.2"
                    "&n_waggle_runs_measured=4&angle_from_vertical_deg=40"
                    "&sun_azimuth_deg=180&individual_calibration_known=yes", 1280, 1250,
     "Пчела: расстояние и направление посчитаны, уверенность 85%"),
    ("03-bee-gap", "/species/honeybee?dance_type=waggle&waggle_run_duration_s=0.6", 1280, 1150,
     "Пчела: угол не измерен — направление помечено как пробел в наблюдении"),
    ("04-dog-refusal", "/species/dog?signal_type=bark&pitch=low&repetition=fast"
                       "&tonality=atonal", 1280, 1350,
     "Собака: по одному звуку контекст не определяется, показано всё распределение"),
    ("05-dog-context", "/species/dog?signal_type=bark&pitch=low&repetition=fast"
                       "&tonality=atonal&reported_situation=stranger", 1280, 1350,
     "Собака: обстановка сузила распределение до 47%"),
    ("06-elephant", "/species/elephant?perceived=heard&f0_hz=18&headshaking=yes"
                    "&threat_present=bees&group_response=retreat", 1280, 1250,
     "Слон: значение проверено проигрыванием, 6 семей из 10"),
    ("07-whale", "/species/spermwhale?signal_type=coda"
                 "&inter_click_intervals_s=0.12,0.12,0.35,0.12&extra_final_click=yes"
                 "&exchange_durations_s=0.71,0.74,0.78,0.80", 1280, 1250,
     "Кашалот: структура разобрана, значения не существует"),
    ("08-whale-clicks", "/species/spermwhale?signal_type=usual_clicks", 1280, 1050,
     "Кашалот: единственный сигнал, у которого функция установлена измерениями"),
    ("09-knowledge", "/species/elephant/kb", 1280, 1500,
     "База знаний: источники, доступ, лицензии, поправки"),
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    sys.exit("Не найден Chrome или Chromium для съёмки страниц.")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, attempts: int = 40) -> None:
    for _ in range(attempts):
        try:
            urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(0.25)
    sys.exit(f"Приложение не поднялось на {url}")


def main() -> None:
    chrome = find_chrome()
    port = free_port()
    OUT.mkdir(parents=True, exist_ok=True)

    for stale in OUT.glob("*.png"):
        stale.unlink()

    server = subprocess.Popen([sys.executable, str(ROOT / "run.py"), str(port)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        wait_for(base + "/")
        for name, path, width, height, caption in SHOTS:
            target = OUT / f"{name}.png"
            subprocess.run(
                [chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
                 f"--window-size={width},{height}",
                 f"--screenshot={target}", base + path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            size = target.stat().st_size // 1024
            print(f"  {target.name:20s} {size:4d} КБ  {caption}")
    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    main()
