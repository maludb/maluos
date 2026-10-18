# Evaluation Engineering in Production LLM Applications

Status: Draft v0.1  
Date: 2026-09-06  
Audience: Engineering, product, AI platform, QA, compliance, and operations teams

## Purpose

This document defines the initial evaluation strategy for a production evaluation dashboard focused on LLM prompts, workflows, and AI agents. It covers the types of evaluations that need to be performed, the engineering process for running them in production applications, and the dashboard capabilities we should design next.

The core position is simple: evaluation is not a one-time benchmark. It is a production engineering discipline that turns expected AI behavior into versioned datasets, repeatable checks, release gates, trace analysis, monitoring, and continuous improvement.

## Executive Summary

Production LLM systems need multiple layers of evaluation because failures happen at multiple layers: prompt rendering, model output, retrieval, tool use, workflow orchestration, user experience, safety controls, and operational performance. A dashboard should therefore evaluate the application path users actually hit, not only isolated model prompts.

The first dashboard version should support:

- Eval suites tied to explicit product promises.
- Versioned datasets, prompts, workflows, model settings, retrieval settings, and tool definitions.
- Deterministic assertions for hard requirements.
- Rubric or judge-based grading for subjective quality.
- Trace-based evaluation for agents and multi-step workflows.
- Cost, latency, and reliability metrics for production readiness.
- Failure triage, regression tracking, and release gates.
- Human review workflows to calibrate automated scoring.
- Architecture-fit checks that confirm the right work is assigned to the model, deterministic systems, and humans.
- Governance artifacts: control owners, evidence, review triggers, and rollback criteria.
- Business outcome tracking that connects technical scores to the value the workflow is meant to produce.

The near-term evaluation program should begin with a small, high-signal suite for each important user-visible workflow. Each suite should include routine cases, edge cases, known historical failures, adversarial cases, and negative cases where the system should refuse, escalate, or ask for clarification.

## Evaluation Principles

1. Evaluate product behavior, not model behavior in isolation.

   Model benchmarks are useful for vendor and model selection, but production evals must measure whether the application satisfies its product contract. The target under test should usually be the same endpoint, prompt builder, retrieval path, tool interface, and workflow orchestration used in production.

2. Start from user-visible promises.

   Every suite should answer a concrete question such as: "Does the support agent resolve billing questions using the right policy?", "Does the research workflow cite only retrieved sources?", or "Does the coding agent choose the correct tool and preserve user changes?"

3. Baseline before changing behavior.

   Before changing prompts, models, tools, retrieval settings, or workflow routing, run the existing system against the eval suite. The baseline distinguishes real regressions from cases that were already failing.

4. Use deterministic checks wherever possible.

   JSON shape, required fields, forbidden phrases, tool names, argument schemas, citation presence, policy constraints, and latency budgets should be checked with deterministic assertions. Judge-based grading should be reserved for dimensions that genuinely require judgment.

5. Calibrate subjective grading with human review.

   Automated judges are useful, but they must be checked against human judgment. Important rubrics should have sample disagreements reviewed by domain experts, and the dashboard should make reviewer agreement visible.

6. Log and trace everything needed to reproduce a result.

   Each run should capture the prompt version, model, model settings, input, output, retrieved context, tool calls, workflow steps, guardrail decisions, errors, cost, latency, and trace identifiers. Without these artifacts, failures are hard to debug and improvements are hard to trust.

7. Treat evaluation as a continuous production loop.

   Evals should run in local development, CI, staging, release review, canary monitoring, and post-release analysis. New bugs, support escalations, human review findings, and production traces should become new eval cases.

8. Write evals as acceptance criteria before implementation.

   An eval suite should exist before production code or prompt work hardens around assumptions. If a behavior cannot be evaluated, the team has not yet defined it well enough to ship or to compare changes.

9. Decompose the workflow before evaluating it.

   Every workflow should identify which parts are owned by the model, existing deterministic systems, and humans. Business rules, authorization, live-state lookups, and irreversible actions should not be hidden inside model behavior when a system of record, policy engine, or human gate is the accountable owner.

10. Evaluate the chosen architecture pattern.

   Augmented calls, workflows, agents, RAG systems, document-processing pipelines, routers, and multi-agent systems fail in different ways. Each architecture needs its own eval contract and observability surface instead of sharing one generic quality score.

11. Set thresholds, rollback criteria, and experiment metrics before seeing results.

   Release gates and experiments should name the primary metric, acceptable regressions, sample-size assumptions, cost and latency constraints, and rollback criteria before the candidate run starts. Otherwise the team is writing acceptance criteria after seeing the answer.

12. Preserve evidence, not just results.

   Scores are useful, but auditability comes from evidence: the input, output, trace, retrieved context, tool calls, routing path, reviewer decision, control owner, and proof that the control was operating at the time of the run.

## Evaluation Types We Need

### 1. Prompt Regression Evals

