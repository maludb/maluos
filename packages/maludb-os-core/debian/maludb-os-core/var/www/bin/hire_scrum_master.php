<?php
declare(strict_types=1);
/**
 * Hire the Projects application's Scrum Master agent (owner, 2026-09-28 — "create a scrum master default agent":
 * hired on install, not merely proposed). This is bin/hire_application_agent.php with --app projects
 * --agent scrum_master; the same options apply (--by, --model, --department, --app-dir, --budget).
 */
array_splice($argv, 1, 0, ['--app=projects', '--agent=scrum_master']);
require __DIR__ . '/hire_application_agent.php';
