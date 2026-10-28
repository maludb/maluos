<?php
declare(strict_types=1);

/**
 * Shared re-renders, gates and field parsers for the Agent HR screens — the exemplar's "a
 * write answers with the whole refreshed screen" pattern. Every render_*_page() here emits
 * status: error through the action channel whenever it is called with a non-empty $errors
 * array (the fix the Expenses and Books slices both had to make: a validation error
 * re-rendered with HTTP 200 reads as success to the assistant and to every agent unless
 * X-Action-Status says otherwise).
 */

function agents_require_files(): void
{
    require_once __DIR__ . '/queries.php';
    require_once __DIR__ . '/prompts.php';
    require_once __DIR__ . '/hiring.php';
    require_once __DIR__ . '/models.php';
    require_once __DIR__ . '/photos.php';
    require_once __DIR__ . '/runs.php';
    require_once __DIR__ . '/mcp_tools.php';
    require_once dirname(__DIR__) . '/team/queries.php';
}

/** Up to two initials from a display name, for the avatar fallback when profile_pic_url is
 *  absent or the image fails to load — never a broken image icon. */
function agent_initials(string $name): string
{
    $name = trim($name);
    if ($name === '') {
        return '?';
    }
    $parts = preg_split('/\s+/', $name) ?: [$name];
    $initials = mb_strtoupper(mb_substr($parts[0], 0, 1));
    if (count($parts) > 1) {
        $initials .= mb_strtoupper(mb_substr($parts[count($parts) - 1], 0, 1));
    }
    return $initials;
}

/**
 * An avatar image with a graceful fallback to initials — used everywhere an agent's picture
 * would show (list, identity card). Since db/090 the picture is a file we hold, and
 * mcp_agents.profile_pic_url is the address that serves it (or NULL when there is none); the
 * fallback stays because a photo can be removed between a page render and its image request.
 * Both elements are always in the DOM; a broken image's `onerror` just swaps which is hidden
 * (classList, not inline style — Bootstrap's `d-none` is `!important` and would ignore one).
 */
function agent_avatar_html(array $agent, string $sizeClass = 'avatar-sm'): string
{
    $initials = agent_initials((string) ($agent['display_name'] ?? ''));
    $url = trim((string) ($agent['profile_pic_url'] ?? ''));
    $fallback = '<span class="avatar-text ' . e($sizeClass) . ' rounded-circle bg-soft-primary text-primary '
              . 'fw-semibold' . ($url === '' ? '' : ' d-none') . '">' . e($initials) . '</span>';
    if ($url === '') {
        return $fallback;
    }
    return '<img src="' . e($url) . '" alt="" class="avatar-image ' . e($sizeClass) . ' rounded-circle" '
         . 'onerror="this.classList.add(\'d-none\');this.nextElementSibling.classList.remove(\'d-none\')">'
         . $fallback;
}

/**
 * The number a voice agent answers. The database enforces E.164, uniqueness and voice-only
 * (db/093); this says so in words before the constraint says so in Latin.
 */
function agent_phone_errors(?string $phone, string $kind): array
{
    if ($phone === null || $phone === '') {
        return [];
    }
    if ($kind !== 'voice') {
        return ['Only a voice agent answers a phone number.'];
    }
    if (preg_match('/^\+[1-9][0-9]{6,14}$/', $phone) !== 1) {
        return ['The phone number needs to be in E.164 form, e.g. +14155550123.'];
    }
    return [];
}

/**
 * The kind badge — one renderer, because three screens showed it and each had its own
 * two-way ternary that silently read "voice" as a subagent when db/091 added it.
 */
function agent_kind_badge_html(array $agent, bool $withCount = true): string
{
    $kind = (string) ($agent['agent_kind'] ?? 'subagent');
    $tone = ['orchestrator' => 'brand', 'subagent' => 'info', 'voice' => 'warning'][$kind] ?? 'secondary';
    $label = AGENT_KIND_LABELS[$kind] ?? ucfirst($kind);
    // "roster", not "manages": the count is agent_subagents (what it may delegate to), and
    // since an orchestrator may also be somebody's manager the two are no longer the same set.
    $count = ($withCount && $kind === 'orchestrator')
        ? ' · roster ' . (int) ($agent['subagent_count'] ?? 0) : '';
    return '<span class="badge bg-soft-' . $tone . ' text-' . $tone . '">' . e($label . $count) . '</span>';
}