Prompt regression evals verify that prompt changes preserve required behavior. They should cover instruction adherence, formatting rules, tone, escalation behavior, refusal behavior, and expected use of supplied context.

These evals are most useful when production prompts are versioned in code with typed inputs and reviewed through the normal deployment process. The dashboard should compare prompt versions and show which cases improved, regressed, or changed without clear benefit.

Examples:

- The assistant must ask a clarifying question when required inputs are missing.
- The output must use the agreed JSON schema.
- The answer must avoid unsupported policy claims.
- The assistant must preserve a specified tone or brand constraint.
- The workflow must not expose hidden instructions or internal routing rules.

### 2. Task Correctness Evals

Task correctness evals measure whether the system produces the right answer for the job. These are the backbone of application-specific evaluation.

Core task categories include:

- Classification: labels, routing, intent detection, severity ranking.
- Extraction: structured fields from text, documents, forms, or conversations.
- Summarization: factual coverage, concision, omission control, no invented facts.
- Transformation: rewriting, normalization, translation, format conversion.
- Decision support: recommendations that follow business rules and evidence.
- Code or workflow generation: correctness, buildability, policy compliance.

Correctness evals should use deterministic checks when outputs are structured. For open-ended answers, they should use rubrics with explicit pass criteria and examples of acceptable and unacceptable responses.

### 3. Retrieval And Grounding Evals

Retrieval-augmented systems need separate evaluation for retrieval quality and answer grounding. A good answer is not enough if it came from the wrong source, ignored required evidence, or invented details.

The dashboard should support:

- Retrieval recall: did the system retrieve the necessary source material?
- Retrieval precision: did it avoid irrelevant or conflicting material?
- Citation accuracy: do cited passages support the claims?
- Grounded answer quality: does the final answer stay within retrieved evidence?
- No-answer behavior: does the system refuse or ask for more information when evidence is missing?
- Staleness handling: does it distinguish current, expired, and superseded sources?

Grounding suites should include cases with complete evidence, partial evidence, conflicting evidence, missing evidence, and intentionally misleading user assertions.

### 4. Tool-Use Evals

Agents and workflows often fail by choosing the wrong tool, calling the right tool with invalid arguments, skipping required validation, mishandling tool errors, or producing side effects at the wrong time.

Tool-use evals should check:

- Tool selection: was the right tool used for the task?
- Argument validity: did arguments match schemas and business constraints?
- Sequencing: were prerequisite checks completed before side effects?
- Error recovery: did the agent respond correctly to tool failures or empty results?
- Idempotency: did retries avoid duplicate side effects?
- Permission boundaries: did the workflow avoid tools it should not use?

These evals should be trace-aware. The final answer alone may look acceptable even when the internal tool path was wrong or unsafe.

### 5. Agent Workflow Evals

Agent workflow evals evaluate multi-step behavior across model calls, tools, memory, retrieval, guardrails, and handoffs. They should use traces as a first-class artifact.

Important dimensions include:

- Task completion: did the workflow accomplish the user's goal?
- Planning quality: did the agent choose a reasonable sequence of steps?
- Handoff behavior: did it escalate, delegate, or stop at the right time?
- State management: did it preserve relevant context across turns?
- Guardrail behavior: did safety, policy, and permission checks fire correctly?
- Recovery behavior: did it handle uncertainty, blocked tools, and partial failures?
- Workflow efficiency: did it avoid unnecessary calls, loops, or repeated work?

Early in development, trace grading is the fastest way to find workflow-level failures. Once recurring failure modes are understood, representative traces should be converted into repeatable datasets and eval runs.

### 6. Safety, Security, And Policy Evals

Production LLM systems need safety and security evals even when the primary task is not safety-sensitive. These evals should be treated as release-blocking when failures create user, business, legal, or data-protection risk.

Required categories include:

- Sensitive data handling: no leakage of secrets, credentials, hidden prompts, or private data.
- Prompt injection resistance: malicious retrieved content or user instructions cannot override system policy.
- Authorization boundaries: the agent cannot act outside the user's permissions.
- Unsafe content handling: regulated, harmful, or disallowed requests are handled according to policy.
- Compliance rules: outputs respect domain-specific constraints, disclaimers, and escalation requirements.
- Side-effect safety: destructive or external actions require the right confirmations and validations.

The dashboard should separate safety failures from ordinary quality failures and make their severity visible.

### 7. Robustness And Adversarial Evals

Robustness evals test behavior under messy, ambiguous, or intentionally difficult inputs. These cases prevent a suite from becoming too clean compared with production traffic.

Coverage should include:

- Ambiguous user requests.
- Missing required fields.
- Long or noisy context.
- Multi-turn drift and context carryover.
- Contradictory instructions.
- Typos, informal phrasing, and domain jargon.
- Internationalization and locale-specific formatting.
- Adversarial prompt injection.
- Edge cases from incident reviews and support escalations.

Robustness suites should be tagged separately from routine cases so teams can distinguish everyday readiness from challenge-set performance.

### 8. Human Experience Evals

