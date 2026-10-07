"""Hilfsfunktionen für Tests (kein pytest-Fixture-Code)."""

from __future__ import annotations

import json
from pathlib import Path

import cv2

from blackjack_assistant.recognition.matcher import Detection

DATA = Path(__file__).parent / "data"


def fixture_image(name: str):
    image = cv2.imread(str(DATA / f"{name}.png"), cv2.IMREAD_COLOR)
    assert image is not None, f"Testbild fehlt: {name}.png (python tools/make_test_screenshots.py)"
    return image


def fixture_expected(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def det(rank: str, x: int, y: int, score: float = 0.95, w: int = 18, h: int = 25,
        second: float = 0.5) -> Detection:
    """Künstlicher Treffer für Tracker-Tests."""
    return Detection(rank, score, x, y, w, h, second_score=second)