// --------------------------------------------------------------------------
// Gates: "mod:hr, agent's manager" and similar OR-gates (a comma in the manifest's Who
// column means OR — getting this backwards is how the ledger slice locked the bookkeeper
// out of posting).
// --------------------------------------------------------------------------
/** mod:hr OR the agent's own manager. */
function agent_require_hr_or_manager(PDO $pdo, array $agent): void
{
    require_login();
    if (is_super_admin()) {
        return;
    }
    if ((int) ($agent['manager_member_id'] ?? 0) === (int) current_member_id()) {
        return;
    }
    $st = $pdo->prepare('SELECT app_has_module(:m)');
    $st->execute(['m' => 'hr']);
    if (!$st->fetchColumn()) {
        deny('This needs the hr module grant, or being this agent\'s manager.');
    }
}

/** Extracts a plpgsql RAISE EXCEPTION's own message from a PDOException, stripping the
 *  "SQLSTATE[P0001]: Raise exception: ... ERROR:  " wrapper PDO adds. The db/072 triggers'
 *  refusal messages are the feature (agent HR follow-up spec) — they must reach the field
 *  error verbatim, not a generic "could not save". Falls back when the message doesn't match
 *  (a different error entirely — never show raw SQL to a user). */
/**
 * Kept as the agents feature's name for it; the rule now lives in one place (db.php), which
 * also stopped this showing raw constraint text — "duplicate key value violates unique
 * constraint members_email_key" is not an instruction to anybody.
 */
function agent_trigger_message(PDOException $ex, string $fallback): string
{
    return db_message($ex, $fallback);
}

/** Agents must not reach authoring (build spec, "Agents must not reach this module's
 *  authoring"). Call at the top of every write/form endpoint except escalation-save.php,
 *  which is the one surface an agent caller IS meant to reach. */
function agent_refuse_agent_caller(): void
{
    if (is_agent_member()) {
        deny('An agent may read its own profile and raise escalations, but not author HR records.');
    }
}

/**
 * Everything the agent-view template needs, assembled once.
 *
 * Both entry points render this screen — the full-page GET (html/agents/view.php) and this
 * file's re-render — and they each built this array independently until 2026-09-18. They
 * diverged three times: the tab list (fixed with AGENT_VIEW_TABS), then `toolEndpointOptions`,
 * which render_agent_page() passed and view.php did not, so the Tools tab's endpoint dropdown
 * was empty for every agent in the browser while the data layer was provably correct. Two
 * copies of one contract is a bug with a delivery schedule.
 */
function agent_view_data(PDO $pdo, array $agent, string $tab, array $errors = []): array
{
    $memberId = (int) $agent['agent_member_id'];
    $isOrchestrator = ($agent['agent_kind'] ?? 'subagent') === 'orchestrator';
    $tab = in_array($tab, AGENT_VIEW_TABS, true) ? $tab : 'job';
    // Only the shown tab's sections are read (owner, 2026-09-28: the page issued 45 statements
    // for every tab, loading all eight). The keys stay — a tab that is not shown gets an empty
    // list — so the payload's shape is one contract still; the header's own needs (the version,
    // the pending one, the manager picker, who may edit) are read for every tab.
    $on = static fn (string ...$tabs): bool => in_array($tab, $tabs, true);
    return [
        'agent' => $agent,
        'tab' => $tab,
        'version' => current_or_latest_agent_version($pdo, $agent),
        'versions' => $versions = find_agent_versions($pdo, $memberId),
        // The newest version, when it is still waiting to be activated. Since hiring activates
        // version 1 (db/096), this is only ever a later edit — and it has to be offered
        // somewhere obvious, because the Job tab shows the CURRENT version, not the waiting one.
        'pendingVersion' => (($versions[0]['activated_at'] ?? null) === null) ? ($versions[0] ?? null) : null,
        'toolGrants' => $on('tools') ? find_agent_tool_grants($pdo, $memberId) : [],
        'toolEndpointOptions' => $on('tools') ? find_grantable_tool_endpoints($pdo) : [],
        'duties' => $on('duties') ? find_agent_duties($pdo, $memberId) : [],
        'hrEvents' => $on('trail') ? find_hr_events($pdo, $memberId) : [],
        'reviews' => $on('performance') ? find_performance_reviews($pdo, $memberId) : [],
        'escalationsForAgent' => $on('performance') ? find_escalations($pdo, ['agent' => $memberId], 1) : [],
        'approvalsForAgent' => $on('performance') ? find_agent_approval_requests($pdo, $memberId) : [],
        'activityCount' => $on('performance') ? count_member_activity($pdo, $memberId) : 0,
        'isHr' => has_module($pdo, 'hr'),
        'isManager' => (int) ($agent['manager_member_id'] ?? 0) === (int) current_member_id(),
        'myId' => (int) current_member_id(),
        'managerOptions' => find_manager_options($pdo),
        // Roster tab (db/072): an orchestrator's live roster, editable; a subagent's read-only
        // list of the orchestrators it serves — membership is managed from the orchestrator side.
        'roster' => !$on('roster') ? [] : match ($agent['agent_kind'] ?? 'subagent') {
            'orchestrator' => find_agent_roster($pdo, $memberId),
            'voice' => [],                       // answers calls; neither delegates nor is delegated to
            default => find_agent_orchestrators($pdo, $memberId),
        },
        'subagentOptions' => $isOrchestrator && $on('roster') ? find_subagent_options($pdo) : [],
        'errors' => $errors,
    ];
}