Some workflows succeed technically but fail the user. Human experience evals measure whether the system is clear, useful, appropriately concise, and aligned with the user's actual job.

Dimensions include:

- Helpfulness and actionability.
- Clarity and organization.
- Appropriate uncertainty.
- Escalation quality.
- Respect for user preferences.
- Trust calibration: no overclaiming, hidden assumptions, or false certainty.
- Workflow completion from the user's perspective.

These evals usually need human review, at least for calibration. The dashboard should allow reviewers to annotate examples and convert reviewed failures into future automated checks where possible.

### 9. Operational Performance Evals

Production readiness includes cost, latency, throughput, and reliability. A system that answers correctly but is too slow or expensive may still be unshippable.

Metrics should include:

- End-to-end latency.
- Model latency by call.
- Tool latency by call.
- Token usage.
- Cost per run.
- Retry count.
- Error rate.
- Timeout rate.
- Tool-call count.
- Workflow step count.

Performance evals should be tied to product budgets. For example, an internal research agent may tolerate slower responses than a customer-facing chat workflow.

### 10. Model, Prompt, And Workflow Migration Evals

Any change to a model, prompt, tool contract, retrieval index, orchestration policy, or guardrail can change behavior. Migration evals compare the current production version with the candidate version.

The dashboard should support side-by-side comparison across:

- Model versions.
- Prompt versions.
- System/developer instructions.
- Retrieval settings and corpus versions.
- Tool schemas and tool implementations.
- Agent routing and handoff policies.
- Guardrail configurations.

Migration reports should show pass-rate deltas, changed outputs, cost deltas, latency deltas, and case-level regressions. A migration should not ship only because the average score improved if critical cases regressed.

### 11. Production Monitoring And Drift Evals

Offline evals are necessary but incomplete. Production systems need online monitoring to detect changes in traffic, data, models, tools, and user expectations.

Monitoring should include:

- Sampled production traces for human review.
- Automated grading of sampled runs.
- User feedback and correction capture.
- Drift in input topics, languages, lengths, and intent distribution.
- Drift in retrieved sources and tool errors.
- Spike detection for refusal rate, escalation rate, safety flags, cost, and latency.
- Failure mining that promotes real incidents into eval cases.

The dashboard should make production drift visible and support a workflow for turning observed failures into new regression cases.

### 12. Architecture Fit And Feasibility Evals

Architecture fit evals verify that the system design matches the work. They answer whether the task should be an augmented model call, deterministic workflow, agent, RAG system, document-processing pipeline, router, or multi-agent system.

These evals should check:

- Decomposition: which steps belong to the model, existing systems, and humans?
- Predictability: can the steps be enumerated in code, or is agentic planning necessary?
- Error cost: what happens if the model is wrong?
- Observability: can the team reconstruct the decision path?
- Latency and cost: does the chosen pattern fit production budgets?
- Reversibility: can a bad action be undone?
- Source of truth: does the workflow use retrieval for stable knowledge and tool calls for live state?

The key failure to catch is architecture overreach: using a model for deterministic rules, using RAG for current transactional state, or choosing an agent when a router and workflow would be more auditable.

### 13. Reliability And Degradation Evals

Reliability evals verify that the system behaves deliberately when dependencies fail. A production LLM workflow needs more than correct outputs on healthy calls.

Coverage should include:

- Transient model errors, rate limits, and timeouts.
- Retry behavior with bounded exponential backoff.
- Fallback chains across models, routes, cached responses, or human queues.
- Circuit-breaker behavior at service boundaries.
- Guardrail failures and whether each guardrail fails open or closed.
- Tool errors, empty tool responses, and authorization failures.
- Agent stopping behavior under token, turn, latency, and tool-call budgets.

These evals should be part of the release gate because reliability controls are much harder to retrofit after the first incident.

### 14. Experimentation And Shadow Testing Evals

Offline evals are the release gate, but live systems also need disciplined experiments. Every A/B test or shadow test should define the hypothesis, treatment, control, primary metric, secondary constraints, sample-size assumptions, and decision rule before the test starts.

The dashboard should support:

- Live A/B tests when limited user exposure is acceptable.
- Shadow tests when high-risk outputs should be scored without reaching users.
- Input distribution checks so treatment and control groups are comparable.
- Session-stable assignment to avoid contamination.
- Segmented analysis for rare but important input classes.
- Detection of secondary-metric regressions such as cost, latency, refusal rate, escalation rate, or safety flags.

An experiment that picks the winning metric after seeing the result is not evidence. It is confirmation.

### 15. Governance Evidence And Audit Evals

Governance evals verify that required controls exist, have owners, and produce evidence. This is separate from whether the model output looked good.

Coverage should include:

- Compliance obligations mapped to technical controls.
- Named owners for each control.
- Evidence artifacts that prove controls are live.
- Data residency, retention, and deletion checks.
- Decision logs that can reconstruct regulated or high-stakes outcomes.
- Scheduled review checkpoints for regulated workflows.
- Access-control and authorization evidence.
- Audit-ready status for each release gate.

