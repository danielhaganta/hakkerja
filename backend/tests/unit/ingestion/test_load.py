import hashlib
from dataclasses import replace
from datetime import date

import pytest

from app.db.models import RegulationStatus, RegulationType, TextQuality
from ingestion.load import (
    MissingSourceMetadataError,
    VerifiedProvision,
    provision_values,
    regulation_values,
)
from ingestion.sources import Source
from ingestion.split_pasal import Article

SOURCE = Source(
    code="UU-13-2003",
    type=RegulationType.UU,
    number="13",
    year=2003,
    title="Ketenagakerjaan",
    enacted_date=date(2003, 3, 25),
    effective_date=date(2003, 3, 25),
    source_url="https://example.test/uu-13-2003",
    status=RegulationStatus.DIUBAH_SEBAGIAN,
    file="UU-13-2003.pdf",
    sha256="a" * 64,
    text_quality=TextQuality.NATIVE,
    expected_articles=1,
)
ARTICLE = Article(
    regulation="UU-13-2003",
    article="156",
    chapter="BAB XII - PEMUTUSAN HUBUNGAN KERJA",
    section=None,
    text="(1) Dalam hal terjadi pemutusan hubungan kerja, pengusaha diwajibkan membayar.",
    ayat=(),
    penjelasan=None,
    pages=(61, 62),
)
ARTICLE_SHA256 = hashlib.sha256(ARTICLE.text.encode()).hexdigest()


def test_regulation_values_carry_status_and_text_quality() -> None:
    values = regulation_values(SOURCE)

    assert values["status"] == "diubah_sebagian"
    assert values["text_quality"] == "native"
    assert values["file_sha256"] == "a" * 64


@pytest.mark.parametrize("missing", ["source_url", "effective_date"])
def test_refuses_to_load_without_required_metadata(missing: str) -> None:
    source = SOURCE.model_copy(update={missing: None})

    with pytest.raises(MissingSourceMetadataError):
        regulation_values(source)


def test_provision_values_derive_label_hash_and_validity() -> None:
    values = provision_values(SOURCE, 1, ARTICLE, frozenset())

    assert values["label"] == "Pasal 156 UU 13/2003"
    assert values["content_sha256"] == ARTICLE_SHA256
    assert values["valid_from"] == date(2003, 3, 25)
    assert values["verified_manually"] is False


def test_verification_holds_only_for_the_checked_text() -> None:
    checked = VerifiedProvision(
        regulation="UU-13-2003", article="156", content_sha256=ARTICLE_SHA256
    )
    edited = replace(ARTICLE, text=f"{ARTICLE.text} Diubah.")

    assert provision_values(SOURCE, 1, ARTICLE, frozenset({checked}))["verified_manually"]
    assert not provision_values(SOURCE, 1, edited, frozenset({checked}))["verified_manually"]