/** "agents only" (escalation_raise's Who). Refuses a human caller. */
function require_agent_caller(): void
{
    require_login();
    if (!is_agent_member()) {
        deny('Only an agent may raise its own escalation.');
    }
}

// --------------------------------------------------------------------------
// Agents list
// --------------------------------------------------------------------------
function agent_list_filters(): array
{
    return [
        'status' => request_string('status'), 'department' => request_integer('department'),
        'kind' => request_string('kind'),
    ];
}

function render_agents_list(PDO $pdo, array $errors = []): never
{
    agents_require_files();
    if ($errors !== []) {
        emit_action_status(false, ['errors' => $errors]);
    }
    $filters = agent_list_filters();
    $page = request_integer('page') ?? 1;
    $rows = find_agents($pdo, $filters, $page);
    $total = (int) ($rows[0]['total_count'] ?? 0);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /agents/');
    echo view('agents/agents.php', [
        'agents' => $rows, 'filters' => $filters, 'page' => $page,
        'totalPages' => max(1, (int) ceil($total / AGENT_PAGE_SIZE)),
        'departments' => find_departments($pdo), 'errors' => $errors,
    ]);
    exit;
}

// --------------------------------------------------------------------------
// Agent detail (tabbed)
// --------------------------------------------------------------------------
function render_agent_page(PDO $pdo, int $memberId, string $tab = 'job', array $errors = []): never
{
    agents_require_files();
    if ($errors !== []) {
        emit_action_status(false, ['errors' => $errors]);
    }
    $agent = find_agent($pdo, $memberId);
    if ($agent === null) {
        render_agents_list($pdo);
    }
    $tabs = AGENT_VIEW_TABS;   // defined once in app/features/agents/queries.php
    $tab = in_array($tab, $tabs, true) ? $tab : 'job';
    $isOrchestrator = ($agent['agent_kind'] ?? 'subagent') === 'orchestrator';

    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /agents/' . $memberId . ($tab !== 'job' ? '?tab=' . $tab : ''));   // the tab the handler chose (a review → Performance)
    echo view('agents/agent.php', agent_view_data($pdo, $agent, $tab, $errors));
    exit;
}

// --------------------------------------------------------------------------
// Escalations
// --------------------------------------------------------------------------
function escalation_list_filters(): array
{
    return ['agent' => request_integer('agent'), 'open' => request_bool('open')];
}

function render_escalations_page(PDO $pdo, array $errors = []): never
{
    agents_require_files();
    if ($errors !== []) {
        emit_action_status(false, ['errors' => $errors]);
    }
    $filters = escalation_list_filters();
    $page = request_integer('page') ?? 1;
    $rows = find_escalations($pdo, $filters, $page);
    $total = (int) ($rows[0]['total_count'] ?? 0);
    header('HX-Retarget: #page-content');
    header('HX-Reswap: innerHTML');
    header('HX-Push-Url: /agents/escalations');
    echo view('agents/escalations.php', [
        'escalations' => $rows, 'filters' => $filters, 'page' => $page,
        'totalPages' => max(1, (int) ceil($total / AGENT_PAGE_SIZE)),
        'agentOptions' => find_agent_member_options($pdo), 'errors' => $errors,
    ]);
    exit;
}