The dashboard should treat "control not evidenced" as a failure state, even if the model output passed all quality checks.

### 16. Business Outcome Evals

Business outcome evals connect technical behavior to the reason the workflow exists. They should capture the baseline business metric before deployment, the same metric after deployment, and the control that makes the comparison auditable.

Examples:

- Average handle time before and after a support assistant launch.
- First-contact resolution rate for a customer service workflow.
- Time to draft or review a contract.
- Claims processing time or exception rate.
- Consultant acceptance rate for RFP drafts.
- Developer cycle time with AI-assisted workflows, paired with defect and review-quality metrics.

The dashboard should show technical metrics and business metrics together. A system with good latency and low error rate can still fail if it does not improve the outcome that funded it.

## Production Evaluation Workflow

### Step 0: Translate Discovery Into Testable Constraints

Before defining cases, capture the stakeholder's request as constraints the system can be measured against:

- What the system must do.
- What the system must not do.
- What the system must cost.
- What the system must prove.

Each requirement should preserve the original stakeholder statement, the implied constraint, the architectural decision it forces, and any assumption that still needs confirmation. This prevents vague goals such as "fast", "accurate", or "seamless" from becoming untestable product requirements.

### Step 1: Define The Product Promise

Every eval suite starts with a product promise. A promise is the behavior the system must provide to users, expressed in testable terms.

Good examples:

- "The billing support agent answers refund eligibility questions using the current policy and escalates ambiguous cases."
- "The research assistant answers only from retrieved sources and includes citations for factual claims."
- "The coding agent modifies only files relevant to the request and does not overwrite unrelated user changes."

Weak examples:

- "The model should be good."
- "The agent should be smart."
- "The answer should feel better."

The dashboard should require each suite to have an owner, product promise, risk level, target under test, and release-gate status.

### Step 2: Map The System Under Test

Before writing cases, map the path the user request takes through the system:

- Entry point or API endpoint.
- Delivery route, hosting boundary, or gateway.
- Prompt builder and prompt version.
- Model and model settings.
- Retrieval sources and ranking settings.
- Tool definitions and permissions.
- Agent orchestration and handoff logic.
- Guardrails and policy checks.
- Identity, authorization, and data-minimization controls.
- Output parser or schema validator.
- UI or downstream consumer.
- Human review, approval, or audit path.

This prevents the team from evaluating a raw prompt while production users hit a different workflow.

Also record the ownership split:

- What the model owns.
- What deterministic systems own.
- What humans own.

Then record the architecture pattern being evaluated: augmented call, workflow, agent, RAG, document-processing pipeline, router, multi-agent system, or a composed pattern. Each pattern has different failure modes and therefore needs different eval cases.

### Step 3: Build Versioned Datasets

Each eval case should be a durable artifact. A useful case includes:

- Stable case ID.
- Scenario description.
- Input messages or task payload.
- Required context fixtures.
- Expected behavior.
- Disallowed behavior.
- Scoring rubric or deterministic assertions.
- Severity if it fails.
- Source of the case, such as requirement, bug, support escalation, or production sample.
- Labels for feature, risk, customer segment, language, and workflow type.
- Data-sensitivity classification.

Datasets should be versioned. Teams should maintain separate subsets for smoke tests, release gates, regression coverage, challenge cases, and holdout evaluation. Holdout cases should not be used for day-to-day prompt tuning.

Production-derived cases must be sanitized. Secrets, customer data, and sensitive personal information should not be committed into fixtures.

### Step 4: Define Metrics And Graders

A suite should combine hard checks and graded checks.

Hard checks:

- Schema validity.
- Required fields.
- Allowed enum values.
- Citation presence.
- Tool name and argument shape.
- Forbidden content.
- Latency and cost budgets.
- Required escalation or refusal.

Graded checks:

- Correctness.
- Completeness.
- Groundedness.
- Instruction adherence.
- Tool-use appropriateness.
- User usefulness.
- Safety judgment.
- Clarity.

Rubrics should be specific enough that two reviewers can usually agree. A weak rubric asks whether an answer is "good." A stronger rubric names the required facts, acceptable uncertainty, disallowed claims, and conditions for pass, partial pass, or fail.

Each grader should also have operational metadata:

- Grader type: code, model, or human.
- Grader owner.
- Grader version or rubric version.
- Generator model and grader model, when model grading is used.
- Calibration status against human-labeled examples.
- Cost and latency per graded case.
- Known blind spots.

### Step 5: Instrument Runs And Traces

Every eval run should capture enough data to reproduce and debug behavior:

- Run ID.
- Suite ID and dataset version.
- Case ID.
- Target version.
- Prompt version.
- Model name and settings.
- Tool schema versions.
- Retrieval corpus and index versions.
- Input fingerprint.
- Final output.
- Intermediate model calls.
- Tool calls and tool results.
- Guardrail decisions.
- Trace ID.
- Human review route and reviewer decision, when applicable.
- Control evidence references.
- Deployment route and entry point.
- Errors and retries.
- Token usage, cost, and latency.
- Scores and grader explanations.
- Business outcome signals, when available.

