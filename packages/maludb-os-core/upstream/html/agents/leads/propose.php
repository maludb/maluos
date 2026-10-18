<?php
declare(strict_types=1);

/** Action `agent_lead_propose` — log `agent_lead.propose` (one per proposal). Gate: super. Files a proposed lead for every department that needs one (db/157). */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/assistants/assistants.php';

require_super_admin();
agent_refuse_agent_caller();
require_post();
verify_csrf();
$pdo = db();
check_approval($pdo, 'agent_lead_propose', 'agent_lead.propose', 'Propose leads for departments without one', [], null, null);
$filed = propose_missing_leads($pdo);
emit_action_status(true, ['did' => $filed === [] ? 'Every department that needs a lead has one, or a proposal waiting.'
    : 'Proposed ' . count($filed) . ' lead' . (count($filed) === 1 ? '' : 's') . ' — confirm or decline each.', 'refresh' => 'agentChanged']);