// --------------------------------------------------------------------------
// Field parsing: hire / config-save share the same tools[] / duties[] repeating-row shape.
// No JS-driven "add another row" exists in this codebase yet (the Books journal exemplar
// ships a fixed bulk lines[] array for the same reason) — the form ships a fixed number of
// blank rows and any left blank is simply skipped. tools[] and duties[] are both optional at
// hire (spec's Fields table carries no checkmark for either).
// --------------------------------------------------------------------------
const AGENT_TOOL_BLANK_ROWS = 3;
const AGENT_DUTY_BLANK_ROWS = 3;

/** @return array{0: array, 1: array} the parsed tool rows and any errors */
function agent_tools_from_request(): array
{
    $rows = (array) ($_POST['tools'] ?? []);
    $tools = [];
    $errors = [];
    foreach ($rows as $row) {
        if (!is_array($row)) {
            continue;
        }
        $endpointId = request_integer_from($row, 'application_endpoint_id');
        $tool = trim((string) ($row['tool_name'] ?? ''));
        if ($endpointId === null && $tool === '') {
            continue;                                  // a blank row is simply skipped
        }
        if ($endpointId === null) {
            $errors[] = 'A tool grant needs an MCP endpoint.';
            continue;
        }
        if ($tool === '') {
            $errors[] = 'A tool grant needs a tool name.';
            continue;
        }
        $constraintsRaw = trim((string) ($row['constraints'] ?? ''));
        $constraints = [];
        if ($constraintsRaw !== '') {
            $decoded = json_decode($constraintsRaw, true);
            if (!is_array($decoded)) {
                $errors[] = 'Constraints for endpoint #' . $endpointId . ':' . $tool . ' must be valid JSON, e.g. {"max_amount": 500}.';
                continue;
            }
            $constraints = $decoded;
        }
        $tools[] = ['application_endpoint_id' => $endpointId, 'tool_name' => $tool, 'constraints' => $constraints];
    }
    return [$tools, $errors];
}

/** @return array{0: array, 1: array} the parsed duty rows (new ones only; existing duties are
 *  edited/removed by id) and any errors */
function agent_duties_from_request(): array
{
    $rows = (array) ($_POST['duties'] ?? []);
    $duties = [];
    $errors = [];
    foreach ($rows as $row) {
        if (!is_array($row)) {
            continue;
        }
        $name = trim((string) ($row['name'] ?? ''));
        $instructions = trim((string) ($row['instructions'] ?? ''));
        $cron = trim((string) ($row['schedule_cron'] ?? ''));
        $tz = trim((string) ($row['timezone'] ?? '')) ?: 'UTC';
        if ($name === '' && $instructions === '' && $cron === '') {
            continue;                                  // a blank row is simply skipped
        }
        if ($name === '' || $instructions === '' || $cron === '') {
            $errors[] = 'A duty needs a name, instructions and a cron schedule.';
            continue;
        }
        if (count(array_filter(explode(' ', $cron), static fn ($p) => $p !== '')) !== 5) {
            $errors[] = 'A duty\'s schedule is a 5-field cron expression, e.g. "0 7 * * 1-5".';
            continue;
        }
        $duties[] = ['duty_id' => request_integer_from($row, 'duty_id'),
                      'name' => $name, 'instructions' => $instructions,
                      'schedule_cron' => $cron, 'timezone' => $tz,
                      'remove' => !empty($row['remove'])];
    }
    return [$duties, $errors];
}

/** request_integer() reads $_GET/$_POST by top-level name; this reads one nested array value. */
function request_integer_from(array $row, string $key): ?int
{
    $v = $row[$key] ?? null;
    if ($v === null || $v === '') {
        return null;
    }
    $filtered = filter_var($v, FILTER_VALIDATE_INT);
    return $filtered === false ? null : $filtered;
}