For agent workflows, traces should be first-class objects in the dashboard. Teams need to inspect not only what the final answer said, but how the system got there.

For high-stakes decisions, logs must be queryable per decision and useful to three audiences: the affected user, the regulator or auditor, and the build team. That usually requires retaining the inputs, retrieved context, output, route, model/tool decisions, and the reason a case was escalated or approved.

### Step 6: Run Baselines And Compare Candidates

The dashboard should support comparison between a baseline and candidate:

- Current production vs new prompt.
- Current model vs candidate model.
- Current workflow vs new orchestration.
- Current retrieval index vs rebuilt index.
- Current tool schema vs proposed schema.

The comparison should show:

- Overall score delta.
- Pass-rate delta by dimension.
- Regressions by severity.
- Improvements by severity.
- Changed-but-unclear cases.
- Cost and latency deltas.
- Case-level artifacts for review.

Release decisions should be based on thresholds and severity, not only averages.

### Step 7: Gate Releases

Evaluation gates should run at multiple points:

- Local development: fast smoke suite.
- Pull request: changed-area regression suite.
- Staging: broader workflow suite with traces.
- Pre-release: critical and safety suites.
- Canary: live monitoring with rollback thresholds.
- Post-release: sampled production review.

Suggested first gate policy:

- Critical safety cases: 100 percent pass required.
- Schema and hard business rules: 100 percent pass required.
- Core task correctness: no severe regression from baseline.
- Grounding: no unsupported high-risk claims.
- Cost and latency: must stay within defined budgets or receive explicit approval.
- Judge-based quality: must meet threshold and pass human spot checks for important changes.
- Reliability: retries, fallbacks, circuit breakers, and guardrail failure directions must pass simulated failure cases.
- Agent and multi-agent workflows: turn limits, tool-call limits, shared trace IDs, and coverage reconciliation must pass.
- Governance: required controls must have current owners and evidence artifacts.

### Step 8: Triage Failures

Failures should be classified before fixes are attempted. Common causes include:

- Bad or incomplete prompt instructions.
- Weak or missing examples.
- Prompt rendering bug.
- Missing retrieval source.
- Retrieval ranking problem.
- Tool schema ambiguity.
- Tool implementation bug.
- Model limitation.
- Workflow routing error.
- Guardrail gap.
- Guardrail failing open when the risk requires failing closed.
- Dataset or expected-answer issue.
- Grader bug or overly brittle assertion.
- Model version, route, or SDK change.
- Data drift or input distribution drift.
- Context growth, cache miss, or token-budget exhaustion.
- Human review overload or missing reviewer context.
- Compliance control drift or stale evidence.

The dashboard should support assigning failures, tagging root cause, linking fixes, and rerunning only affected cases when appropriate.

Recurring failures should become runbook entries. A useful runbook entry maps symptom to likely architecture cause to first action, such as "quality degraded with no code change" mapping to model, prompt, or retrieval drift investigation.

### Step 9: Close The Improvement Loop

Evaluation improves systems only when failures turn into durable learning. The loop should be:

1. Observe a failure through evals, traces, monitoring, review, or user feedback.
2. Classify the failure mode and severity.
3. Add or update a representative eval case.
4. Fix the prompt, workflow, tool, retrieval layer, guardrail, or model configuration.
5. Run baseline vs candidate comparison.
6. Review regressions and tradeoffs.
7. Ship behind the appropriate gate.
8. Monitor production and feed new failures back into the dataset.

## Dashboard Implications

The evaluation dashboard should be designed around investigation and release decisions, not just charts.

Core entities:

- Project.
- Workflow.
- Eval suite.
- Dataset.
- Eval case.
- Target under test.
- Architecture pattern.
- Ownership split.
- Prompt version.
- Model configuration.
- Tool schema version.
- Retrieval corpus version.
- Context strategy.
- Deployment route or entry point.
- Eval run.
- Trace.
- Grader.
- Score.
- Failure.
- Human review.
- Release gate.
- Control.
- Evidence artifact.
- SLA.
- Experiment.
- Business outcome metric.
- Runbook entry.
- Decision record.

Core views:

- Run history with baseline and candidate comparison.
- Suite overview with pass rates by dimension and severity.
- Case drill-down with input, output, expected behavior, scores, and trace.
- Regression report for prompt, model, retrieval, tool, or workflow changes.
- Failure triage board grouped by root cause and owner.
- Safety and policy failures view.
- Cost and latency trend view.
- Dataset coverage view by feature, risk, source, and case type.
- Human review calibration view.
- Production monitoring view with sampled traces and drift signals.
- Architecture-fit view showing model, system, and human ownership by step.
- Governance control register with owner, evidence, status, and revalidation cadence.
- Human review queue with inputs, output, trace, confidence, stakes, and flag reason.
- A/B and shadow-test view with hypothesis, primary metric, sample size, and decision rule.
- Feedback-loop view mapping signals to triggers, owners, actions, and review cadence.
- Business outcome view comparing before and after metrics with audit evidence.
- Runbook view mapping symptoms to likely causes and first actions.

