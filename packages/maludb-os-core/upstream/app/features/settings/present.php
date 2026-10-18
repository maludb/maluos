<?php
declare(strict_types=1);

/**
 * Settings presenters — business settings, pipelines, catalog, tax rates, expense categories,
 * the model registry and the prompt library. Whitelists, mirrored by web/lib/schemas/settings.ts
 * (docs/react-migration-plan.md, "Presenters, never raw rows").
 *
 * business_settings(), find_catalog_items_admin() and find_tax_rates_admin() read base tables
 * with SELECT *, so the whitelist here is the only thing between those rows and the browser:
 * business tax_id, address, email, phone and website are not on this screen and are not sent.
 */

/** Business settings, exactly the eight fields the form edits. */
function present_business_settings(array $s): array
{
    return [
        'business_name' => (string) ($s['business_name'] ?? ''),
        'legal_name' => ($s['legal_name'] ?? '') !== '' ? (string) $s['legal_name'] : null,
        'base_currency' => (string) ($s['base_currency'] ?? 'USD'),
        'timezone' => (string) ($s['timezone'] ?? 'UTC'),
        'fiscal_year_start_month' => (int) ($s['fiscal_year_start_month'] ?? 1),
        'default_payment_terms_days' => (int) ($s['default_payment_terms_days'] ?? 30),
        'deal_quiet_days' => (int) ($s['deal_quiet_days'] ?? 14),
        'default_hourly_rate' => isset($s['default_hourly_rate']) ? (string) $s['default_hourly_rate'] : null,
        'prompt_payload_retention_days' => ($s['prompt_payload_retention_days'] ?? null) !== null
            ? (int) $s['prompt_payload_retention_days'] : null,
    ];
}

/**
 * The company's logo as Business settings shows it (business_logo_record(), db/134): null when
 * the shipped logo is in use. The path on disk stays on the server; the address is the versioned
 * one the shell uses (business_logo_url()).
 */
function present_business_logo(PDO $pdo): ?array
{
    $logo = business_logo_record($pdo);
    if ($logo === null) {
        return null;
    }
    return [
        'url' => business_logo_url($pdo),
        'mime' => (string) $logo['logo_mime'],
        'size_bytes' => (int) $logo['logo_size_bytes'],
        'updated_at' => json_ts($logo['logo_updated_at']),
    ];
}

/** A pipeline with its stages as the editor shows them (find_pipelines()). */
function present_pipeline_settings(array $p): array
{
    return [
        'id' => (int) $p['pipeline_id'],
        'name' => (string) $p['name'],
        'is_default' => (bool) $p['is_default'],
        'stages' => array_map(static fn (array $s): array => [
            'id' => (int) $s['stage_id'],
            'name' => (string) ($s['stage_name'] ?? ''),
            'kind' => (string) ($s['stage_kind'] ?? 'open'),
            'probability' => (string) ($s['probability'] ?? 0),
            'sort_order' => (int) ($s['sort_order'] ?? 0),
        ], $p['stages'] ?? []),
    ];
}

/** One catalog item (find_catalog_items_admin()). */
function present_catalog_item_settings(array $i): array
{
    return [
        'id' => (int) $i['id'],
        'name' => (string) $i['name'],
        'unit' => ($i['unit'] ?? '') !== '' ? (string) $i['unit'] : null,
        'unit_price' => (string) $i['unit_price'],
        'tax_rate_id' => ($i['tax_rate_id'] ?? null) !== null ? (int) $i['tax_rate_id'] : null,
        'archived' => $i['archived_at'] !== null,
    ];
}

/** One tax rate (find_tax_rates_admin()). */
function present_tax_rate_settings(array $r): array
{
    return [
        'id' => (int) $r['id'],
        'name' => (string) $r['name'],
        'rate' => (string) $r['rate'],
        'is_default' => (bool) $r['is_default'],
        'archived' => $r['archived_at'] !== null,
    ];
}

/** One expense category (find_expense_categories($pdo, true)). */
function present_expense_category_settings(array $c): array
{
    return [
        'id' => (int) $c['category_id'],
        'name' => (string) $c['name'],
        'accounting_code' => ($c['accounting_code'] ?? '') !== '' ? (string) $c['accounting_code'] : null,
        'is_billable_default' => !empty($c['is_billable_default']),
        'archived' => ($c['archived_at'] ?? null) !== null,
    ];
}

/**
 * A registered model, for the registry and its form (find_models() / find_model()).
 * endpoint_url is absent on purpose: mcp_model_registry does not expose it. Only the model form
 * carries it — html/settings/models/form.php adds it from find_model_endpoint_url() (decision 10).
 */