/** Fields shared by the hire form (agent-hire) — everything version 1 and the profile need. */
function agent_hire_fields_from_request(): array
{
    $errors = [];
    $fields = [
        'name' => request_string('name'),
        'email' => strtolower(trim(request_string('email'))),
        'job_title' => request_string('job_title'),
        'department_id' => request_integer('department_id'),
        'manager_member_id' => request_integer('manager_member_id'),
        'model_id' => request_integer('model_id'),
        'job_description' => request_string('job_description'),
        'monthly_budget_amount' => request_string('monthly_budget_amount') ?: null,
        'budget_currency' => request_string('budget_currency', 'USD') ?: 'USD',
        'home_location_id' => request_integer('home_location_id'),
        'system_prompt_id' => request_integer('system_prompt_id'),
        'description' => request_string('description') ?: null,
        'role_key' => trim(request_string('role_key')) ?: null,
        'phone_number' => trim(request_string('phone_number')) ?: null,
        'agent_kind' => in_array(request_string('agent_kind'), AGENT_KINDS, true)
            ? request_string('agent_kind') : 'subagent',
    ];
    // A starting roster only makes sense for an orchestrator; ignored otherwise rather than
    // erroring — the form hides the control via JS, but a stray value should not fail the hire.
    $fields['subagents'] = $fields['agent_kind'] === 'orchestrator'
        ? array_values(array_unique(array_filter(array_map('intval', (array) ($_POST['subagents'] ?? [])))))
        : [];

    if ($fields['name'] === '' || mb_strlen($fields['name']) > 200) {
        $errors[] = 'An agent needs a name (up to 200 characters).';
    }
    if ($fields['email'] === '' || filter_var($fields['email'], FILTER_VALIDATE_EMAIL) === false) {
        $errors[] = 'An agent needs a valid, unique email — it is its identity for tokens.';
    }
    if ($fields['job_title'] === '') {
        $errors[] = 'An agent needs a job title.';
    }
    if ($fields['department_id'] === null) {
        $errors[] = 'Choose the department this agent works in.';
    }
    if ($fields['manager_member_id'] === null) {
        $errors[] = 'Choose a manager — a person, or an orchestrator agent.';
    }
    if ($fields['model_id'] === null) {
        $errors[] = 'Choose a model — register one first if the list is empty.';
    }
    // A library prompt supplies the job description on resolution (prompts.php,
    // resolve_agent_prompt_selection()) — only an inline prompt needs one typed here.
    if ($fields['job_description'] === '' && $fields['system_prompt_id'] === null) {
        $errors[] = 'The job description is the agent\'s system prompt — write one, or choose a library prompt.';
    }
    if ($fields['monthly_budget_amount'] !== null && (!is_numeric($fields['monthly_budget_amount'])
            || (float) $fields['monthly_budget_amount'] < 0)) {
        $errors[] = 'The monthly budget must be zero or more.';
    }
    $errors = array_merge($errors, agent_phone_errors($fields['phone_number'], $fields['agent_kind']));

    // The photo is only validated here; it is stored once the agent has an id to store it
    // under, so a refused image never leaves a half-made agent behind.
    [$photo, $photoErrors] = agent_photo_from_request();
    $fields['photo'] = $photo;
    $errors = array_merge($errors, $photoErrors);

    [$tools, $toolErrors] = agent_tools_from_request();
    [$duties, $dutyErrors] = agent_duties_from_request();
    $fields['tools'] = $tools;
    $fields['duties'] = $duties;
    $errors = array_merge($errors, $toolErrors, $dutyErrors);

    // Inline model settings — ignored once a library prompt is cited (its version's parameters
    // are what land in harness_config, by the db/071 trigger; a form control here would lie).
    if ($fields['system_prompt_id'] === null) {
        [$parameters, $paramErrors] = prompt_parameters_from_request();
        $fields['parameters'] = $parameters;
        $errors = array_merge($errors, $paramErrors);
    } else {
        $fields['parameters'] = [];
    }

    return [$fields, $errors];
}