The first dashboard should not try to solve every evaluation problem. It should make one narrow workflow trustworthy end to end: dataset, run, score, trace, compare, triage, and release decision.

## Recommended Initial Evaluation Suites

For this project, the initial evaluation catalog should include these suites:

1. Prompt contract suite.

   Verifies schema, formatting, instruction adherence, tone, refusals, clarifying questions, and no leakage of hidden instructions.

2. Workflow task-completion suite.

   Measures whether each target workflow completes the user's job under normal, edge, and failure conditions.

3. Retrieval grounding suite.

   Verifies that answers use retrieved evidence, cite correctly where required, and avoid unsupported claims.

4. Tool-use suite.

   Checks tool choice, argument shape, sequencing, permission boundaries, error handling, and idempotency.

5. Agent trace suite.

   Scores traces for planning, tool use, handoffs, guardrails, recovery, and unnecessary loops.

6. Safety and policy suite.

   Exercises data leakage, prompt injection, unsafe requests, authorization boundaries, side-effect confirmation, and domain policy requirements.

7. Migration suite.

   Compares current and candidate prompts, models, workflow settings, retrieval settings, and tool contracts before release.

8. Production monitoring suite.

   Samples production traces, tracks drift, captures user feedback, and promotes real failures into regression cases.

9. Operational budget suite.

   Tracks latency, cost, token use, retries, tool-call count, error rate, and timeout rate.

10. Architecture-fit suite.

   Confirms the workflow decomposition, architecture pattern, data-access mechanism, and human-review placement match the task's predictability, stakes, observability, latency, cost, and reversibility.

11. Reliability and degradation suite.

   Exercises retries, fallback chains, circuit breakers, dependency failures, guardrail failures, timeouts, tool errors, and agent stopping criteria.

12. Experimentation suite.

   Captures A/B and shadow-test hypotheses, treatment/control assignment, primary metrics, sample-size assumptions, secondary constraints, and decision rules.

13. Governance evidence suite.

   Verifies that controls have owners, evidence artifacts, audit-ready status, and scheduled revalidation.

14. Business outcome suite.

   Tracks before and after business metrics and connects them to the technical metrics and controls that make the outcome auditable.

## Minimum Viable Eval Case Schema

The dashboard should support a case structure similar to this:

```yaml
id: support-refund-eligibility-001
suite: billing-support-grounding
status: active
source: product-requirement
severity: high
architecture_pattern: rag_workflow
source_of_truth:
  stable_knowledge: retrieval
  live_state: tool_call
labels:
  workflow: billing-support
  type: grounding
  risk: customer-impact
  language: en-US
ownership:
  model: "Draft grounded answer."
  system: "Retrieve policy and validate citation support."
  human: "Approve ambiguous refund exceptions."
input:
  messages:
    - role: user
      content: "Can I get a refund if I cancelled after 10 days?"
fixtures:
  retrieval_docs:
    - refund-policy-v4.md
expected:
  behavior: "Answer using the current refund policy and escalate if the cancellation date is ambiguous."
  must_include:
    - "current refund eligibility window"
  must_not_include:
    - "unsupported exceptions"
assertions:
  - type: schema
  - type: citation_support
  - type: no_unsupported_claims
rubric:
  correctness: "Pass if the answer applies the current policy accurately."
  groundedness: "Pass if every factual policy claim is supported by the supplied policy document."
  escalation: "Pass if ambiguous dates trigger a clarifying question or escalation."
grader:
  type: model
  rubric_version: refund-grounding-v1
gate:
  release_blocking: true
  rollback_threshold: "Any unsupported high-risk policy claim fails the release."
controls:
  - name: citation_support_check
    owner: ai-platform
    evidence: eval-run-artifact
business_outcome:
  metric: first_contact_resolution_rate
```

This schema can evolve, but the first implementation should preserve stable IDs, labels, expected behavior, assertions, rubrics, severity, source, architecture pattern, ownership, control evidence, grader metadata, release gate status, and business-outcome linkage.

## Production Readiness Checklist

Before an LLM prompt, workflow, or agent is treated as production-ready, it should have:

- A named owner.
- A documented product promise.
- A discovery translation table covering what the system must do, must not do, must cost, and must prove.
- A decomposition map showing what the model owns, what deterministic systems own, and what humans own.
- A documented architecture pattern and the failure modes specific to that pattern.
- Versioned prompts or workflow definitions.
- Instrumentation for prompts, traces, tools, retrieval, cost, latency, and errors.
- Server-side identity and authorization boundaries for any protected data or side-effecting action.
- Data-minimization and redaction decisions for all fields entering prompts, retrieval, tools, traces, and logs.
- A smoke eval suite runnable locally.
- A release-gate suite runnable in CI or staging.
- Safety and policy cases for high-risk behavior.
- A baseline run for the current production version.
- A candidate comparison report for every behavior change.
- Predefined thresholds, rollback criteria, and experiment metrics.
- Reliability tests for retries, fallbacks, circuit breakers, tool failures, and guardrail failure direction.
- A human review path for subjective or high-risk cases.
- A review-routing rule based on confidence, reversibility, and cost of a wrong answer.
- A control register with owners, evidence artifacts, and audit-ready status.
- A feedback-loop table mapping signals to triggers, owners, actions, and review cadence.
- A runbook mapping known symptoms to likely causes and first actions.
- Before and after business outcome metrics with an owner for ongoing measurement.
- A process for converting production failures into regression cases.

## Important Platform Notes

The OpenAI documentation reviewed for this draft recommends eval-driven development, task-specific evals, logging, automated scoring where possible, human calibration, and continuous evaluation. It also distinguishes trace grading for debugging agent workflows from repeatable dataset-based eval runs once desired behavior is understood.

As of the documentation available on 2026-09-06, OpenAI's Evals platform is being deprecated, with existing eval content becoming read-only on 2026-10-31 and the platform scheduled to shut down on 2026-11-30. The dashboard architecture should therefore use a portable internal data model for suites, datasets, runs, graders, traces, and scores instead of depending on a deprecated hosted eval object model.

OpenAI's prompt guidance also recommends keeping production prompts in application code, using typed inputs or schemas, adding representative fixtures and evaluation checks before changing production prompts, and rolling out prompt changes through the normal deployment system with feature flags or configuration when staged releases are needed.

## Anthropic Evaluation Process Review

Anthropic's evaluation guidance reinforces the same production discipline and adds useful implementation pressure: define measurable success criteria before prompt engineering, build task-specific evaluations around the real distribution of use, and make grading cost part of the eval design. Anthropic frames prompt engineering as an empirical loop: test cases, preliminary prompt, iterative testing and refinement, final validation, and ship.

Key practices to incorporate:

- Define success criteria first. Criteria should be specific, measurable, achievable, and relevant. Anthropic's examples include measurable thresholds for task fidelity, toxicity rate, severity of errors, latency, and baseline improvement.
- Evaluate multiple dimensions. Anthropic calls out task fidelity, consistency, relevance and coherence, tone and style, privacy preservation, context utilization, latency, and price. This supports our decision to model eval results as dimensional scores, not a single aggregate grade.
- Use held-out test sets. Prompt and workflow tuning should not consume every case. The dashboard should support holdout datasets that are protected from day-to-day optimization and used for final validation.
- Mirror production traffic, including edge cases. Anthropic explicitly recommends task-specific evals that reflect the real distribution and include irrelevant inputs, nonexistent inputs, long inputs, harmful inputs, and ambiguous cases.
- Automate grading wherever possible. Anthropic recommends structuring questions so they can be graded through exact match, string match, code graders, or LLM graders. Human grading remains valuable for nuanced tasks, but it is slow and should be reserved for cases where automation is not reliable enough.
- Prefer the fastest reliable grader. Anthropic's recommended grading order is code-based grading first, human grading for maximum flexibility when necessary, and LLM-based grading for scalable complex judgment after testing reliability.
- Design around recurring grading cost. Writing cases and golden answers is usually a one-time cost; grading runs every time the suite is executed. This means the dashboard should track grader type, grader cost, grader latency, and confidence in grader reliability.
- Make rubrics concrete. LLM-based graders should use detailed rubrics and emit empirical outputs such as binary labels, ordinal scores, or structured results. Subjective free-form judgment should be converted into explicit pass, partial pass, or fail criteria where possible.
- Separate generation from grading. Anthropic cookbook examples note that it is generally better to use a different model to grade than the one that produced the evaluated output. The dashboard should record both generator and grader model configurations.
- Use synthetic case generation carefully. Anthropic suggests using Claude to generate more test cases from baseline examples or to brainstorm evaluation methods. Those generated cases still need review, deduplication, severity labels, and data-sensitivity checks before they become release gates.
- Treat prompt engineering as only one possible fix. Anthropic's prompt overview notes that not every failing eval is best solved by prompt changes. Some failures should be addressed through model choice, retrieval, tool design, structured outputs, latency work, or workflow decomposition.
- Evaluate structured output separately. Anthropic's consistency guidance recommends precise output formats and structured outputs when guaranteed JSON schema conformance is required. Our dashboard should therefore distinguish "valid structure" from "correct content."
- Evaluate retrieval independently from end-to-end answer quality. Anthropic's RAG cookbook separates retrieval precision, recall, F1, mean reciprocal rank, and end-to-end answer accuracy. This confirms that retrieval failures should not be hidden inside a generic answer-quality score.
- Evaluate tools as products. Anthropic's tool evaluation cookbook tracks actual response, expected response, duration, tool-call count, per-tool durations, and agent feedback about tool names, parameter clarity, schema documentation, errors, and missing capabilities. Our tool-use suite should evaluate both agent behavior and tool usability.