function present_model(array $m): array
{
    $text = static fn (string $k): ?string => ($m[$k] ?? '') !== '' ? (string) $m[$k] : null;
    return [
        'id' => isset($m['model_id']) ? (int) $m['model_id'] : null,
        'model_key' => (string) ($m['model_key'] ?? ''),
        'display_name' => (string) ($m['display_name'] ?? ''),
        'provider' => (string) ($m['provider'] ?? ''),
        'provider_model_id' => $text('provider_model_id'),
        'harness' => (string) ($m['harness'] ?? ''),
        'context_window_tokens' => ($m['context_window_tokens'] ?? null) !== null ? (int) $m['context_window_tokens'] : null,
        'price_input_per_mtok' => $text('price_input_per_mtok'),
        'price_output_per_mtok' => $text('price_output_per_mtok'),
        'price_cache_read_per_mtok' => $text('price_cache_read_per_mtok'),
        'price_cache_write_per_mtok' => $text('price_cache_write_per_mtok'),
        'currency' => (string) ($m['currency'] ?? 'USD'),
        'status' => (string) ($m['status'] ?? 'active'),
        // What it bills to (db/164): api_key, or claude_subscription (the owner's Max plan; Claude Code harness only).
        'auth_mode' => (string) ($m['auth_mode'] ?? 'api_key'),
    ];
}

/** A library prompt, for the list and its page (find_system_prompts() / find_system_prompt()). */
function present_system_prompt(array $p): array
{
    return [
        'id' => (int) $p['system_prompt_id'],
        'prompt_key' => (string) $p['prompt_key'],
        'name' => (string) $p['name'],
        'description' => ($p['description'] ?? '') !== '' ? (string) $p['description'] : null,
        'role_key' => ($p['role_key'] ?? '') !== '' ? (string) $p['role_key'] : null,
        'current_version' => (int) ($p['current_version'] ?? 0),
        'version_count' => (int) ($p['version_count'] ?? 0),
        'used_by_configs' => (int) ($p['used_by_configs'] ?? 0),
        'archived' => ($p['archived_at'] ?? null) !== null,
    ];
}

/** A prompt version's parameters, decoded (mcp_system_prompt_versions.parameters). */
function system_prompt_version_parameters(array $v): array
{
    $params = $v['parameters'] ?? '{}';
    return is_array($params) ? $params : (json_decode((string) $params, true) ?: []);
}

/** One immutable version, full text and all (find_system_prompt_versions()). */
function present_system_prompt_version(array $v): array
{
    return [
        'id' => (int) $v['system_prompt_version_id'],
        'version_no' => (int) $v['version_no'],
        'body' => (string) $v['body'],
        'change_note' => ($v['change_note'] ?? '') !== '' ? (string) $v['change_note'] : null,
        'created_by_name' => $v['created_by_name'] ?? null,
        'created_by' => isset($v['created_by']) ? (int) $v['created_by'] : null,
        'created_at' => json_ts($v['created_at'] ?? null),
        'parameters_summary' => prompt_parameters_summary(system_prompt_version_parameters($v)),
    ];
}

/**
 * What the "New version" form starts from: the current version, prefilled (mod:hr only).
 * prompt.php took temperature and max_tokens from the version's own columns and the thinking
 * budget from its parameters; the "other parameters" box starts empty, as it did.
 */
function present_new_prompt_version_defaults(?array $current): array
{
    $params = $current !== null ? system_prompt_version_parameters($current) : [];
    return [
        'body' => (string) ($current['body'] ?? ''),
        'temperature' => (string) ($current['temperature'] ?? ''),
        'max_tokens' => (string) ($current['max_tokens'] ?? ''),
        'thinking_budget' => (string) ($params['thinking_budget'] ?? ''),
    ];
}

/**
 * The signed-in member's own Settings screen (find_member_by_id() + the two token lists).
 * A members row is the widest row in the database — password hash, TOTP secret, recovery
 * material — so this names the nine things the five sections show and nothing else. No token
 * value is here or anywhere in a read: a raw token exists only in the answer to the POST that
 * created it (tokens/create.php, 2fa/enroll.php, 2fa/enable.php).
 */
function present_my_settings(array $m, array $tokens, string $recordsUrl, string $activityUrl): array
{
    return [
        'profile' => [
            'display_name' => (string) ($m['display_name'] ?? ''),
            'timezone' => (string) ($m['timezone'] ?? 'UTC'),
            'organization' => (string) ($m['organization'] ?? ''),
            'bio' => (string) ($m['bio'] ?? ''),
        ],
        'notifications' => [
            'notify_reply' => !empty($m['notify_reply']),
            'notify_event' => !empty($m['notify_event']),
            'notify_exam' => !empty($m['notify_exam']),
            'notify_digest' => !empty($m['notify_digest']),
        ],
        'security' => ['enabled' => ($m['totp_enabled_at'] ?? null) !== null],
        'tokens' => array_map(static fn (array $t): array => [
            'id' => (int) $t['id'],
            'label' => (string) $t['label'],
            'last_used_at' => json_ts($t['last_used_at'] ?? null),
            'created_at' => json_ts($t['created_at'] ?? null),
        ], $tokens),
        'mcp' => ['records_url' => $recordsUrl, 'activity_url' => $activityUrl],
    ];
}