/** Fields shared by the edit form (agent-edit / config-save.php). */
function agent_config_fields_from_request(): array
{
    $errors = [];
    $fields = [
        'job_description' => request_string('job_description'),
        'model_id' => request_integer('model_id'),
        'monthly_budget_amount' => request_string('monthly_budget_amount') ?: null,
        'change_note' => request_string('change_note') ?: null,
        'system_prompt_id' => request_integer('system_prompt_id'),
        'description' => request_string('description') ?: null,
        'role_key' => trim(request_string('role_key')) ?: null,
        'phone_number' => trim(request_string('phone_number')) ?: null,
        'remove_photo' => request_bool('remove_photo'),
    ];
    if ($fields['job_description'] === '' && $fields['system_prompt_id'] === null) {
        $errors[] = 'The job description cannot be empty — write one, or choose a library prompt.';
    }
    if ($fields['model_id'] === null) {
        $errors[] = 'Choose a model.';
    }
    if ($fields['monthly_budget_amount'] !== null && (!is_numeric($fields['monthly_budget_amount'])
            || (float) $fields['monthly_budget_amount'] < 0)) {
        $errors[] = 'The monthly budget must be zero or more.';
    }
    [$photo, $photoErrors] = agent_photo_from_request();
    $fields['photo'] = $photo;
    $errors = array_merge($errors, $photoErrors);

    [$duties, $dutyErrors] = agent_duties_from_request();
    $fields['duties'] = $duties;
    $errors = array_merge($errors, $dutyErrors);

    if ($fields['system_prompt_id'] === null) {
        [$parameters, $paramErrors] = prompt_parameters_from_request();
        $fields['parameters'] = $parameters;
        $errors = array_merge($errors, $paramErrors);
    } else {
        $fields['parameters'] = [];
    }

    [$runtime, $runtimeErrors] = agent_runtime_fields_from_request();
    $fields['runtime'] = $runtime;
    $errors = array_merge($errors, $runtimeErrors);

    return [$fields, $errors];
}

/**
 * The run limits a person may set on a version (agent_config_versions.runtime_config, db/097):
 * how many turns a run may take and how long it may last. Only what was SENT is returned — a
 * key absent from the request is carried forward from the version being replaced, a key sent
 * empty is removed (the runner's default applies). Everything else in runtime_config is carried
 * forward untouched by create_config_version(); nothing here can set a key the runner would
 * have to refuse.
 * @return array{0: array<string, ?int>, 1: list<string>}
 */
const AGENT_RUNTIME_LIMITS = [
    'max_turns' => ['label' => 'Most turns in a run', 'min' => 1, 'max' => 200],
    'run_timeout_seconds' => ['label' => 'Longest a run may last', 'min' => 60, 'max' => 3600],
];

function agent_runtime_fields_from_request(): array
{
    $runtime = [];
    $errors = [];
    foreach (AGENT_RUNTIME_LIMITS as $key => $rule) {
        if (!array_key_exists($key, $_POST)) {
            continue;
        }
        $raw = trim(request_string($key));
        if ($raw === '') {
            $runtime[$key] = null;
            continue;
        }
        if (!ctype_digit($raw) || (int) $raw < $rule['min'] || (int) $raw > $rule['max']) {
            $errors[] = $rule['label'] . ' must be a whole number from ' . $rule['min'] . ' to ' . $rule['max'] . '.';
            continue;
        }
        $runtime[$key] = (int) $raw;
    }
    return [$runtime, $errors];
}

// --------------------------------------------------------------------------
// Escalation field parsing
// --------------------------------------------------------------------------
function escalation_fields_from_request(): array
{
    $errors = [];
    $fields = [
        'reason_kind' => request_string('reason_kind'),
        'summary' => request_string('summary'),
        'entity_type' => request_string('entity_type') ?: null,
        'entity_id' => request_integer('entity'),
        'to_member_id' => request_integer('to_member'),
        'open_ticket' => request_bool('open_ticket'),
    ];
    if (!in_array($fields['reason_kind'], ESCALATION_REASON_KINDS, true)) {
        $errors[] = 'That is not a reason this app knows: ' . implode(', ', ESCALATION_REASON_KINDS) . '.';
    }
    if ($fields['summary'] === '') {
        $errors[] = 'An escalation needs a summary.';
    }
    return [$fields, $errors];
}

// --------------------------------------------------------------------------
// Performance review field parsing
// --------------------------------------------------------------------------
function review_fields_from_request(): array
{
    $errors = [];
    $fields = [
        'period_start' => request_string('period_start'),
        'period_end' => request_string('period_end'),
        'rating' => request_integer('rating'),
        'summary' => request_string('summary') ?: null,
    ];
    if ($fields['period_start'] === '' || $fields['period_end'] === '') {
        $errors[] = 'A review needs a period (start and end).';
    } elseif ($fields['period_end'] < $fields['period_start']) {
        $errors[] = 'The period end cannot be before its start.';
    }
    if ($fields['rating'] !== null && ($fields['rating'] < 1 || $fields['rating'] > 5)) {
        $errors[] = 'Rating is 1 to 5.';
    }
    return [$fields, $errors];
}

