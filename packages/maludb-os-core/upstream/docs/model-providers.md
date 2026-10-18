# Model providers — what leaves this server, to whom, under what terms

> A control-register entry in the making (Claude Architect Module 3: "validate whether logs, caches,
> monitoring, and retention paths remain within the approved boundary"; training use and retention are
> **separate claims**). Whatever an agent reads becomes part of a prompt and goes to that agent's model
> provider. **Owner: the platform owner. Revalidate: every quarter, and whenever a provider or a model is
> added.** Checked 2026-09-20 against each provider's own published pages; "not verified" means I did not
> find it stated, not that it is false.

| | Anthropic (API) | Fireworks AI (serverless) | DeepSeek (direct API) |
|---|---|---|---|
| Used for agents | Jack, Becky, Sasha (Sonnet 5); the assistant; the eval judge | none yet (5 models registered) | **Seamus** (DeepSeek Flash) |
| Trains on our inputs/outputs | **No, by default** — "we will not use your inputs or outputs from our commercial products (e.g. … Anthropic API …) to train our models"; exception: feedback we explicitly submit | not verified | **Yes, unless opted out** — data is used "to train and improve our technology, such as our machine learning models"; the policy gives a "right to opt-out"; the mechanism is not described |
| Retention | not stated in that article (Fable-class models are not offered under zero retention) — not verified | **Zero by default** — "does not log or store prompt or generation data for any open models, without explicit user opt-in" (their Response API with `store=True` keeps 30 days; we do not use it) | "for as long as you have an account"; no fixed period |
| Where it is processed | not verified | not verified (their "(US)" model variants, 1.5× the price, are the ones that promise US inference) | **"we directly collect, process and store your Personal Data in People's Republic of China"** |
| Which terms govern API use | Commercial Terms | platform terms — not read | the privacy policy says data from "downstream systems… developed by developers using our open platform" is **not covered by it**; the Open Platform terms that do cover it — **not read** |
| Evidence | privacy.claude.com article 7996868 | docs.fireworks.ai → security & compliance → data handling | cdn.deepseek.com privacy policy (en-US) |

## What follows from it

1. **DeepSeek direct should not see the books, payroll, contacts or mail** until its Open Platform terms
   are read and an opt-out from training is actually exercised. Seamus is on it today; his reach is the
   `recall` tool over Front Office and organisation memory. That is a small exposure, but it is business
   information going to a service that stores it in China and may train on it.
2. **The same DeepSeek models are served by Fireworks** (`deepseek-v4p1-flash` at the same price as
   DeepSeek's own Flash, `deepseek-v4-pro-0813`) under a zero-retention default. The owner asked for the
   non-DeepSeek Fireworks models only; this finding is a reason to revisit that for any agent whose work
   touches sensitive records.
3. **The registry cannot express any of this yet.** A model row has prices and a provider, not "which
   classes of data may go here". Proposed: a `data_classes_allowed` setting per provider, checked when a
   model is chosen for an agent against what that agent's grants can reach. Needs the owner's word — it
   is new schema.
4. **The prompt ledger is the fourth copy of everything.** Full payloads, no retention rule, no
   redaction, visible only through permission-gated views. Decision owed (owner): keep forever / keep
   payloads N months and the ledger row forever / redact named fields at the proxy. Until then: forever.
