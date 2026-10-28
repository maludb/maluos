<?php
declare(strict_types=1);

/**
 * The prompt library (db/070, "A prompt library"; db/071, "Model parameters belong to the
 * prompt version"). A system_prompts row is reusable across agents; each version is the whole
 * instruction unit — wording AND model parameters (temperature, max_tokens, thinking_budget,
 * ...) — and is immutable by trigger once written (system_prompt_versions_no_edit guards both
 * `body` and `parameters`). A new wording, or a new setting, is always a new version.
 *
 * agent_config_versions.system_prompt_id/system_prompt_version point at the version a
 * configuration drew from; job_description and harness_config keep the RESOLVED copies (the
 * db/071 trigger `agent_config_versions_harness_mirror` writes harness_config from the cited
 * version on every insert/update of the pointer — this file never sets it directly for a
 * config that cites a prompt). Editing the library later must never change what a past
 * configuration is recorded as having said.
 *
 * Reads go through mcp_system_prompts / mcp_system_prompt_versions (db/070, db/071 — both
 * app_is_insider()-gated). find_agent()/find_agent_version() in queries.php additionally join
 * back to the base agent_profiles / agent_config_versions tables for the three identity columns
 * and the two prompt-pointer columns db/070 did not add to mcp_agents / mcp_agent_config_versions
 * — safe because that join only adds columns to a row the mcp_* view already decided the caller
 * may see, never a new row.
 */

const PROMPT_PARAMETER_NAMED_KEYS = ['temperature', 'max_tokens', 'thinking_budget'];

function find_system_prompts(PDO $pdo, bool $includeArchived = true): array
{
    $sql = 'SELECT * FROM mcp_system_prompts' . ($includeArchived ? '' : ' WHERE archived_at IS NULL')
         . ' ORDER BY archived_at NULLS FIRST, name';
    return $pdo->query($sql)->fetchAll();
}

function find_system_prompt(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_system_prompts WHERE system_prompt_id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** Non-archived prompts for a picker (agent hire/edit form). */
function find_active_system_prompt_options(PDO $pdo): array
{
    return $pdo->query("SELECT system_prompt_id, prompt_key, name, current_version
                           FROM mcp_system_prompts WHERE archived_at IS NULL ORDER BY name")->fetchAll();
}

function find_system_prompt_versions(PDO $pdo, int $promptId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_system_prompt_versions WHERE system_prompt_id = :id ORDER BY version_no DESC');
    $st->execute(['id' => $promptId]);
    return $st->fetchAll();
}

function find_system_prompt_version(PDO $pdo, int $promptId, int $versionNo): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_system_prompt_versions WHERE system_prompt_id = :id AND version_no = :vno');
    $st->execute(['id' => $promptId, 'vno' => $versionNo]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** How many agent configurations (any version, live or not) have ever cited this prompt —
 *  "used by N agent configurations" (system-prompt-view). */
function count_configs_citing_prompt(PDO $pdo, int $promptId): int
{
    $st = $pdo->prepare('SELECT count(*) FROM agent_config_versions WHERE system_prompt_id = :id');
    $st->execute(['id' => $promptId]);
    return (int) $st->fetchColumn();
}

/** The agents whose LIVE (active) configuration cites this prompt — named in the archive
 *  refusal, the way retire_location() names what blocks it. */
function agents_citing_prompt(PDO $pdo, int $promptId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT DISTINCT m.display_name
          FROM agent_profiles ap
          JOIN agent_config_versions v ON v.id = ap.current_config_version_id
          JOIN members m ON m.id = ap.member_id
         WHERE v.system_prompt_id = :id AND ap.status <> 'offboarded'
         ORDER BY m.display_name
    SQL);
    $st->execute(['id' => $promptId]);
    return $st->fetchAll(PDO::FETCH_COLUMN);
}

/** Creates the prompt AND its version 1 in one transaction — a prompt with no body cannot exist.
 *  $f: prompt_key, name, description, role_key, body, parameters (array). */
function create_system_prompt(PDO $pdo, array $f, int $by): array
{
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO system_prompts (prompt_key, name, description, role_key, current_version, created_by)
            VALUES (:key, :name, :desc, :role, 1, :by)
            RETURNING id
        SQL);
        $st->execute([
            'key' => $f['prompt_key'], 'name' => $f['name'], 'desc' => $f['description'] ?: null,
            'role' => $f['role_key'] ?: null, 'by' => $by,
        ]);
        $id = (int) $st->fetchColumn();

        $pdo->prepare(<<<'SQL'
            INSERT INTO system_prompt_versions (prompt_id, version_no, body, change_note, parameters, created_by)
            VALUES (:id, 1, :body, 'Initial version', :params, :by)
        SQL)->execute([
            'id' => $id, 'body' => $f['body'], 'params' => json_object_encode($f['parameters'] ?? []), 'by' => $by,
        ]);

        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
    return find_system_prompt($pdo, $id) ?? [];
}

/** Metadata only — prompt_key, name, description, role_key. A version's body and parameters can
 *  never be edited here (system_prompt_versions_no_edit); see create_system_prompt_version(). */
function update_system_prompt_meta(PDO $pdo, int $id, array $f): array
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE system_prompts
           SET prompt_key = :key, name = :name, description = :desc, role_key = :role, updated_at = now()
         WHERE id = :id
        RETURNING id
    SQL);
    $st->execute([
        'key' => $f['prompt_key'], 'name' => $f['name'], 'desc' => $f['description'] ?: null,
        'role' => $f['role_key'] ?: null, 'id' => $id,
    ]);
    $row = $st->fetch();
    return $row === false ? [] : (find_system_prompt($pdo, $id) ?? []);
}

