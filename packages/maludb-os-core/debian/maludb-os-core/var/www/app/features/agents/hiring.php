<?php
declare(strict_types=1);

/**
 * The hire transaction and config-version lifecycle (build spec: docs/build-specs/agent-hr.md,
 * "Hiring — the screen this slice exists for" and "Config versions are immutable").
 *
 * hire_agent() creates FOUR things in one transaction: the members row (member_kind='agent',
 * business_role='user' — members_agent_is_user_check requires it), the agent_profiles row,
 * version 1 in agent_config_versions, and the location_residents row at the home location (only
 * when a home location was given). Hiring an agent into an unmanaged location is refused by the
 * db/067 trigger on location_residents — caught here and re-thrown as a field-readable message.
 *
 * create_config_version() never edits a version; it always creates version_no + 1, copying
 * forward what was not changed and snapshotting the CURRENT (live) tool_grants and duties as
 * jsonb — so grants made through the Tools tab and duties added on this same edit are captured
 * exactly as they stand the moment the version is written.
 */

/** The live tool_grants and duties for an agent, as the two jsonb blobs a config version
 *  snapshots them into. @return array{0: string, 1: string} */
function agent_snapshot_json(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare("SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM
        (SELECT application_endpoint_id, tool_name, constraints FROM agent_tool_grants
          WHERE agent_member_id = :id AND revoked_at IS NULL) t");
    $st->execute(['id' => $memberId]);
    $tools = (string) $st->fetchColumn();

    $st = $pdo->prepare("SELECT coalesce(jsonb_agg(d), '[]'::jsonb) FROM
        (SELECT name, instructions, schedule_cron, timezone FROM agent_duties
          WHERE agent_member_id = :id) d");
    $st->execute(['id' => $memberId]);
    $duties = (string) $st->fetchColumn();

    return [$tools, $duties];
}

/** @param array $f name, email, job_title, department_id, manager_member_id, model_id,
 *                  job_description, monthly_budget_amount, budget_currency, home_location_id,
 *                  system_prompt_id, system_prompt_version (both set together or both null —
 *                  resolve_agent_prompt_selection() in prompts.php produces this pair),
 *                  parameters (array, inline model settings — ignored when a prompt is cited;
 *                  the db/071 trigger overwrites harness_config from the cited version instead),
 *                  tools (array of [application_endpoint_id, tool_name, constraints]), duties (array of
 *                  [name, instructions, schedule_cron, timezone]), agent_kind ('orchestrator' or
 *                  'subagent', default 'subagent' — db/072), subagents (array of member ids for
 *                  the starting roster, meaningful only when agent_kind is 'orchestrator';
 *                  refused by the agent_subagents_one_level trigger if any is not itself a
 *                  subagent, rolling back the whole hire)
 */
function hire_agent(PDO $pdo, array $f, int $by): array
{
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO members (email, password_hash, display_name, member_kind, business_role,
                                  job_title, is_external, status, email_verified_at)
            VALUES (:email, NULL, :name, 'agent', 'user', :job_title, false, 'active', now())
            RETURNING id
        SQL);
        $st->execute(['email' => $f['email'], 'name' => $f['name'], 'job_title' => $f['job_title']]);
        $memberId = (int) $st->fetchColumn();

        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO agent_profiles
                (member_id, manager_member_id, status, model_id, monthly_budget_amount,
                 budget_currency, home_location_id, hired_at, hired_by,
                 description, role_key, agent_kind, phone_number)
            VALUES (:id, :mgr, 'active', :model, :budget, :cur, :home, now(), :by,
                    :desc, :role, :kind, :phone)
        SQL);
        $st->execute([
            'id' => $memberId, 'mgr' => $f['manager_member_id'], 'model' => $f['model_id'],
            'budget' => $f['monthly_budget_amount'] ?: null, 'cur' => $f['budget_currency'] ?: 'USD',
            'home' => $f['home_location_id'] ?: null, 'by' => $by,
            'desc' => $f['description'] ?? null, 'role' => $f['role_key'] ?? null,
            'kind' => $f['agent_kind'] ?? 'subagent', 'phone' => $f['phone_number'] ?? null,
        ]);

        $pdo->prepare('INSERT INTO department_members (department_id, member_id, is_admin, is_primary)
                        VALUES (:d, :m, false, true)')
            ->execute(['d' => $f['department_id'], 'm' => $memberId]);

        if (($f['home_location_id'] ?? null) !== null) {
            // Triggers here (db/067): an agent may only reside where the effective control is
            // 'managed'. A violation raises with the location's own name in the message, which
            // we surface verbatim as the field error below.
            $pdo->prepare('INSERT INTO location_residents (location_id, member_id, is_primary)
                            VALUES (:loc, :m, true)')
                ->execute(['loc' => $f['home_location_id'], 'm' => $memberId]);
        }

        foreach (($f['tools'] ?? []) as $tool) {
            $pdo->prepare(<<<'SQL'
                INSERT INTO agent_tool_grants (agent_member_id, application_endpoint_id, tool_name, constraints, granted_by)
                VALUES (:m, :endpoint, :tool, :constraints, :by)
            SQL)->execute([
                'm' => $memberId, 'endpoint' => $tool['application_endpoint_id'], 'tool' => $tool['tool_name'],
                'constraints' => json_object_encode($tool['constraints']), 'by' => $by,
            ]);
        }
        foreach (($f['duties'] ?? []) as $duty) {
            $pdo->prepare(<<<'SQL'
                INSERT INTO agent_duties (agent_member_id, name, instructions, schedule_cron, timezone, active)
                VALUES (:m, :name, :instructions, :cron, :tz, true)
            SQL)->execute([
                'm' => $memberId, 'name' => $duty['name'], 'instructions' => $duty['instructions'],
                'cron' => $duty['schedule_cron'], 'tz' => $duty['timezone'] ?: 'UTC',
            ]);
        }

        // A starting roster — only meaningful for an orchestrator; a subagent choosing kin here
        // would simply be refused by the one-level trigger below, same as any other write.
        if (($f['agent_kind'] ?? 'subagent') === 'orchestrator') {
            foreach (($f['subagents'] ?? []) as $subagentId) {
                $pdo->prepare(<<<'SQL'
                    INSERT INTO agent_subagents (orchestrator_member_id, subagent_member_id, added_by)
                    VALUES (:o, :s, :by)
                SQL)->execute(['o' => $memberId, 's' => $subagentId, 'by' => $by]);
            }
        }

        [$toolsJson, $dutiesJson] = agent_snapshot_json($pdo, $memberId);
        // With a cited prompt the db/071 trigger overwrites harness_config from that version's
        // parameters regardless of what is sent here; with no prompt, this configuration's own
        // inline settings are what harness_config actually is (db/071's redefinition of the
        // column — it no longer carries the model's harness string, which model_registry.harness
        // already tracks and the Job tab reads from there).
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO agent_config_versions
                (agent_member_id, version_no, job_description, model_id, harness_config,
                 tool_grants, schedule, monthly_budget_amount, change_note, created_by,
                 system_prompt_id, system_prompt_version)
            VALUES (:m, 1, :desc, :model, :harness_config, :tools, :duties, :budget, 'Initial hire', :by,
                    :prompt_id, :prompt_version)
            RETURNING id
        SQL);
        $st->execute([
            'm' => $memberId, 'desc' => $f['job_description'], 'model' => $f['model_id'],
            'harness_config' => json_object_encode($f['parameters'] ?? []),
            'tools' => $toolsJson, 'duties' => $dutiesJson,
            'budget' => $f['monthly_budget_amount'] ?: null, 'by' => $by,
            'prompt_id' => $f['system_prompt_id'] ?? null, 'prompt_version' => $f['system_prompt_version'] ?? null,
        ]);
        $versionId = (int) $st->fetchColumn();

        $pdo->prepare("INSERT INTO hr_events (member_id, event_type, config_version_id, actor_member_id, note)
                        VALUES (:m, 'hire', :v, :by, NULL)")
            ->execute(['m' => $memberId, 'v' => $versionId, 'by' => $by]);

        // Hiring activates (2026-09-18, owner). An agent used to arrive as a `candidate` with
        // its first version unactivated, which made hiring a two-step job whose second step was
        // a button inside a tab — "I cannot find where to perform the second step that shouldn't
        // be necessary in the first place". A brand-new version cannot have a passing eval run
        // against it anyway, so the gate could only ever have refused every hire; it stays where
        // it belongs, on version 2 and after, where there is something to compare against.
        // Recorded as ungated so the trail never implies an eval that did not happen.
        $pdo->prepare('UPDATE agent_config_versions SET activated_at = now(), activated_by = :by
                        WHERE id = :v')->execute(['by' => $by, 'v' => $versionId]);
        $pdo->prepare('UPDATE agent_profiles SET current_config_version_id = :v, updated_at = now()
                        WHERE member_id = :m')->execute(['v' => $versionId, 'm' => $memberId]);
        $pdo->prepare("INSERT INTO hr_events (member_id, event_type, config_version_id, actor_member_id, note)
                        VALUES (:m, 'onboard', :v, :by, :note)")
            ->execute(['m' => $memberId, 'v' => $versionId, 'by' => $by,
                       'note' => 'Version 1 activated at hire, ungated — a first version has nothing to have been evaluated against.']);

        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
    return find_agent($pdo, $memberId) ?? [];
}

/**
 * Never edits a version; always creates version_no + 1. $f: job_description, model_id,
 * monthly_budget_amount, budget_currency, change_note, system_prompt_id, system_prompt_version
 * (both-or-neither — resolve_agent_prompt_selection()), parameters (inline settings, ignored
 * when a prompt is cited). Duty upserts/removals (if any) must already have been applied by the
 * caller before this runs, so the schedule snapshot below captures the live, post-edit set —
 * same reasoning for tool_grants (live, via the Tools tab).
 */
function create_config_version(PDO $pdo, int $memberId, array $f, int $by): array
{
    $st = $pdo->prepare('SELECT coalesce(max(version_no), 0) + 1 FROM agent_config_versions WHERE agent_member_id = :id');
    $st->execute(['id' => $memberId]);
    $versionNo = (int) $st->fetchColumn();

    [$toolsJson, $dutiesJson] = agent_snapshot_json($pdo, $memberId);

    // runtime_config belongs to the harness (db/097). A new version starts from the one it
    // replaces — the active version, else the newest — so a key this form does not show (skill
    // pins) is never dropped by an unrelated edit; $f['runtime'] holds only what was sent.
    $st = $pdo->prepare('SELECT cv.runtime_config
                           FROM agent_config_versions cv
                           LEFT JOIN agent_profiles ap ON ap.current_config_version_id = cv.id
                          WHERE cv.agent_member_id = :id
                          ORDER BY (ap.member_id IS NOT NULL) DESC, cv.version_no DESC LIMIT 1');
    $st->execute(['id' => $memberId]);
    $runtime = json_decode((string) ($st->fetchColumn() ?: '{}'), true);
    $runtime = is_array($runtime) ? $runtime : [];
    foreach ($f['runtime'] ?? [] as $key => $value) {
        if ($value === null) {
            unset($runtime[$key]);
        } else {
            $runtime[$key] = $value;
        }
    }

    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO agent_config_versions
            (agent_member_id, version_no, job_description, model_id, harness_config,
             tool_grants, schedule, monthly_budget_amount, change_note, created_by,
             system_prompt_id, system_prompt_version, runtime_config)
        VALUES (:m, :vno, :desc, :model, :harness_config, :tools, :duties, :budget, :note, :by,
                :prompt_id, :prompt_version, :runtime)
        RETURNING id
    SQL);
    $st->execute([
        'm' => $memberId, 'vno' => $versionNo, 'desc' => $f['job_description'], 'model' => $f['model_id'],
        'runtime' => json_object_encode($runtime),
        'harness_config' => json_object_encode($f['parameters'] ?? []),
        'tools' => $toolsJson, 'duties' => $dutiesJson,
        'budget' => $f['monthly_budget_amount'] ?: null, 'note' => $f['change_note'] ?: null, 'by' => $by,
        'prompt_id' => $f['system_prompt_id'] ?? null, 'prompt_version' => $f['system_prompt_version'] ?? null,
    ]);
    $id = (int) $st->fetchColumn();

    $pdo->prepare("INSERT INTO hr_events (member_id, event_type, config_version_id, actor_member_id, note)
                    VALUES (:m, 'adjust', :v, :by, :note)")
        ->execute(['m' => $memberId, 'v' => $id, 'by' => $by, 'note' => $f['change_note'] ?: null]);

    return find_agent_version($pdo, $id) ?? [];
}

/**
 * A gating eval set for this agent, or null. Queries the real eval_sets table (installed by
 * db/046, which this slice does not touch) — it has zero matching rows today because nothing
 * authors eval sets yet, so this degrades to null honestly rather than being hardcoded. The day
 * the evals slice adds a set for an agent, activation starts gating on it with no code change
 * here.
 */
function gating_eval_set_for(PDO $pdo, int $memberId): ?array
{
    $st = $pdo->prepare("SELECT * FROM eval_sets WHERE agent_member_id = :id AND status = 'active' LIMIT 1");
    $st->execute(['id' => $memberId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/**
 * Activation and evals (revised 2026-09-20 — evals are run on demand and ADVISE):
 *  - a passing eval run exists for THIS version -> it is recorded as gating_eval_run_id, gated=true;
 *  - anything else -> activation proceeds all the same, gating_eval_run_id stays NULL, and the
 *    caller is told the version went live unevaluated. Never fake a pass; never refuse for the
 *    lack of one.
 *
 * @return array{agent: array, gated: bool, eval_set_name: ?string}
 * @throws RuntimeException when a gating eval set exists but has no passing run for this version
 */
function activate_config_version(PDO $pdo, int $versionId, int $by): array
{
    $version = find_agent_version($pdo, $versionId);
    if ($version === null) {
        throw new RuntimeException('That configuration version does not exist.');
    }
    $memberId = (int) $version['agent_member_id'];
    $evalSet = gating_eval_set_for($pdo, $memberId);
    $gatingRunId = null;
    $gated = false;

    if ($evalSet !== null) {
        $st = $pdo->prepare(<<<'SQL'
            SELECT id FROM eval_runs
             WHERE eval_set_id = :set AND config_version_id = :v AND status = 'passed'
             ORDER BY created_at DESC LIMIT 1
        SQL);
        $st->execute(['set' => $evalSet['id'], 'v' => $versionId]);
        $gatingRunId = $st->fetchColumn() ?: null;
        // Evals ADVISE, they do not block (owner, 2026-09-20): they are run on demand, by a person
        // weighing a model or prompt change or looking into a degradation. A version with no passing
        // run activates like any other; what is recorded — and said back — is that it went live
        // unevaluated. gating_eval_run_id is set only when a passing run for THIS version exists.
        $gated = $gatingRunId !== null;
    }

    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare('UPDATE agent_config_versions SET activated_at = now(), activated_by = :by,
                                     gating_eval_run_id = :run WHERE id = :id RETURNING id');
        $st->execute(['by' => $by, 'run' => $gatingRunId, 'id' => $versionId]);
        if ($st->fetch() === false) {
            $pdo->rollBack();
            throw new RuntimeException('That version could not be activated.');
        }

        $wcSt = $pdo->prepare("SELECT status = 'candidate' FROM agent_profiles WHERE member_id = :id");
        $wcSt->execute(['id' => $memberId]);
        $wasCandidate = $wcSt->fetchColumn();

        // The profile's model and budget are what every list, the dashboard and mcp_agents show as
        // "current", so activation carries them over from the version. Until 2026-09-20 it did
        // not, and an agent moved to another model kept showing the one it was hired on. A version
        // with no budget of its own leaves the profile's standing budget alone (the ledger proxy
        // reads them in the same order).
        $pdo->prepare("UPDATE agent_profiles ap
                          SET current_config_version_id = cv.id, status = 'active', updated_at = now(),
                              model_id = cv.model_id,
                              monthly_budget_amount = COALESCE(cv.monthly_budget_amount, ap.monthly_budget_amount)
                         FROM agent_config_versions cv
                        WHERE ap.member_id = :m AND cv.id = :v AND cv.agent_member_id = ap.member_id")
            ->execute(['v' => $versionId, 'm' => $memberId]);

        if ($wasCandidate) {
            $pdo->prepare("INSERT INTO hr_events (member_id, event_type, config_version_id, actor_member_id, note)
                            VALUES (:m, 'onboard', :v, :by, :note)")
                ->execute([
                    'm' => $memberId, 'v' => $versionId, 'by' => $by,
                    'note' => $gated ? null : ($evalSet !== null
                        ? 'Activated without a passing eval run for this version (eval set "' . $evalSet['name'] . '" exists; evals advise, they do not block).'
                        : 'Activated without an eval — no eval set exists for this agent yet.'),
                ]);
        }
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }

    return ['agent' => find_agent($pdo, $memberId) ?? [], 'gated' => $gated,
            'eval_set_name' => $evalSet['name'] ?? null];
}
