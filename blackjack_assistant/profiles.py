"""Profile: alle Einstellungen pro Spiel (Bildschirmbereiche, Lesemodus, Templates, Regeln …).

Ein Profil ist ein Ordner unter profiles/<name>/ mit einer Datei profile.json und einem
Unterordner templates/ (ein Bild pro Rang). Profile lassen sich zur Laufzeit umschalten.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .models import Rules

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = PROJECT_ROOT / "profiles"

READ_MODES = ("table", "history")

# Bereich als [x, y, Breite, Höhe] in Bildschirmpixeln
Region = list[int]


@dataclass
class RecognitionSettings:
    """Einstellungen der Kartenerkennung."""

    min_confidence: float = 0.80      # darunter: unsicher → nicht zählen, gelb markieren
    uncertain_margin: float = 0.03    # bester und zweitbester Rang zu nah beieinander → unsicher
    min_candidate: float = 0.75       # darunter wird ein Treffer gar nicht beachtet
    stable_ms: int = 300              # Bild muss so lange unverändert sein
    stable_threshold: float = 3       # so viele geänderte Pixel (verkleinertes Bild) gelten noch als "unverändert"
    uncertain_frames: int = 3         # so viele stabile Bilder darf eine Karte unsicher bleiben
    orientation_check: bool = True    # gedrehte Ecken (unten rechts) aussortieren
    card_brightness: int | None = 170 # nur in hellen Flächen (Karten) suchen; None = überall
    table_scale: float | None = 1.0   # Template-Skalierung im Tischbereich (None = automatisch)
    history_scale: float | None = 1.0 # Template-Skalierung im Verlaufs-Panel (None = automatisch)

    @classmethod
    def from_dict(cls, data: dict | None) -> "RecognitionSettings":
        data = data or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Profile:
    """Einstellungen für ein Spiel."""

    name: str
    display_name: str = ""
    read_mode: str = "table"                       # "table" oder "history"
    # Bildschirmbereiche (absolute Pixel). None = noch nicht festgelegt.
    regions: dict[str, Region | None] = field(
        default_factory=lambda: {"table": None, "history": None}
    )
    # Dealer- und Spielerbereich relativ zum Tischbereich: [x, y, Breite, Höhe] als Anteile 0..1
    areas: dict[str, list[float]] = field(
        default_factory=lambda: {"dealer": [0.0, 0.0, 1.0, 0.4], "player": [0.0, 0.4, 1.0, 0.6]}
    )
    recognition: RecognitionSettings = field(default_factory=RecognitionSettings)
    rules: Rules = field(default_factory=Rules)
    # Dealer bekommt eine Hole Card. Wird sie nicht gezeigt, gilt sie als "ungesehen".
    dealer_hole_card: bool = True
    counting: dict = field(default_factory=lambda: {"system": "hi_lo"})
    betting: dict = field(
        default_factory=lambda: {"unit": 10, "ramp": [[2, 2], [3, 4], [4, 6], [5, 8]]}
    )
    decision_engine: str = "strategy"              # "strategy" oder "jev"
    notes: str = ""
    path: Path | None = None                       # Ordner des Profils (nicht gespeichert)

    # ------------------------------------------------------------------

    @property
    def templates_dir(self) -> Path:
        if self.path is None:
            raise ValueError("Profil hat keinen Ordner")
        return self.path / "templates"

    @property
    def deck_count(self) -> int:
        return self.rules.decks

    def validate(self) -> list[str]:
        """Gibt eine Liste von Problemen zurück (leer = alles in Ordnung)."""
        problems = []
        if self.read_mode not in READ_MODES:
            problems.append(f"Unbekannter Lesemodus: {self.read_mode}")
        for key in ("dealer", "player"):
            area = self.areas.get(key)
            if not area or len(area) != 4 or not all(0 <= v <= 1 for v in area):
                problems.append(f"Bereich '{key}' muss [x, y, b, h] mit Werten 0..1 sein")
        for key, region in self.regions.items():
            if region is not None and (len(region) != 4 or region[2] <= 0 or region[3] <= 0):
                problems.append(f"Bildschirmbereich '{key}' ist ungültig: {region}")
        if not 1 <= self.rules.decks <= 8:
            problems.append("Deckanzahl muss zwischen 1 und 8 liegen")
        if self.decision_engine not in ("strategy", "jev"):
            problems.append(f"Unbekannte Entscheidungs-Engine: {self.decision_engine}")
        return problems

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("path")
        data["rules"] = self.rules.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict, path: Path | None = None) -> "Profile":
        known = {f.name for f in fields(cls)} - {"path", "recognition", "rules"}
        kwargs = {k: v for k, v in data.items() if k in known}
        profile = cls(**kwargs)
        profile.recognition = RecognitionSettings.from_dict(data.get("recognition"))
        profile.rules = Rules.from_dict(data.get("rules"))
        profile.path = path
        # Fehlende Bereiche ergänzen, damit ältere Profile weiter funktionieren
        profile.regions = {"table": None, "history": None, **(profile.regions or {})}
        return profile

    def save(self, path: Path | None = None) -> Path:
        """Speichert profile.json (Ordner wird bei Bedarf angelegt)."""
        folder = Path(path) if path else self.path
        if folder is None:
            folder = PROFILES_DIR / self.name
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder
        target = folder / "profile.json"
        target.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        return target


def load_profile(name_or_path: str | Path, root: Path = PROFILES_DIR) -> Profile:
    """Lädt ein Profil über seinen Namen (Ordner unter profiles/) oder einen Pfad."""
    candidate = Path(name_or_path)
    if (root / str(name_or_path) / "profile.json").exists():
        folder = root / str(name_or_path)      # Name eines Profils unter profiles/
    elif candidate.is_file():
        folder = candidate.parent              # Pfad zu einer profile.json
    else:
        folder = candidate                     # Pfad zu einem Profilordner
    file = folder / "profile.json"
    if not file.exists():
        raise FileNotFoundError(f"Profil nicht gefunden: {file}")
    data = json.loads(file.read_text(encoding="utf-8"))
    profile = Profile.from_dict(data, path=folder)
    problems = profile.validate()
    if problems:
        raise ValueError(f"Profil '{profile.name}' ungültig: " + "; ".join(problems))
    return profile


def list_profiles(root: Path = PROFILES_DIR) -> list[str]:
    """Namen aller vorhandenen Profile (alphabetisch)."""
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "profile.json").exists())


class ProfileManager:
    """Hält das aktive Profil und schaltet reihum weiter (Hotkey "Profil wechseln")."""

    def __init__(self, root: Path = PROFILES_DIR, active: str | None = None):
        self.root = root
        names = list_profiles(root)
        if not names:
            raise FileNotFoundError(f"Keine Profile in {root}")
        self.names = names
        self.active = load_profile(active or names[0], root)

    def next(self) -> Profile:
        self.names = list_profiles(self.root)
        index = self.names.index(self.active.name) if self.active.name in self.names else -1
        self.active = load_profile(self.names[(index + 1) % len(self.names)], self.root)
        return self.active

    def switch(self, name: str) -> Profile:
        self.active = load_profile(name, self.root)
        return self.active
