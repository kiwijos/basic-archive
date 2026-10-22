"""Initial schema: subjects, names, relations, documents, images, transcriptions, outbox.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Every uncertain date is kept as written plus the earliest and latest date it could mean.
SCHEMA = """
CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION forbid_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION USING MESSAGE = TG_TABLE_NAME || ' is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TABLE subject (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL CHECK (kind IN ('ship', 'organisation')),
    notes text,
    external_refs jsonb NOT NULL DEFAULT '[]',
    source_id text,
    source_system text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);
CREATE UNIQUE INDEX subject_source_key ON subject (source_system, source_id) WHERE source_id IS NOT NULL;

CREATE TABLE ship (
    subject_id uuid PRIMARY KEY REFERENCES subject (id) ON DELETE CASCADE,
    ship_type text,
    tonnage numeric(10, 2),
    launched_date_text text,
    launched_date_from date,
    launched_date_to date CHECK (launched_date_to >= launched_date_from),
    fate text,
    fate_date_text text,
    fate_date_from date,
    fate_date_to date CHECK (fate_date_to >= fate_date_from)
);

CREATE TABLE organisation (
    subject_id uuid PRIMARY KEY REFERENCES subject (id) ON DELETE CASCADE,
    organisation_type text,
    place text
);

CREATE TABLE subject_name (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id uuid NOT NULL REFERENCES subject (id),
    name text NOT NULL CHECK (btrim(name) <> ''),
    name_type text NOT NULL DEFAULT 'given' CHECK (name_type IN ('given', 'alias')),
    date_text text,
    date_from date,
    date_to date CHECK (date_to >= date_from),
    source text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);
CREATE INDEX subject_name_subject_id_idx ON subject_name (subject_id);

CREATE TABLE relation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    from_subject_id uuid NOT NULL REFERENCES subject (id),
    predicate text NOT NULL CHECK (predicate IN ('built_by', 'owned_by', 'operated_by', 'rebuilt_from')),
    to_subject_id uuid NOT NULL REFERENCES subject (id),
    place text,
    date_text text,
    date_from date,
    date_to date CHECK (date_to >= date_from),
    source text,
    confidence numeric(3, 2) CHECK (confidence BETWEEN 0 AND 1),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CHECK (from_subject_id <> to_subject_id)
);
CREATE INDEX relation_from_idx ON relation (from_subject_id);
CREATE INDEX relation_to_idx ON relation (to_subject_id);

CREATE TABLE document (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    document_type text,
    date_text text,
    date_from date,
    date_to date CHECK (date_to >= date_from),
    physical_location text,
    description text,
    external_refs jsonb NOT NULL DEFAULT '[]',
    source_id text,
    source_system text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);
CREATE UNIQUE INDEX document_source_key ON document (source_system, source_id) WHERE source_id IS NOT NULL;

CREATE TABLE document_subject (
    document_id uuid NOT NULL REFERENCES document (id),
    subject_id uuid NOT NULL REFERENCES subject (id),
    role text,
    PRIMARY KEY (document_id, subject_id)
);

CREATE TABLE image (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES document (id),
    page_no integer NOT NULL DEFAULT 1 CHECK (page_no >= 1),
    bucket text,
    object_key text,
    sha256 char(64),
    mime text,
    width integer,
    height integer,
    original_filename text,
    review_status text NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'ocr_done', 'verified', 'failed')),
    rights text NOT NULL DEFAULT 'reserved' CHECK (rights IN ('CC0', 'PDM', 'CC BY', 'reserved')),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    UNIQUE (document_id, page_no)
);
CREATE INDEX image_sha256_idx ON image (sha256);

CREATE TABLE transcription (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id uuid NOT NULL REFERENCES image (id),
    source text NOT NULL CHECK (source IN ('machine', 'human')),
    text text NOT NULL,
    engine text,
    engine_version text,
    language text,
    confidence numeric(4, 3) CHECK (confidence BETWEEN 0 AND 1),
    created_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source <> 'human' OR created_by IS NOT NULL)
);
CREATE INDEX transcription_image_idx ON transcription (image_id, created_at);
CREATE TRIGGER transcription_append_only BEFORE UPDATE OR DELETE ON transcription
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

CREATE TABLE outbox (
    id bigserial PRIMARY KEY,
    event_type text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);
CREATE INDEX outbox_unpublished_idx ON outbox (id) WHERE published_at IS NULL;

CREATE TRIGGER subject_updated BEFORE UPDATE ON subject FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER subject_name_updated BEFORE UPDATE ON subject_name FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER relation_updated BEFORE UPDATE ON relation FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER document_updated BEFORE UPDATE ON document FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER image_updated BEFORE UPDATE ON image FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'archive_readonly') THEN
        CREATE ROLE archive_readonly NOLOGIN;
    END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO archive_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO archive_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO archive_readonly;
"""

TABLES = [
    "outbox", "transcription", "image", "document_subject", "document", "relation",
    "subject_name", "organisation", "ship", "subject",
]


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SCHEMA)


def downgrade() -> None:
    connection = op.get_bind()
    for table in TABLES:
        connection.exec_driver_sql(f"DROP TABLE {table}")
    connection.exec_driver_sql("DROP FUNCTION set_updated_at()")
    connection.exec_driver_sql("DROP FUNCTION forbid_change()")