// --------------------------------------------------------------------------
// Performance review gate: "mod:hr, manager" (OR). For an agent reviewee, "manager" is
// agent_profiles.manager_member_id; the manifest names no equivalent for a human, so this
// reads it as any department the reviewee belongs to whose manager_member_id is the caller —
// the same "manager" concept departments already carry (departments.manager_member_id).
// --------------------------------------------------------------------------
function can_review_member(PDO $pdo, array $member): bool
{
    if (is_super_admin()) {
        return true;
    }
    $me = (int) current_member_id();
    if (($member['member_kind'] ?? 'human') === 'agent') {
        $st = $pdo->prepare('SELECT manager_member_id FROM agent_profiles WHERE member_id = :id');
        $st->execute(['id' => (int) $member['member_id']]);
        if ((int) $st->fetchColumn() === $me) {
            return true;
        }
    } else {
        $st = $pdo->prepare(<<<'SQL'
            SELECT 1 FROM department_members dm JOIN departments d ON d.id = dm.department_id
             WHERE dm.member_id = :id AND dm.left_at IS NULL AND d.manager_member_id = :me LIMIT 1
        SQL);
        $st->execute(['id' => (int) $member['member_id'], 'me' => $me]);
        if ($st->fetchColumn() !== false) {
            return true;
        }
    }
    $st = $pdo->prepare('SELECT app_has_module(:m)');
    $st->execute(['m' => 'hr']);
    return (bool) $st->fetchColumn();
}

// --------------------------------------------------------------------------
// Model registry field parsing
// --------------------------------------------------------------------------
function model_fields_from_request(): array
{
    $errors = [];
    $fields = [
        'model_key' => request_string('model_key'),
        'display_name' => request_string('display_name'),
        'provider' => request_string('provider'),
        'provider_model_id' => request_string('provider_model_id'),
        'harness' => request_string('harness'),
        'endpoint_url' => request_string('endpoint_url') ?: null,
        'context_window_tokens' => request_integer('context_window_tokens'),
        'price_input_per_mtok' => request_string('price_input_per_mtok', '0'),
        'price_output_per_mtok' => request_string('price_output_per_mtok', '0'),
        'price_cache_read_per_mtok' => request_string('price_cache_read_per_mtok', '0'),
        'price_cache_write_per_mtok' => request_string('price_cache_write_per_mtok', '0'),
        'currency' => strtoupper(request_string('currency', 'USD')),
        'status' => request_string('status', 'active'),
        // What the model bills to (db/164): an API key held by the ledger proxy, or the owner's Claude Max login.
        'auth_mode' => request_string('auth_mode', 'api_key') ?: 'api_key',
    ];
    if (!in_array($fields['auth_mode'], MODEL_AUTH_MODES, true)) {
        $errors[] = 'That is not a way a model can bill.';
    } elseif ($fields['auth_mode'] === 'claude_subscription'
              && ($fields['provider'] !== 'anthropic' || $fields['harness'] !== 'claude_agent_sdk')) {
        $errors[] = 'The Claude Max plan is used only by Anthropic models on the claude_agent_sdk harness (the official Claude Code CLI).';
    }
    if ($fields['model_key'] === '' || mb_strlen($fields['model_key']) > 100) {
        $errors[] = 'A model needs a short unique key, e.g. "claude-opus-5".';
    }
    if ($fields['display_name'] === '') {
        $errors[] = 'A model needs a display name.';
    }
    if (!in_array($fields['provider'], MODEL_PROVIDERS, true)) {
        $errors[] = 'That is not a provider this app knows.';
    }
    if ($fields['provider_model_id'] === '') {
        $errors[] = 'The provider model id is what is sent to the provider API.';
    }
    if (!in_array($fields['harness'], MODEL_HARNESSES, true)) {
        $errors[] = 'That is not a harness this app knows.';
    }
    if (!in_array($fields['status'], MODEL_STATUSES, true)) {
        $fields['status'] = 'active';
    }
    if (strlen($fields['currency']) !== 3) {
        $errors[] = 'Currency is a 3-letter code.';
    }
    foreach (['price_input_per_mtok', 'price_output_per_mtok', 'price_cache_read_per_mtok', 'price_cache_write_per_mtok'] as $p) {
        if (!is_numeric($fields[$p]) || (float) $fields[$p] < 0) {
            $errors[] = 'Prices must be zero or more.';
            break;
        }
    }
    return [$fields, $errors];
}