Dashboard implications from Anthropic's process:

- Each suite should require a success-criteria section with measurable thresholds.
- Each case should distinguish golden answer, rubric, hard assertions, and expected behavior.
- Eval results should store grader type: code, human, or model.
- Model-graded results should store grader model, rubric version, structured score, and explanation.
- Dataset management should support routine, edge, challenge, production-derived, synthetic, and holdout subsets.
- Release reports should show score deltas by dimension, cost deltas for generation and grading, and latency deltas for both the system under test and the grader.
- Tool eval reports should include tool-call counts, per-tool durations, tool errors, and schema-feedback fields.
- RAG eval reports should split retrieval metrics from final-answer metrics.
- The dashboard should make it easy to identify whether the likely fix is prompt, model, retrieval, tool, guardrail, orchestration, data, or grader logic.

## Local Claude Architect Module Learnings

The five added module files add a broader production-architecture lens to the eval strategy:

- Module 1, solution design: Decompose work before architecture. The eval dashboard should check whether each step belongs to the model, deterministic systems, or humans, and whether the chosen pattern fits the task's predictability, stakes, observability, latency, cost, and reversibility. It should also catch architecture category errors such as using retrieval for live state or using an agent where a workflow would be auditable.
- Module 2, enterprise integration and production: Treat evals as acceptance criteria before code, keep golden datasets representative and current, model production cost and p95 latency before launch, and test retries, fallbacks, circuit breakers, and architecture-specific failure modes. It also adds disciplined A/B and shadow-test design.
- Module 3, responsible AI and risk: Safety is a layered stack. The dashboard should distinguish trained model behavior from deployment-specific policy, test input screening, output screening, and deterministic action authorization, track guardrail fail-open/fail-closed behavior, evaluate fairness injection points, and maintain a control register with owners and evidence.
- Module 4, stakeholder lifecycle: Discovery should become testable constraints, and observability must feed a feedback loop with triggers, owners, actions, and review cadence. Evaluation should connect technical metrics to before and after business outcomes, not only system health.
- Module 5, team enablement and productivity: Shared prompts, skills, tools, and configs need versioning, owners, rollout control, and rollback. The dashboard should support verification checklists, adoption/runbook workflows, and symptom-to-cause operational guidance so teams can respond to drift without relying on one specialist.

## Next Design Questions

The next phase should answer:

1. Which first production workflow will be evaluated end to end?
2. What target under test should the dashboard call: API endpoint, job runner, local adapter, agent trace exporter, or hosted workflow?
3. Which eval runner should execute suites in v1?
4. What trace format will be stored?
5. What case schema and run schema should become the canonical database model?
6. Which metrics are release-blocking vs informational?
7. Who can approve a failed gate or mark a failure as accepted risk?
8. How will production data be sanitized before it becomes an eval fixture?
9. How will the dashboard connect eval results to deployment versions?
10. What is the smallest dashboard slice that supports dataset, run, score, trace, compare, triage, and release decision?
11. How will the dashboard represent model, system, and human ownership for each workflow step?
12. Which controls require evidence artifacts and scheduled revalidation?
13. Which production signals trigger team action, stakeholder review, or no action?
14. Which business outcome metric must be captured before launch for the first workflow?
15. Which experiment types will v1 support: offline comparison, shadow test, live A/B test, or all three?

## References Reviewed

- OpenAI, "Evaluation best practices": https://developers.openai.com/api/docs/guides/evaluation-best-practices
- OpenAI, "Evaluate agent workflows": https://developers.openai.com/api/docs/guides/agent-evals
- OpenAI, "Prompt engineering": https://developers.openai.com/api/docs/guides/prompt-engineering
- OpenAI / ChatGPT Work, "Add evals to your AI application": https://learn.chatgpt.com/use-cases/ai-app-evals
- Anthropic / Claude Platform, "Define success criteria and build evaluations": https://platform.claude.com/docs/en/test-and-evaluate/develop-tests
- Anthropic / Claude Platform, "Prompt engineering overview": https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview
- Anthropic / Claude Platform, "Increase output consistency": https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/increase-consistency
- Anthropic / Claude Cookbook, "Building evals": https://platform.claude.com/cookbook/misc-building-evals
- Anthropic / Claude Cookbook, "Tool evaluation": https://platform.claude.com/cookbook/tool-evaluation-tool-evaluation
- Anthropic / Claude Cookbook, "Retrieval augmented generation": https://platform.claude.com/cookbook/capabilities-retrieval-augmented-generation-guide

## Local Files Reviewed

- Module1-Claude-Platform-Solution-Design.md
- Module2-Enterprise-Integration-Production.md
- Module3-Responsible-AI-Safety-Risk.md
- Module4-Stakeholder-Engagement-Lifecycle-GTM.md
- Module5-Team-Enablement-Operational-Productivity.md

