"""Track the extractor version used for indexed file records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_extractor_version"
down_revision: str | None = "0004_relationship_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("indexed_extractor_version", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("files", "indexed_extractor_version")
