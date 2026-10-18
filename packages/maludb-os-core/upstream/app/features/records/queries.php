<?php
declare(strict_types=1);

/**
 * Cross-entity record components: tags and comments. Written once in the exemplar slice and
 * reused verbatim by every later slice — a tag on an invoice and a tag on a contact are the
 * same row shape, so they are the same code.
 *
 * Entity types are allowlisted here: a tagging or comment may only point at something this
 * platform knows about, and the list grows with each slice.
 */

const TAGGABLE_ENTITY_TYPES = [
    'organization', 'contact', 'deal', 'project', 'task', 'invoice', 'quote', 'expense',
    'ticket', 'document', 'appointment', 'content_item',
];

function is_taggable_entity(string $entityType): bool
{
    return in_array($entityType, TAGGABLE_ENTITY_TYPES, true);
}

/**
 * The module grant that admits someone to an entity's module. Tagging or commenting on a
 * record is gated by the record's own module, so a tag never becomes a side door.
 */
function entity_module(string $entityType): string
{
    // Every taggable record belonged to a module the kernel cut removed (2026-09-22). A kernel
    // record that gains tags or comments adds itself here and to entity_is_visible().
    return [][$entityType] ?? 'none';
}

/**
 * Can the caller see this record? Asked of the entity's own mcp_* view, so the answer is the
 * one app_can_see() gives every other caller — and an invisible record is indistinguishable
 * from one that does not exist.
 */
/**
 * A save must not clear a link its editor cannot see (owner's decision 6, 2026-09-19).
 *
 * A form's picker holds only records the editor may see, so a record linked to something hidden
 * from them — a task on a project they cannot open, a project for a customer outside their
 * contacts reach — shows "none", and the save used to write that blank back: fixing a typo
 * detached the task from its project.
 *
 * The rule: a blank leaves a HIDDEN link as it was; a blank clears a VISIBLE one (that is the
 * editor choosing "none"); any value the editor picked replaces it. The accepted cost is that
 * only someone who can see a link can clear it. The hidden id never reaches the browser — it is
 * read here, from the row the handler already loaded.
 */
function keep_hidden_link(PDO $pdo, string $entityType, ?int $requested, mixed $current): ?int
{
    if ($requested !== null || $current === null || $current === '') {
        return $requested;
    }
    return entity_is_visible($pdo, $entityType, (int) $current) ? null : (int) $current;
}

function entity_is_visible(PDO $pdo, string $entityType, int $entityId): bool
{
    $source = [][$entityType] ?? null;

    if ($source === null) {
        return false;
    }
    [$view, $idColumn] = $source;          // both from this allowlist, never from the request
    $st = $pdo->prepare("SELECT 1 FROM {$view} WHERE {$idColumn} = :id");
    $st->execute(['id' => $entityId]);
    return $st->fetchColumn() !== false;
}

// ---- tags -----------------------------------------------------------------

function find_tags(PDO $pdo): array
{
    return $pdo->query('SELECT tag_id, name, color FROM mcp_tags ORDER BY name')->fetchAll();
}

function find_taggings(PDO $pdo, string $entityType, int $entityId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT tag_id, tag_name, created_at
          FROM mcp_taggings
         WHERE entity_type = :t AND entity_id = :id
         ORDER BY tag_name
    SQL);
    $st->execute(['t' => $entityType, 'id' => $entityId]);
    return $st->fetchAll();
}

/** Tag by name: an unknown name creates the tag, which is what "add a tag" means to a user. */
function add_tagging(PDO $pdo, string $entityType, int $entityId, string $tagName, int $createdBy): array
{
    $tagName = trim($tagName);
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare('SELECT id FROM tags WHERE lower(name) = lower(:n)');
        $st->execute(['n' => $tagName]);
        $tagId = $st->fetchColumn();

        if ($tagId === false) {
            $st = $pdo->prepare('INSERT INTO tags (name) VALUES (:n) RETURNING id');
            $st->execute(['n' => $tagName]);
            $tagId = $st->fetchColumn();
        }

        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO taggings (tag_id, entity_type, entity_id, created_by)
            VALUES (:tag, :t, :id, :by)
            ON CONFLICT (tag_id, entity_type, entity_id) DO NOTHING
        SQL);
        $st->execute(['tag' => $tagId, 't' => $entityType, 'id' => $entityId, 'by' => $createdBy]);

        $pdo->commit();
        return ['tag_id' => (int) $tagId, 'name' => $tagName];
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
}

function remove_tagging(PDO $pdo, string $entityType, int $entityId, int $tagId): bool
{
    $st = $pdo->prepare('DELETE FROM taggings WHERE tag_id = :tag AND entity_type = :t AND entity_id = :id');
    $st->execute(['tag' => $tagId, 't' => $entityType, 'id' => $entityId]);
    return $st->rowCount() > 0;
}

// ---- comments -------------------------------------------------------------

function find_record_comments(PDO $pdo, string $entityType, int $entityId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT comment_id, author_member_id, author_name, body, created_at, updated_at
          FROM mcp_record_comments
         WHERE entity_type = :t AND entity_id = :id
         ORDER BY created_at
    SQL);
    $st->execute(['t' => $entityType, 'id' => $entityId]);
    return $st->fetchAll();
}

function insert_record_comment(PDO $pdo, string $entityType, int $entityId, string $body, int $authorId): array
{
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO record_comments (entity_type, entity_id, author_member_id, body)
        VALUES (:t, :id, :by, :body)
        RETURNING id AS comment_id, entity_type, entity_id, body, created_at
    SQL);
    $st->execute(['t' => $entityType, 'id' => $entityId, 'by' => $authorId, 'body' => $body]);
    return $st->fetch() ?: [];
}

function find_record_comment(PDO $pdo, int $commentId): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_record_comments WHERE comment_id = :id');
    $st->execute(['id' => $commentId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** Comments are soft-deleted: the thread keeps its shape and the trail stays true. */
function delete_record_comment(PDO $pdo, int $commentId): bool
{
    $st = $pdo->prepare('UPDATE record_comments SET deleted_at = now() WHERE id = :id AND deleted_at IS NULL');
    $st->execute(['id' => $commentId]);
    return $st->rowCount() > 0;
}
