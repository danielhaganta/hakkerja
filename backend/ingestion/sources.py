from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from app.db.models import RegulationStatus, RegulationType, TextQuality

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
SOURCES_FILE = DATA_DIR / "sources.yaml"


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    type: RegulationType
    number: str
    year: int
    title: str
    enacted_date: date | None
    effective_date: date | None
    source_url: str | None
    status: RegulationStatus
    file: str
    sha256: str
    text_quality: TextQuality
    expected_articles: int

    @property
    def raw_path(self) -> Path:
        return RAW_DIR / self.file

    @property
    def interim_path(self) -> Path:
        return INTERIM_DIR / f"{self.code}.txt"

    @property
    def processed_path(self) -> Path:
        return PROCESSED_DIR / f"{self.code}.jsonl"


def load_sources(path: Path = SOURCES_FILE) -> list[Source]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Source.model_validate(entry) for entry in document["regulations"]]


def select_sources(code: str | None) -> list[Source]:
    sources = load_sources()
    if code is None:
        return sources
    selected = [source for source in sources if source.code == code]
    if not selected:
        raise SystemExit(f"Unknown regulation code: {code}")
    return selected