/** Always a new version, never an edit — the trigger refuses an edit anyway; this is the
 *  application-level guarantee that backs it. $f: body, change_note, parameters (array). */
function create_system_prompt_version(PDO $pdo, int $promptId, array $f, int $by): array
{
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare('SELECT coalesce(max(version_no), 0) + 1 FROM system_prompt_versions WHERE prompt_id = :id');
        $st->execute(['id' => $promptId]);
        $versionNo = (int) $st->fetchColumn();

        $pdo->prepare(<<<'SQL'
            INSERT INTO system_prompt_versions (prompt_id, version_no, body, change_note, parameters, created_by)
            VALUES (:id, :vno, :body, :note, :params, :by)
        SQL)->execute([
            'id' => $promptId, 'vno' => $versionNo, 'body' => $f['body'],
            'note' => $f['change_note'] ?: null, 'params' => json_object_encode($f['parameters'] ?? []), 'by' => $by,
        ]);

        $pdo->prepare('UPDATE system_prompts SET current_version = :vno, updated_at = now() WHERE id = :id')
            ->execute(['vno' => $versionNo, 'id' => $promptId]);

        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
    return find_system_prompt($pdo, $promptId) ?? [];
}

/**
 * Refused while a live agent configuration cites it (manifest wording) — named, the way
 * retire_location() names what blocks it. Restoring (archived=false) is never blocked.
 */
