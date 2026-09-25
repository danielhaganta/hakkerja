import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any, ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIMENSIONS = 768
FEEDBACK_COMMENT_MAX_CHARS = 280

# Deterministic constraint names, so later migrations can drop them by name on any database.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {str: Text, datetime: DateTime(timezone=True)}


class RegulationType(StrEnum):
    UU = "UU"
    PP = "PP"
    PERMEN = "PERMEN"
    PUTUSAN_MK = "PUTUSAN_MK"


class RegulationStatus(StrEnum):
    BERLAKU = "berlaku"
    DIUBAH_SEBAGIAN = "diubah_sebagian"
    DICABUT = "dicabut"


class ProvisionStatus(StrEnum):
    BERLAKU = "berlaku"
    DIUBAH = "diubah"
    DIHAPUS = "dihapus"


class QuestionStatus(StrEnum):
    ANSWERED = "answered"
    NOT_FOUND = "not_found"
    OUT_OF_SCOPE = "out_of_scope"
    QUOTA_EXCEEDED = "quota_exceeded"
    ERROR = "error"


class EvalMode(StrEnum):
    RETRIEVAL = "retrieval"
    FULL = "full"


# TEXT + CHECK instead of a native ENUM type: see docs/adr/0001-migrations-and-schema.md.
def check_one_of(column: str, values: type[StrEnum]) -> CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=column)


class Regulation(Base):
    __tablename__ = "regulations"
    __table_args__ = (
        check_one_of("type", RegulationType),
        check_one_of("status", RegulationStatus),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    type: Mapped[str]
    number: Mapped[str]
    year: Mapped[int]
    title: Mapped[str]
    enacted_date: Mapped[date | None]
    effective_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default=RegulationStatus.BERLAKU)
    revoked_by_id: Mapped[int | None] = mapped_column(ForeignKey("regulations.id"))
    source_url: Mapped[str]
    file_sha256: Mapped[str | None]
    retrieved_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Provision(Base):
    """One row per version of an article.

    An article amended by UU 6/2023 keeps the regulation_id of its original law;
    the amending law goes in amended_by_id. valid_to is exclusive: the version in
    force on day d satisfies valid_from <= d AND (valid_to IS NULL OR d < valid_to).
    """

    __tablename__ = "provisions"
    __table_args__ = (
        check_one_of("status", ProvisionStatus),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_range"),
        Index(
            "uq_provisions_in_force_article",
            "regulation_id",
            "article",
            unique=True,
            postgresql_where=sql_text("valid_to IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    regulation_id: Mapped[int] = mapped_column(ForeignKey("regulations.id"))
    article: Mapped[str]
    label: Mapped[str]
    chapter: Mapped[str | None]
    text: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=ProvisionStatus.BERLAKU)
    amended_by_id: Mapped[int | None] = mapped_column(ForeignKey("regulations.id"))
    amendment_ref: Mapped[str | None]
    valid_from: Mapped[date]
    valid_to: Mapped[date | None]
    verified_manually: Mapped[bool] = mapped_column(server_default=false())
    content_sha256: Mapped[str]


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("provision_id", "chunk_index"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provision_id: Mapped[int] = mapped_column(ForeignKey("provisions.id", ondelete="CASCADE"))
    chunk_index: Mapped[int]
    text: Mapped[str]
    # Two-argument form: generated columns need an immutable expression, and the
    # one-argument form depends on the session's default_text_search_config.
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('indonesian', text)", persisted=True)
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str]
    corpus_version: Mapped[str]


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (check_one_of("status", QuestionStatus),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    question_text: Mapped[str]
    normalized_hash: Mapped[str]
    status: Mapped[str]
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    provider: Mapped[str | None]
    model: Mapped[str | None]
    prompt_version: Mapped[str | None]
    corpus_version: Mapped[str | None]
    cache_hit: Mapped[bool] = mapped_column(server_default=false())
    used_tools: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    latency_ms: Mapped[int | None]
    client_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class AnswerCitation(Base):
    __tablename__ = "answer_citations"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    provision_id: Mapped[int] = mapped_column(ForeignKey("provisions.id"), primary_key=True)
    rank: Mapped[int]


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("question_id", "client_hash"),
        CheckConstraint(
            f"char_length(comment) <= {FEEDBACK_COMMENT_MAX_CHARS}", name="comment_length"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    helpful: Mapped[bool]
    comment: Mapped[str | None]
    client_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AnswerCache(Base):
    __tablename__ = "answer_cache"

    cache_key: Mapped[str] = mapped_column(primary_key=True)
    # SET NULL: the 180-day retention job deletes questions while their cached answers live on.
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB)
    hit_count: Mapped[int] = mapped_column(server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]


class QueryEmbeddingCache(Base):
    __tablename__ = "query_embedding_cache"

    text_hash: Mapped[str] = mapped_column(primary_key=True)
    # Part of the key: fallback embedders share the dimension but not the vector space.
    embedding_model: Mapped[str] = mapped_column(primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UsageDaily(Base):
    __tablename__ = "usage_daily"

    client_hash: Mapped[str] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column(server_default="0")


class ProviderUsageDaily(Base):
    __tablename__ = "provider_usage_daily"

    provider: Mapped[str] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(primary_key=True)
    requests: Mapped[int] = mapped_column(server_default="0")
    tokens: Mapped[int] = mapped_column(server_default="0")


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (check_one_of("mode", EvalMode),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_at: Mapped[datetime] = mapped_column(server_default=func.now())
    git_sha: Mapped[str]
    corpus_version: Mapped[str]
    mode: Mapped[str]
    provider: Mapped[str | None]
    model: Mapped[str | None]
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
