-- 035_documents.sql
-- Documents & knowledge (new tables; cert-study resources stay untouched).
-- Files live on disk under the tenant's storage root; the database holds metadata,
-- versions, extracted text and the PostgreSQL full-text index (decided for v1; MaluDB
-- semantic indexing is a Phase 4 enhancement). Questions: DC1–DC8, H3/H4 handbooks.
-- origin_location_id FK is added in 043_locations_task_queue.sql.

BEGIN;

CREATE TABLE folders (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_id        bigint REFERENCES folders(id) ON DELETE CASCADE,
    name             text NOT NULL,
    department_id    bigint REFERENCES departments(id) ON DELETE SET NULL,
    owner_member_id  bigint REFERENCES members(id) ON DELETE SET NULL,
    archived_at      timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX folders_name_idx ON folders (COALESCE(parent_id, 0), name) WHERE archived_at IS NULL;

CREATE TABLE documents (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    folder_id           bigint REFERENCES folders(id) ON DELETE SET NULL,
    title               text NOT NULL,
    kind                text NOT NULL DEFAULT 'file'
                            CHECK (kind IN ('file', 'page', 'procedure', 'handbook')),   -- DC2, DC4
    department_id       bigint REFERENCES departments(id) ON DELETE SET NULL,
    owner_member_id     bigint REFERENCES members(id) ON DELETE SET NULL,
    current_version_id  bigint,                                      -- FK below, after versions
    mime_type           text,
    size_bytes          bigint CHECK (size_bytes >= 0),
    body_markdown       text,                                        -- page/procedure/handbook kinds
    extracted_text      text,                                        -- text pulled from files for search
    origin              text NOT NULL DEFAULT 'upload'
                            CHECK (origin IN ('upload', 'desk_import', 'generated', 'email', 'agent')),
    origin_location_id  bigint,                                      -- FK in 043 (DC8)
    search_tsv          tsvector,
    archived_at         timestamptz,
    deleted_at          timestamptz,                                 -- soft delete; DC7 audit in activity
    created_by          bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX documents_folder_idx     ON documents (folder_id) WHERE deleted_at IS NULL;
CREATE INDEX documents_kind_idx       ON documents (kind, department_id) WHERE deleted_at IS NULL;
CREATE INDEX documents_title_trgm     ON documents USING gin (title gin_trgm_ops);
CREATE INDEX documents_search_idx     ON documents USING gin (search_tsv);
CREATE INDEX documents_origin_idx     ON documents (origin) WHERE origin = 'desk_import';

CREATE TABLE document_versions (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id    bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_no     integer NOT NULL CHECK (version_no > 0),
    storage_path   text,                                             -- null for page kinds
    sha256         text,
    size_bytes     bigint CHECK (size_bytes >= 0),
    mime_type      text,
    body_markdown  text,                                             -- DC6 diff source for pages
    change_note    text,
    created_by     bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_no)
);

ALTER TABLE documents
    ADD CONSTRAINT documents_current_version_fk
    FOREIGN KEY (current_version_id) REFERENCES document_versions(id) ON DELETE SET NULL;

-- A document attached to any record (DC3): contact, invoice, project, ticket, expense, content.
CREATE TABLE document_links (
    document_id  bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    entity_type  text   NOT NULL,
    entity_id    bigint NOT NULL,
    linked_by    bigint REFERENCES members(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, entity_type, entity_id)
);
CREATE INDEX document_links_entity_idx ON document_links (entity_type, entity_id);

ALTER TABLE departments
    ADD CONSTRAINT departments_handbook_fk
    FOREIGN KEY (handbook_document_id) REFERENCES documents(id) ON DELETE SET NULL;

CREATE OR REPLACE FUNCTION documents_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.body_markdown, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.extracted_text, '')), 'C');
    RETURN NEW;
END$$;
CREATE TRIGGER documents_tsv_trg BEFORE INSERT OR UPDATE OF title, body_markdown, extracted_text
    ON documents FOR EACH ROW EXECUTE FUNCTION documents_tsv_update();

-- Foreign-key lookup indexes
CREATE INDEX folders_parent_idx ON folders (parent_id);
CREATE INDEX documents_department_idx ON documents (department_id);
CREATE INDEX documents_owner_idx ON documents (owner_member_id);

COMMIT;
