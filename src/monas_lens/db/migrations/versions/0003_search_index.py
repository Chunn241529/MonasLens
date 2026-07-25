"""Create the lexical search projection and FTS5 index."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_search_index"
down_revision: str | None = "0002_structural_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("qualified_name", sa.Text(), nullable=True),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
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
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            name="ux_search_documents_entity",
        ),
    )
    op.create_index(
        "ix_search_documents_repository_id",
        "search_documents",
        ["repository_id"],
    )
    op.create_index(
        "ix_search_documents_file_id",
        "search_documents",
        ["file_id"],
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE search_documents_fts USING fts5(
            relative_path,
            name,
            qualified_name,
            signature,
            body,
            content='search_documents',
            content_rowid='id',
            tokenize="unicode61 remove_diacritics 2 tokenchars '_'",
            prefix='2 3 4'
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER search_documents_ai AFTER INSERT ON search_documents BEGIN
            INSERT INTO search_documents_fts(
                rowid,
                relative_path,
                name,
                qualified_name,
                signature,
                body
            )
            VALUES (
                new.id,
                new.relative_path,
                new.name,
                new.qualified_name,
                new.signature,
                new.body
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER search_documents_ad AFTER DELETE ON search_documents BEGIN
            INSERT INTO search_documents_fts(
                search_documents_fts,
                rowid,
                relative_path,
                name,
                qualified_name,
                signature,
                body
            )
            VALUES (
                'delete',
                old.id,
                old.relative_path,
                old.name,
                old.qualified_name,
                old.signature,
                old.body
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER search_documents_au AFTER UPDATE ON search_documents BEGIN
            INSERT INTO search_documents_fts(
                search_documents_fts,
                rowid,
                relative_path,
                name,
                qualified_name,
                signature,
                body
            )
            VALUES (
                'delete',
                old.id,
                old.relative_path,
                old.name,
                old.qualified_name,
                old.signature,
                old.body
            );
            INSERT INTO search_documents_fts(
                rowid,
                relative_path,
                name,
                qualified_name,
                signature,
                body
            )
            VALUES (
                new.id,
                new.relative_path,
                new.name,
                new.qualified_name,
                new.signature,
                new.body
            );
        END
        """
    )
    _backfill_existing_index()


def downgrade() -> None:
    op.execute("DROP TRIGGER search_documents_au")
    op.execute("DROP TRIGGER search_documents_ad")
    op.execute("DROP TRIGGER search_documents_ai")
    op.execute("DROP TABLE search_documents_fts")
    op.drop_index("ix_search_documents_file_id", table_name="search_documents")
    op.drop_index("ix_search_documents_repository_id", table_name="search_documents")
    op.drop_table("search_documents")


def _backfill_existing_index() -> None:
    op.execute(
        """
        INSERT INTO search_documents(
            repository_id,
            file_id,
            entity_type,
            entity_id,
            language,
            kind,
            relative_path,
            body,
            start_line,
            end_line
        )
        SELECT
            f.repository_id,
            f.id,
            'file',
            f.id,
            f.language,
            'file',
            f.relative_path,
            '',
            1,
            MAX(
                COALESCE(
                    (SELECT MAX(s.end_line) FROM symbols AS s WHERE s.file_id = f.id),
                    1
                ),
                COALESCE(
                    (SELECT MAX(c.end_line) FROM chunks AS c WHERE c.file_id = f.id),
                    1
                ),
                COALESCE(
                    (SELECT MAX(sf.end_line) FROM syntax_facts AS sf WHERE sf.file_id = f.id),
                    1
                )
            )
        FROM files AS f
        """
    )
    op.execute(
        """
        INSERT INTO search_documents(
            repository_id,
            file_id,
            entity_type,
            entity_id,
            language,
            kind,
            relative_path,
            name,
            qualified_name,
            signature,
            body,
            start_line,
            end_line
        )
        SELECT
            f.repository_id,
            s.file_id,
            'symbol',
            s.id,
            s.language,
            s.kind,
            f.relative_path,
            s.name,
            s.qualified_name,
            s.signature,
            COALESCE(s.docstring, ''),
            s.start_line,
            s.end_line
        FROM symbols AS s
        JOIN files AS f ON f.id = s.file_id
        """
    )
    op.execute(
        """
        INSERT INTO search_documents(
            repository_id,
            file_id,
            entity_type,
            entity_id,
            language,
            kind,
            relative_path,
            name,
            qualified_name,
            signature,
            body,
            start_line,
            end_line
        )
        SELECT
            f.repository_id,
            c.file_id,
            'chunk',
            c.id,
            f.language,
            c.kind,
            f.relative_path,
            s.name,
            s.qualified_name,
            s.signature,
            c.source_text,
            c.start_line,
            c.end_line
        FROM chunks AS c
        JOIN files AS f ON f.id = c.file_id
        LEFT JOIN symbols AS s ON s.id = c.symbol_id
        """
    )
    op.execute(
        """
        INSERT INTO search_documents(
            repository_id,
            file_id,
            entity_type,
            entity_id,
            language,
            kind,
            relative_path,
            body,
            start_line,
            end_line
        )
        SELECT
            f.repository_id,
            sf.file_id,
            'fact',
            sf.id,
            f.language,
            sf.kind,
            f.relative_path,
            sf.target_text,
            sf.start_line,
            sf.end_line
        FROM syntax_facts AS sf
        JOIN files AS f ON f.id = sf.file_id
        """
    )
