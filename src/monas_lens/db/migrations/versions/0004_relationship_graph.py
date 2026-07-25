"""Create the conservative relationship graph."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_relationship_graph"
down_revision: str | None = "0003_search_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column(
            "graph_dirty",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "repositories",
        sa.Column("graph_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "relationships",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("fact_id", sa.String(length=64), nullable=False),
        sa.Column("source_file_id", sa.String(length=64), nullable=False),
        sa.Column("source_symbol_id", sa.String(length=64), nullable=True),
        sa.Column("target_file_id", sa.String(length=64), nullable=False),
        sa.Column("target_symbol_id", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("resolution_strategy", sa.String(length=64), nullable=False),
        sa.Column("raw_target", sa.String(length=500), nullable=False),
        sa.Column("normalized_target", sa.String(length=500), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["fact_id"],
            ["syntax_facts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["files.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_symbol_id"],
            ["symbols.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_file_id"],
            ["files.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_symbol_id"],
            ["symbols.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "repository_id",
        "fact_id",
        "source_file_id",
        "source_symbol_id",
        "target_file_id",
        "target_symbol_id",
        "kind",
    ):
        op.create_index(f"ix_relationships_{column}", "relationships", [column])

    op.create_table(
        "resolution_diagnostics",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("fact_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("fact_kind", sa.String(length=32), nullable=False),
        sa.Column("raw_target", sa.String(length=500), nullable=False),
        sa.Column("normalized_target", sa.String(length=500), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["fact_id"],
            ["syntax_facts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("repository_id", "file_id", "fact_id", "reason"):
        op.create_index(
            f"ix_resolution_diagnostics_{column}",
            "resolution_diagnostics",
            [column],
        )


def downgrade() -> None:
    for column in ("reason", "fact_id", "file_id", "repository_id"):
        op.drop_index(
            f"ix_resolution_diagnostics_{column}",
            table_name="resolution_diagnostics",
        )
    op.drop_table("resolution_diagnostics")
    for column in (
        "kind",
        "target_symbol_id",
        "target_file_id",
        "source_symbol_id",
        "source_file_id",
        "fact_id",
        "repository_id",
    ):
        op.drop_index(f"ix_relationships_{column}", table_name="relationships")
    op.drop_table("relationships")
    op.drop_column("repositories", "graph_updated_at")
    op.drop_column("repositories", "graph_dirty")
