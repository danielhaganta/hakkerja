"""Initial schema (SPEC section 6)

Revision ID: 798927a72b33
Revises:
Create Date: 2026-09-25 22:04:06.241086

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "798927a72b33"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate does not know about extensions; chunks.embedding needs it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("git_sha", sa.Text(), nullable=False),
        sa.Column("corpus_version", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("mode IN ('retrieval', 'full')", name=op.f("ck_eval_runs_mode")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
    )
    op.create_table(
        "provider_usage_daily",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("provider", "day", name=op.f("pk_provider_usage_daily")),
    )
    op.create_table(
        "query_embedding_cache",
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "text_hash", "embedding_model", name=op.f("pk_query_embedding_cache")
        ),
    )
    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("normalized_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("corpus_version", sa.Text(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("used_tools", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("client_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('answered', 'not_found', 'out_of_scope', 'quota_exceeded', 'error')",
            name=op.f("ck_questions_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_questions")),
    )
    op.create_index(op.f("ix_questions_created_at"), "questions", ["created_at"], unique=False)
    op.create_table(
        "regulations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("enacted_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default="berlaku", nullable=False),
        sa.Column("revoked_by_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=True),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('berlaku', 'diubah_sebagian', 'dicabut')",
            name=op.f("ck_regulations_status"),
        ),
        sa.CheckConstraint(
            "type IN ('UU', 'PP', 'PERMEN', 'PUTUSAN_MK')", name=op.f("ck_regulations_type")
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_id"],
            ["regulations.id"],
            name=op.f("fk_regulations_revoked_by_id_regulations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regulations")),
        sa.UniqueConstraint("code", name=op.f("uq_regulations_code")),
    )
    op.create_table(
        "usage_daily",
        sa.Column("client_hash", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("client_hash", "day", name=op.f("pk_usage_daily")),
    )
    op.create_table(
        "answer_cache",
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name=op.f("fk_answer_cache_question_id_questions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("cache_key", name=op.f("pk_answer_cache")),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("client_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(comment) <= 280", name=op.f("ck_feedback_comment_length")),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name=op.f("fk_feedback_question_id_questions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint(
            "question_id", "client_hash", name=op.f("uq_feedback_question_id_client_hash")
        ),
    )
    op.create_table(
        "provisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("regulation_id", sa.Integer(), nullable=False),
        sa.Column("article", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("chapter", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="berlaku", nullable=False),
        sa.Column("amended_by_id", sa.Integer(), nullable=True),
        sa.Column("amendment_ref", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "verified_manually", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('berlaku', 'diubah', 'dihapus')", name=op.f("ck_provisions_status")
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name=op.f("ck_provisions_valid_range")
        ),
        sa.ForeignKeyConstraint(
            ["amended_by_id"],
            ["regulations.id"],
            name=op.f("fk_provisions_amended_by_id_regulations"),
        ),
        sa.ForeignKeyConstraint(
            ["regulation_id"],
            ["regulations.id"],
            name=op.f("fk_provisions_regulation_id_regulations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provisions")),
    )
    op.create_index(
        "uq_provisions_in_force_article",
        "provisions",
        ["regulation_id", "article"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_table(
        "answer_citations",
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("provision_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["provision_id"],
            ["provisions.id"],
            name=op.f("fk_answer_citations_provision_id_provisions"),
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name=op.f("fk_answer_citations_question_id_questions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("question_id", "provision_id", name=op.f("pk_answer_citations")),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provision_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('indonesian', text)", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("corpus_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["provision_id"],
            ["provisions.id"],
            name=op.f("fk_chunks_provision_id_provisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint(
            "provision_id", "chunk_index", name=op.f("uq_chunks_provision_id_chunk_index")
        ),
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], unique=False, postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("answer_citations")
    op.drop_table("provisions")
    op.drop_table("feedback")
    op.drop_table("answer_cache")
    op.drop_table("usage_daily")
    op.drop_table("regulations")
    op.drop_table("questions")
    op.drop_table("query_embedding_cache")
    op.drop_table("provider_usage_daily")
    op.drop_table("eval_runs")
    op.execute("DROP EXTENSION IF EXISTS vector")
