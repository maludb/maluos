# Build spec: Documents — "where is the file, the procedure, the reference?"

2026-09-19 · Module 3 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/035 (`folders`, `documents`, `document_versions`, `document_links`; views `mcp_folders`,
`mcp_documents`, `mcp_document_versions`, `mcp_document_links`). No migration needed. Manifest
"Documents": 6 screens, 11 actions built here; `desk_import_confirm` / `_reject` wait for phase 6
(nothing feeds `desk_imports`). Tools: `find_documents`, `get_document`, `record_documents`,
`compare_document_versions`.

## Two kinds of document
- **A file** (`kind = file`): uploaded bytes. Each upload of a new file onto the same document is
  a new **version** (`document_versions.storage_path`, `sha256`, `size_bytes`, `mime_type`).
- **A page** (`kind = page | procedure | handbook`): written here in Markdown
  (`body_markdown`). Saving a changed body writes a new version holding that body.
`documents.current_version_id` points at the live one; restoring a version writes a NEW version
that copies the old one — history is never rewritten.

## Files (owner's decision 10)
- **25 MB**; the type is decided from the file's **own bytes** (`finfo`), never its name or the
  browser's claim; allow-list: PDF, Word / Excel / PowerPoint (OOXML and legacy), OpenDocument
  text / sheet / presentation, plain text, Markdown, CSV, PNG, JPEG, GIF, WebP. Executables,
  scripts, HTML, SVG and archives are refused. (An OOXML file *is* a zip; it is accepted only
  when `finfo` names the Office type.)
- Stored at `storage_root()/documents/<document id>/<sha256>.<ext>` — outside the web root, the
  name derived from the content, the extension from the detected type. Same shape as agent photos.
- **Served only through `html/documents/download.php`**, which finds the document through
  `mcp_documents` (so the caller must be able to see it), sends `Content-Disposition: attachment`
  and `nosniff`. The browser reaches it through the web app's `/api/download` relay, whose
  allow-list gains this one path.
- **Upload is screen-only** (manifest decision 6): `upload.php` refuses an action token.
- **Text for search**: plain text / Markdown / CSV as they are; PDF through `pdftotext`
  (**installed: poppler-utils**); DOCX by reading `word/document.xml`. Capped at 1 MB of text;
  extraction failing never fails the upload. It feeds `documents.extracted_text`, which the
  existing trigger folds into `search_tsv`.

## Visibility and who may do what
`mcp_documents` / `mcp_folders` apply `app_can_see('documents', owner, department, …)`: the owner,
a dept-admin inside the document's department, a holder of the documents grant, or someone it was
shared with. Reading follows the view. Writing: manifest's `mod:documents` = `require_module`;
`own, mod:documents` = the owner, or a grant holder who can see it; delete = the owner or an
admin. A deleted document is **soft-deleted** (`deleted_at`) and its files stay for 30 days
(purging is a later job — recorded OPEN).

## Links
`document_links (document_id, entity_type, entity_id)`. Accepted types and the view each must be
visible through: `organization`, `contact`, `deal`, `project`, `task`, `invoice`, `quote`,
`expense`, `ticket`, `content_item`. A link to a record the caller cannot see is refused.
`record_documents` (tool) and a "Documents" card can then be added to those records' pages —
this slice adds the card to **projects, companies and expenses** (Expenses' receipt button has
been a placeholder waiting for this module).

## Screens
| Screen | React route | PHP read |
| --- | --- | --- |
| `documents-list` | `/documents?folder=&q=&kind=&department=&origin=` | `html/documents/index.php` — folders of the current folder, documents, breadcrumb; `q` is full-text |
| `document-upload` | `/documents/upload?folder=&link_type=&link_id=` | `…/upload-form.php` |
| `page-add` | `/documents/pages/new?kind=&title=&department=` | `…/pages/form.php` |
| `document-view` | `/documents/{id}` | `…/view.php` — details, the body (a page) or the download (a file), links, versions |
| `document-edit` | `/documents/{id}/edit` | `…/form.php` — title, folder, department; a page's body; a file's replacement upload |
| `document-versions` | `/documents/{id}/versions?from=&to=` | `…/versions.php` — the list, and for a page a line diff between two versions |

## Actions (handlers in `html/documents/`)
`document_upload` → `upload.php`; `page_create` → `pages/save.php`; `document_update` →
`save.php`; `document_move`; `document_restore_version` → `restore.php`; `document_link` /
`document_unlink`; `document_archive`; `document_delete`; `folder_save`; `folder_delete` (must be
empty). Events as the manifest names them.