function archive_system_prompt(PDO $pdo, int $id, bool $archived): array
{
    if ($archived) {
        $citedBy = agents_citing_prompt($pdo, $id);
        if ($citedBy !== []) {
            throw new RuntimeException(
                'This prompt cannot be archived — it is cited by a live configuration for: '
                . implode(', ', $citedBy) . '.'
            );
        }
    }
    $st = $pdo->prepare('UPDATE system_prompts SET archived_at = CASE WHEN :a THEN now() END, updated_at = now()
                          WHERE id = :id RETURNING id');
    $st->execute(['a' => $archived ? 't' : 'f', 'id' => $id]);
    $row = $st->fetch();
    return $row === false ? [] : (find_system_prompt($pdo, $id) ?? []);
}

// --------------------------------------------------------------------------
// Parameters: named fields for the two everyone compares plus thinking_budget, and a small
// JSON textarea for anything else the harness takes (top_p, stop_sequences, ...). Round-trips:
// prefill splits a stored jsonb object back into the named fields + a JSON blob of the rest.
// --------------------------------------------------------------------------

/** @return array{0: array, 1: array} the assembled parameters object and any errors */
function prompt_parameters_from_request(): array
{
    $errors = [];
    $parameters = [];

    $temp = trim(request_string('temperature'));
    if ($temp !== '') {
        if (!is_numeric($temp) || (float) $temp < 0) {
            $errors[] = 'Temperature must be a non-negative number.';
        } else {
            $parameters['temperature'] = (float) $temp;
        }
    }
    $maxTokens = trim(request_string('max_tokens'));
    if ($maxTokens !== '') {
        $filtered = filter_var($maxTokens, FILTER_VALIDATE_INT);
        if ($filtered === false || $filtered < 1) {
            $errors[] = 'Max tokens must be a whole number greater than zero.';
        } else {
            $parameters['max_tokens'] = $filtered;
        }
    }
    $thinkingBudget = trim(request_string('thinking_budget'));
    if ($thinkingBudget !== '') {
        $filtered = filter_var($thinkingBudget, FILTER_VALIDATE_INT);
        if ($filtered === false || $filtered < 0) {
            $errors[] = 'Thinking budget must be a whole number, zero or more.';
        } else {
            $parameters['thinking_budget'] = $filtered;
        }
    }

    $extraRaw = trim(request_string('extra_parameters'));
    if ($extraRaw !== '') {
        $decoded = json_decode($extraRaw, true);
        if (!is_array($decoded) || ($decoded !== [] && array_is_list($decoded))) {
            $errors[] = 'Extra parameters must be a JSON object, e.g. {"top_p": 0.9}.';
        } else {
            foreach ($decoded as $k => $v) {
                if (!array_key_exists($k, $parameters)) {
                    $parameters[$k] = $v;
                }
            }
        }
    }

    return [$parameters, $errors];
}

/** Splits a stored parameters object back into the named fields + a JSON blob of whatever else
 *  is in it, for prefilling the new-version form from the current version. */
function split_prompt_parameters(array $parameters): array
{
    $extra = array_diff_key($parameters, array_flip(PROMPT_PARAMETER_NAMED_KEYS));
    return [
        'temperature' => $parameters['temperature'] ?? '',
        'max_tokens' => $parameters['max_tokens'] ?? '',
        'thinking_budget' => $parameters['thinking_budget'] ?? '',
        'extra_parameters' => $extra === [] ? '' : json_encode($extra, JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT),
    ];
}

/** A short "temp 0.2 · 4096 tok" summary for a table cell. Empty string when parameters is {}. */
function prompt_parameters_summary(array $parameters): string
{
    $parts = [];
    if (isset($parameters['temperature'])) {
        $parts[] = 'temp ' . $parameters['temperature'];
    }
    if (isset($parameters['max_tokens'])) {
        $parts[] = $parameters['max_tokens'] . ' tok';
    }
    if (isset($parameters['thinking_budget'])) {
        $parts[] = $parameters['thinking_budget'] . ' think';
    }
    $extraCount = count(array_diff_key($parameters, array_flip(PROMPT_PARAMETER_NAMED_KEYS)));
    if ($extraCount > 0) {
        $parts[] = '+' . $extraCount . ' more';
    }
    return implode(' · ', $parts);
}

// --------------------------------------------------------------------------
// Field parsing
// --------------------------------------------------------------------------
function system_prompt_fields_from_request(): array
{
    $errors = [];
    $fields = [
        'prompt_key' => trim(request_string('prompt_key')),
        'name' => request_string('name'),
        'description' => request_string('description') ?: null,
        'role_key' => request_string('role_key') ?: null,
        'body' => request_string('system_prompt'),
    ];
    if ($fields['prompt_key'] === '' || mb_strlen($fields['prompt_key']) > 100) {
        $errors[] = 'A prompt needs a short unique key (up to 100 characters).';
    }
    if ($fields['name'] === '') {
        $errors[] = 'A prompt needs a name.';
    }
    [$parameters, $paramErrors] = prompt_parameters_from_request();
    $fields['parameters'] = $parameters;
    $errors = array_merge($errors, $paramErrors);
    return [$fields, $errors];
}

function system_prompt_version_fields_from_request(): array
{
    $errors = [];
    $fields = [
        'body' => request_string('body'),
        'change_note' => request_string('change_note') ?: null,
    ];
    if ($fields['body'] === '') {
        $errors[] = 'A version needs a body — this is the text the model receives.';
    }
    [$parameters, $paramErrors] = prompt_parameters_from_request();
    $fields['parameters'] = $parameters;
    $errors = array_merge($errors, $paramErrors);
    return [$fields, $errors];
}

/**
 * Resolves an agent hire/config form's chosen library prompt (if any) into job_description and
 * the system_prompt_id/system_prompt_version pointer. Leaves job_description untouched and both
 * pointer fields null when no prompt was chosen — "written inline" stays permitted. Model
 * parameters for the inline case come from the form's own fields (already in $fields via
 * agent_hire_fields_from_request()/agent_config_fields_from_request()); a cited version's
 * parameters are resolved by the db/071 trigger, not here, so $fields['parameters'] is simply
 * ignored downstream once a prompt is cited.
 *
 * @return array{0: array, 1: array} the fields (with job_description/pointers resolved) and errors
 */
function resolve_agent_prompt_selection(PDO $pdo, array $fields): array
{
    $errors = [];
    $fields['system_prompt_version'] = null;
    if (($fields['system_prompt_id'] ?? null) === null) {
        return [$fields, $errors];
    }
    $prompt = find_system_prompt($pdo, (int) $fields['system_prompt_id']);
    if ($prompt === null) {
        $errors[] = 'Choose a prompt that exists.';
        return [$fields, $errors];
    }
    if ($prompt['archived_at'] !== null) {
        $errors[] = 'That prompt is archived — choose an active one, or write inline.';
        return [$fields, $errors];
    }
    $version = find_system_prompt_version($pdo, (int) $prompt['system_prompt_id'], (int) $prompt['current_version']);
    if ($version === null) {
        $errors[] = 'That prompt has no current version.';
        return [$fields, $errors];
    }
    $fields['job_description'] = $version['body'];
    $fields['system_prompt_version'] = (int) $version['version_no'];
    return [$fields, $errors];
}
