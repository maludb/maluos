# Claude Certified Architect — Module 2: Enterprise Integration & Production

*Source: Anthropic Partners Skilljar (personal study notes)*

---

<!-- S01 -->

*Module shell · 2 min*

### Orientation: what you will be able to do by the end

Module 1 introduced architectural concepts. This module dives deep into the specifics.

This module gives you the specific tools that separate a prototype from a production system: a quality gate before you build, a cost and reliability model before you deploy, a feasibility framework before you commit, an integration architecture that survives security review, and an experimentation method that tells you whether changes actually work.

### By the end of this module, you will be able to:

- 1Define success criteria and build an eval suite before writing the first line of production code, distinguishing model-based from code-based evals, selecting eval workflow stages, and using evals as the gating mechanism for any change to a production system.
- 2Work through the POC-to-production checklist, mapping cost and latency to a budget, specifying reliability patterns (retries, fallbacks, circuit breakers), naming failure modes for the chosen architecture, and articulating the mitigation for each, including how to make agents (systems that use tools, reason across turns, and take multi-step actions) production-reliable.
- 3Create a use case by estimating call volume, token consumption, and cost, assess technical feasibility against the four AI properties from AI Capabilities and Limitations, and translate a business problem into a scoped solution architecture with explicit boundary conditions.
- 4Architect a Claude deployment that is ready for the enterprise by specifying integration patterns for compliance (regulated-industry constraints, BAA coverage, data-residency), identity (SSO/OAuth), authorization, data handling, and observability instrumentation. Place the right integration point (API, SDK, MCP, Claude Code) at each integration point.
- 5Plan and interpret an A/B test or structured experiment on a live Claude system, setting the hypothesis, selecting metrics, estimating the required sample size, and reading a result without overclaiming.

This module assumes a strong systems background and builds directly on Module 1. It skips foundational concepts and goes deep on the decisions that separate a prototype from a production system.

> **Disclaimer / Notice for Educational Content**
> 
> We built this Architect course Module 2: Enterprise Integration & Production to help you get real work done with Claude. Treat it as educational content. It doesn't constitute legal, financial, or other professional advice, so adapt what you learn to your own situation. Our products and services evolve quickly, so certain content may contain errors or be outdated; remember to verify on Anthropic's website or docs. Examples and scenarios used in the course are illustrative and often fictitious. If the course material mentions a company or product, it doesn't mean Anthropic endorses them, they endorse Anthropic, or that we're affiliated. Also note your use of Anthropic products and services is covered by our terms, policies and documentation; if anything in this course conflicts with them, they control.

---

<!-- S02 -->

*Teaching · Evals · 17 min*

### Evals as acceptance criteria: building quality into the build process

In the first module, you made architecture decisions: patterns, integration points, and how your system should respond to different inputs. What you don't have yet is confidence that those decisions hold when the inputs are real and the users are unpredictable.

This is where evals come into the picture. Evals are short for evaluations, and they let you test your system's behavior before it goes to production or after model updates, so you discover problems before they occur. This section explains what evals are, why they matter, and how to use them to get ahead of issues before your users find them for you.

#### Evals before code: why the order matters

An **eval**, or evaluation, is a structured test that checks whether your system returns the expected and accurate output. Although it sounds straightforward, the timing is extremely important. The standard approach is to build the system, see if it looks right, and conduct tests later. This isn't always the best approach.

Writing your eval suite before you write production code forces three things to happen that are otherwise easy to defer:

- First, state what success means in measurable terms
- Second, expose design assumptions early, when changing them is still cheap
- Third, give yourself a gate that can determine whether a model swap, a prompt change, or a new retrieval strategy measurably improved the system

An eval suite belongs at the beginning of your build, defined before production code is written, rather than at the end as a QA step. In fact, if you cannot write an eval for behavior, then you have no reliable way to measure whether that behavior is present. This means that every change you make to the system isn't verifiable. Adding an eval suite at the beginning allows you to verify throughout the entire build.

#### How the eval workflow runs: from task definition to result

A well-constructed eval workflow runs sequentially through the stages below. Each stage produces an artifact that feeds into the next stage:

| Stage | What happens | Output |
| --- | --- | --- |
| **1. Define the task** | State the behavior you are evaluating in specific, measurable terms, and write the prompt you will use to test it. A vague definition produces a vague eval. The level of concreteness of both the behavioral specification and the prompt is what makes the result meaningful. | Task specification with prompt to test and pass criteria |
| **2. Build the golden dataset** | Assemble the inputs that your system will encounter, including edge cases and counterexamples. This dataset is what your eval runs against. If the dataset is not representative, then the scores are not meaningful. | Labeled dataset with expected outputs |
| **3. Run automated checks** | Pass each prompt through the system and compare the output against your expected result. Automated checks are fast and cheap. Use them for behaviors that are unambiguous: format compliance, schema validation, and factual lookups against authoritative data. | Pass/fail record per item |
| **4. Score with a judge** | For behaviors that require interpretation, such as tone, accuracy of reasoning, and appropriateness of edge-case responses, a model-based judge can assess the outputs at scale. | Score per item with reasoning |
| **5. Interpret and act** | Aggregate scores tell you where the system is and whether a change moved it in the right direction. A change that raises the mean score while quietly degrading performance on edge cases or adversarial inputs doesn't make the system better. | Overall score, per-category breakdown |

#### Model-based vs. code-based evals: when to use each

Not every behavior you need to evaluate can be checked the same way. Some behaviors have a single correct answer: the output is either a valid JSON, or it isn't. A second category is whether the output matches the expected tone or style of language. These two categories of behavior need different evaluation tools, and choosing the right one for a given behavior is important to ensure accuracy and save costs.

The three types of evals have different speed-versus-flexibility tradeoffs:

- **Code-based evals** run deterministic checks in milliseconds and cost almost nothing.
- **Model-based evals** use a judge model to assess outputs that require interpretation and cost roughly as much as the model call itself.
- **Human-review evals** rely on human judgment for high-stakes or novel behaviors where neither code nor a model judge can be trusted to evaluate reliably. Human-review evals are the slowest and most expensive option.

| Eval type | How it works | When to use it | Cost | Limitation |
| --- | --- | --- | --- | --- |
| **Code-based eval** | A function checks the output programmatically: schema validation, regex match, JSON parse, length check, assertion against authoritative data. | Any behavior that is unambiguous. Format compliance, schema correctness, lookup accuracy, length constraints. | Very low: milliseconds per check, no API call. | Can't assess behaviors that require interpretation. Tone, helpfulness, reasoning quality, and edge-case appropriateness all require judgment that a function cannot supply. |
| **Model-based eval** | A judge model receives the original prompt, the system output, and a scoring rubric. The judge returns a score and reasoning. The judge prompt is itself a prompt that needs to be engineered and tested. | Any behavior that requires interpretation: response quality, instruction following, reasoning accuracy, safety, and handling of ambiguous inputs. | Medium to high: one API call per item evaluated, at the judge model's per-token rate at scale, this adds up. | Judge models can be inconsistent in borderline cases. Without forcing the judge to produce reasoning alongside the score, that inconsistency is difficult to detect |
| **Human-review** | A human evaluator reads the output and scores it against a rubric or set of criteria. This may be structured (a scoring sheet) or unstructured (open annotations and feedback). | High-stakes or novel behaviors where neither a function nor a judge model can be trusted: safety-critical edge cases, new capability areas without established rubrics, or any output where a wrong evaluation carries significant risk. Also useful for calibrating and validating model-based evals. | High: human time is the most expensive resource, and throughput is limited. Not viable at scale without sampling. | Slow, expensive, and not scalable beyond sampled subsets. Human evaluators also introduce their own inconsistency. |

#### The grading ladder: choosing how to grade

Not every behavior should be graded the same way, and the choice of grading method follows a deliberate ladder. Reach for the cheapest reliable method first and climb only when the behavior demands it.

- **Code-based grading, wherever the behavior allows it.** Deterministic checks, including schema validation, exact match, length, and presence, run in milliseconds, cost almost nothing, and never drift. If a behavior can be checked in code, then it should be.
- **LLM-as-judge, when the behavior needs interpretation.** Use a judge model for outputs that require judgment. Make the judging rigorous by using detailed rubrics, constrained verdicts (a small fixed set of labels rather than free-form scores), calibration against human-labeled examples, and grading with a *different* model than the one whose outputs you're evaluating, to avoid self-preference.
- **Human grading, as the last resort.** Reserve human review for high-stakes or novel behaviors where neither code nor a calibrated judge is trustworthy yet. It is the most expensive and least scalable option.

> **Judge calibration: the step many teams skip**
> 
> An LLM judge is itself a system that can be wrong. Before you trust its verdicts, make sure to calibrate it. To do this, run it against a set of human-labeled outputs and confirm its similarity with human judgment is high enough to rely on. An uncalibrated judge produces confident scores that may not be high quality at all. This is worse than no automated grade, because it *seems* trustworthy.

Favor volume over perfection. Many automatically gradable cases beat a handful of manually-graded ones: broad, cheap coverage catches more regressions than a small, painstaking set, and it can run on every change.

#### Defining success criteria: turning a business requirement into a measurable threshold

A business requirement like "summarize claims accurately" does not really tell you what to measure. The process of turning it into an eval criterion has the following steps:

- **Identify the behavior specifically:** "Summarize claims accurately" should be updated to "extract the filer's name, claim number, incident date, and claimed amount from each document."
- **Set the threshold:** Decide what counts as passing. If, for example, your thresholds are 100% accuracy on structured fields, less than 2% hallucination rate, and response within schema 99.5% of the time, those numbers should come from the business requirement. Don't just choose what your first prototype happens to achieve; find guidance on setting eval thresholds at *platform.claude.com/docs/en/test-and-evaluate/develop-tests*.
- **Identify the failure modes:** Continuing with the same example, an output that might not be acceptable can include a fake claim number, a missing incident date, or a value from the wrong claim. Each failure mode is a category in your eval dataset.
- **Include adversarial inputs:** It should include documents with missing fields, handwritten sections, unusual formatting, and non-standard layouts. If your golden dataset contains only clean inputs, then your eval scores will not predict production performance.

#### Evals as the gating mechanism for change

Every change to a production Claude system, whether it is a model swap, a prompt revision, a context strategy change, or a retrieval configuration update, should run through the eval suite during development before it moves to production. This is the only reliable way to know whether a change has improved the system.

A single-turn eval set will not tell you how the system holds up across a conversation. Multi-turn evals are a separate category that scores the system over a sequence of exchanges rather than on a single prompt and response. A multi-turn eval checks a few criteria: whether the system keeps prior context straight across turns, whether it answers a follow-up prompt without inventing details that were never said earlier in the conversation, and whether output quality holds as the conversation runs longer. Because the unit being scored is a whole conversation, this category needs its own golden dataset. This consists of full conversation transcripts with known high quality responses at each turn, covering the follow-ups, topic shifts, and conversation lengths the system will see in production.

Consider a team building a document summarization workflow that revised their summarization prompt but did not update their eval suite to match. The eval suite passed all required checks. Two days after the swap went to production, field reports showed that multi-clause legal sentences were being truncated into summaries. The root cause was that the eval set predated the prompt change and didn't match the behavior that changed.

In short, you should run evals before every change to keep the eval set current with the system it is measuring.

> **Cost · Complexity · Risk**
> 
> **Cost:** Every model-based eval is an API call. Although cost is worth keeping in mind, don't let it drive you toward a smaller eval set than your use case warrants. The bigger risk is under-evaluating: a production-breaking change that slips through an undersized eval suite costs far more than a few extra API calls. Size your dataset against what gives you confidence in your results and treat cost as a secondary constraint.
>  **Complexity:** Eval infrastructure adds a parallel system to maintain. The golden dataset must be kept current, the judge prompts must be engineered and tested, and the pass thresholds must be revisited when the system's requirements change. Where to go next: For working implementation patterns, including a walkthrough of grading designs and golden-answer comparison, see the Claude Cookbooks at *github.com/anthropics/claude-cookbooks/blob/main/misc/building_evals.ipynb*.
>  **Risk:** An out-of-date eval suite provides false confidence. It creates the misleading impression that a change is safe when the checks are measuring behavior that no longer exists in the system. The highest risk moment for a regression is when evals are present and out of date.

---

<!-- S03 -->

*Watch Out · Evals · 5 min*

### The eval suite that measured the wrong thing

> **Why this mistake happens**
> 
> When a demo is working, declaring it "good enough" feels like a reasonable call. Manual spot-checks take time, and the system seems to respond correctly on every input tested. What makes this an issue is that teams can only test inputs they thought of, whereas production surfaces the rest.

#### A partner postmortem that needs to be reconstructed

The following is a composite postmortem representing a pattern that appears repeatedly in field deployments. The team built a contract review assistant for a professional services firm. They manually tested the assistant against ten contracts their team knew well, declared the system ready, and then moved to production. The regression arrived two weeks later.

### What the postmortem found

The system was failing on a class of contracts it had never been tested against, namely those with non-standard obligation structures. The model was extracting obligations from the wrong section.

The eval suite existed. It was built at the start of the project and had been built from the ten contracts the team used during development. This was not a representative sample of the full contract population.

When the prompt changed, the eval suite kept passing, but only because the golden dataset still reflected the old prompt's expected outputs. It had never been updated to account for the new behavior.

#### The decisions that led us here

- **The eval dataset was built from convenient inputs rather than a representative sample.** An eval suite that does not cover the input distribution it will face in production is measuring a different system than the one you are shipping.
- **The eval input set was not updated after the prompt was changed.** The eval was still passing every time because it was assessing behavior the prompt no longer produced. The scores looked stable because nothing was testing what had changed.
- **Manual spot-checks were treated as an eval substitute.** Spot-checks can confirm that a specific input produces a specific output, but they cannot tell you whether the system behaves correctly on unknown inputs.

> **What to Watch Out for**
> 
> The eval suite was present but misconfigured in two ways: the dataset was not representative, and it was not kept current. Both problems are invisible until production exposes the gap. The system looked healthy in development because it was only tested on inputs it was already optimized for.

---

<!-- S04 -->

*Checkpoint · Evals · 5 min*

### Sort the eval types

Eight evaluation tasks are listed below. Drag each one into the bucket where it belongs: model-based eval or code-based eval. The right placement follows whether the behavior being checked requires interpretation or is straightforward.

**Sorting exercise (answer key):**
- **Code-based eval:**
  - 1. Check that every response is valid JSON matching the defined output schema.
  - 3. Verify that the response length is under 500 tokens.
  - 5. Confirm that the extracted claim number matches the quantitative value in the source document.
  - 7. Verify that all required sections (executive summary, methodology, findings, recommendations) are present in the output.
- **Model-based eval:**
  - 2. Assess whether the model's reasoning in a complex analysis is sound and complete.
  - 4. Score how appropriately the system handles an emotionally charged customer complaint.
  - 6. Evaluate whether the summary captures the most important points from a long briefing document.
  - 8. Assess whether the tone of a customer-facing message is appropriately professional for the brand.

**Course answer data:**
**CUES:**
- **1.** Schema validation is deterministic. A function either parses or it does not. No interpretation is required.
- **2.** Reasoning quality requires judgment. A deterministic function cannot score whether an argument is logically complete.
- **3.** Length is a number. This is a one-line assertion, so it does not require interpretation.
- **4.** Appropriateness is a judgment. The range of valid responses is too wide and context-dependent for a deterministic check.
- **5.** Quantitative value comparison is a string match. The expected value is known, so a function can check it.
- **6.** Importance and completeness are interpretive. The LLM-as-a-judge model is needed to assess whether the right items were included.
- **7.** Section presence is a simple checklist where each heading either exists in the output or doesn't. No interpretation is required.
- **8.** Brand voice and tonal appropriateness are judgment calls that a function cannot encode reliably.

---

<!-- S05 -->

*Teaching · POC to Prod · 16 min*

### From POC to production: cost, latency, and reliability

Your eval suite tells you whether the system behaves correctly, but nothing about whether it can afford to behave correctly at the volume your partner expects. That gap is the Proof of Concept (POC)-to-production gap, and it has four dimensions: cost, latency, reliability, and failure modes. All four are invisible in a demo.

A POC also gives you the first signal on whether the system moves the business metric it was designed to improve. That signal is worth capturing deliberately: measure the outcome the partner cares about on your POC sample, even before you model production cost. A cost profile that fits the budget on a system that does not produce a measurable improvement in the metric that matters is still a failed deployment.

#### Where a Proof of Concept (POC) and a production system differ

A POC is designed to demonstrate capability. It runs at low volume, on clean inputs, and with a patient user. A production system runs at the volume your partner's business generates, on real inputs, and with users who have no tolerance for slow or incorrect responses. The four dimensions where a POC misleads you are cost, latency, reliability, and failure modes.

| Dimension | Why it's invisible in a demo | What it looks like when it fails |
| --- | --- | --- |
| **Cost** | A POC running 10–50 requests per day produces a negligible bill. Monthly cost projections at production volume are a different calculation entirely. | The billing dashboard shows a cost that exceeds the budget signed off at project approval. The architecture must be renegotiated after deployment. |
| **Latency** | A demo typically runs one request at a time. Latency p95 under concurrent load is a different number than median latency under a single request. | SLA breaches and user abandonment. Latency that is acceptable for a demo can be unacceptable for a real-time user-facing workflow. |
| **Reliability** | A POC has no retry logic, no fallback, and no circuit breaker. When it fails, the developer refreshes and tries again. There are no users waiting. | Without retry logic or fallback handling, any transient API failure takes the entire user-facing workflow down rather than degrading gracefully. |
| **Failure modes** | A demo is tested on inputs the developer expects. Production raises inputs the developer did not expect. Failure modes are specific to architecture type. | Silent degradation, made-up outputs on edge-case inputs, or complete failure on an input class that was never tested. |

#### Cost and latency modeling: Know the numbers before you build

The cost and latency model is built before you finalize the architecture. The three inputs you need are call volume (requests per day or per month), token budget per request (input tokens plus expected output tokens), and model tier. From those three, you can estimate monthly cost and check it against your budget ceiling before any code is written.

The token budget per request is where most cost models go wrong. Teams calculate the average token count on the inputs they have and assume that is the distribution. In practice, token distributions are often skewed: most requests are short, but a tail of long requests consumes a disproportionate share of the total cost. A cost model based on average usage can significantly underestimate the cost impact of these longer requests, often by a factor of two or three.

Latency follows a similar pattern. Median latency reflects the middle of the pack, but SLA breaches are usually caused by slower requests at the high end. That is why p95 is a more useful design target than the median. P95 is the latency value below which 95% of requests complete. Only the slowest 5% fall above it.

**Caching** is the most effective cost and latency lever when the system prompt is long and stable. Prompt caching preserves the processed prompt prefix for the cached tokens, so the API does not reprocess them on subsequent requests. Savings scale with both the length of the cached prefix and how often it's reused. If, for example, cache reads are charged at 10% of the standard input token rate, a long prefix reused across many requests produces the largest effective savings. Find the most current cache read rate at *platform.claude.com/docs/en/about-claude/pricing*. The risk is consistency: if the cached content needs to reflect live state, caching creates a consistency window that may violate the requirements of the use case. What is stored is the prompt prefix.

#### Reliability controls: what to build into every model call

The reliability controls that belong in the production Claude system address different failure scenarios and sit at different layers of the call stack.

- **Transient error recovery with exponential backoff.** When a model returns a transient error, such as a rate limit 429, timeout, or 5xx, the system should retry with progressively longer delays between attempts. This prevents a flood of retries from turning a brief hiccup into a prolonged outage. Set the maximum number of attempts and total wait time based on how much delay your use case can tolerate.
- **Fallback chains.** If the primary model or endpoint is unavailable, the system should automatically route the request to an alternative such as a different model tier or a cached response. It should not raise an error to the user. Fallback behavior should be tested as part of your eval suite.
- **Circuit breakers.** A circuit breaker measures the error rate on a downstream dependency and trips when errors exceed an established threshold. Once tripped, requests fail immediately rather than waiting for a timeout. This prevents one degraded dependency from taking down the broader system.

Reliability controls must sit at the right stage to be effective: new attempts belong close to the API call, circuit breakers at the service boundary, and fallback chains in the orchestration layer. Placing them in the wrong layer means protecting the wrong part of the system and leaving the right part exposed.

#### Failure modes by architecture type

Agents handle tasks that cannot be completed in a single model call: they can use tools, observe results, adjust plans mid-execution, and complete multi-step processes that require dynamic reasoning at each step. Claude Code is a production example, and it navigates codebases, runs tests, applies fixes, and iterates across a workflow that is impossible in a single-turn architecture. The controls below govern how to build these systems reliably.

| Architecture | What breaks first | Mitigation |
| --- | --- | --- |
| **Agent** | Unbounded tool use and growing context. An agent that can call tools without budget constraints or turn limits will run up cost and latency in ways that are invisible until a single request exceeds the budget ceiling. | Set per-turn token budgets, maximum tool call counts, and explicit stopping criteria. Constrain the tool set to the minimum required. Eval the agent's stopping behavior, not just its output quality. |
| **RAG** (retrieval-augmented generation) | Retrieval quality drift. The retrieval layer degrades when documents are added or removed from the index without reindexing, when the query and the document representation fall out of alignment, or when the index is refreshed on a schedule that creates staleness for live-state queries. | Keep retrieval quality in the eval loop. Monitor retrieval precision and recall as system metrics, not just output quality. Separate live-state queries from static knowledge queries. |
| **Document processing pipeline** (Evaluator-optimizer) | No exception path for low-confidence extractions. A pipeline that routes all documents through the same flow regardless of extraction confidence will produce wrong outputs on edge cases at the same rate it produces correct outputs on clean documents. | Add confidence scoring to the extraction step. Route low-confidence extractions to a human review queue rather than downstream processing. Include edge-cases and difficult documents in your eval set. |
| **Orchestrator-workers** | Failure boundaries between orchestrators and subagents blur, traces fragment, and a dropped subagent can fail silently at synthesis. | Define recoverable (subagent: retry or flag) versus unrecoverable (orchestrator) boundaries. Create a shared trace ID across all agents. Reconcile coverage at synthesis so results equal the units submitted. |

> **Cost · Complexity · Risk**
> 
> **Cost:** Don't assume your proof-of-concept costs will match production. Model costs before committing to an architecture, rather than after the first billing cycle.
>  **Complexity:** Retries, fallback chains, and circuit breakers are much harder to add to a system that wasn't designed for them. Build reliability in from the start rather than scrambling to fix it after the first production incident.
>  **Risk:** A system with no fallback and no circuit breaker has one point of failure: the primary model endpoint. When that endpoint goes down at peak load, there is no recovery path, the entire user-facing workflow fails instead of degrading gracefully.

> **Model version pinning**
> 
> Note: Model version pinning applies to every architecture in the table above equally. It is an operational discipline, not an architecture choice. Pin model versions in your configuration, monitor the Anthropic model deprecation page at *platform.claude.com/docs/en/about-claude/model-deprecations*, and maintain a version-update runbook.

---

<!-- S06 -->

*Watch Out · POC to Prod · 5 min*

### The demo cost profile that became the production bill

> **Why this mistake is easy to make**
> 
> A POC is built to prove capability. It is not designed to model cost. The team builds against a small dataset, runs a few hundred requests, and the bill is negligible. A POC bill at low volume is a sample, and it does not reflect production spend.

#### Three quotes from post-launch review

The quotes below are from a single team's post-deployment review, 60 days after moving a document triage system to production. Each quote identifies a different aspect of the same mistake.

> **Quote 1**
> 
> "A POC running 10–50 requests per day can still inform a production cost estimate, but only if the numbers are scaled to expected production volume with appropriate error bounds. Presenting raw demo costs to a client without that extrapolation is where risk lives."

> **Quote 2**
> 
> "We assumed the token distribution would be uniform. It wasn't. The long documents in the tail were consuming 80% of the total token spend."

> **Quote 3**
> 
> "When the endpoint returned a 529 error at peak on day three, the whole workflow went down. We had no fallback because we'd never tested what happened when the call failed."

#### What broke and why

Each quote names a distinct failure, but they compound in order. The cost model was wrong because it was built at the incorrect volume. The token distribution assumption was wrong because it was built on the incorrect inputs. The reliability failure was invisible in development because failure cases were never tested.

All three failures share the same root cause: the POC was treated as a cost and reliability model, not just a capability demonstration. A POC answers the question "can the system do this", but it does not answer "what does it cost to do this at scale" or "what happens when a dependency fails."

> **What to Watch Out for**
> 
> The POC was treated as a production model in three dimensions simultaneously: cost, input distribution, and reliability. All three are production-system properties that must be designed in separately, and a POC establishes none of them.

---

<!-- S07 -->

*Checkpoint · POC to Prod · 5 min*

### Cost & reliability calculator

Use the calculator to explore configurations. Adjust the model tier, prompt caching, max_tokens cap, and call-volume multiplier; the readouts show monthly cost and p95 latency for each setting. Your goal: find a configuration that meets both the cost ceiling and the latency target at the same time. The calculator only displays values; it does not score your exploration. (Figures are representative for modeling; confirm current rates at publish time.)

### Scenario

A customer service agent processes **50,000 requests per month**. The system prompt is **5,000 tokens** and stable across requests. Average user input is **300 tokens**, average output is **400 tokens**. The **cost ceiling is $800/month**. The **p95 latency target is 3 seconds**.

### Decision: Once you have a configuration that meets both targets, which lever did the most work to get there?

- **A.** Switching to Opus, because the most capable model is always safest.
- ✅ **B.** Turning prompt caching on, because the 5,000-token system prompt is stable across all 50,000 requests, so caching it cuts the dominant input-cost driver.
- **C.** Raising the max_tokens cap, because more headroom improves quality.

**Answer: B**

> **A.** Incorrect: Opus is the most expensive tier and would push cost over the ceiling at this volume.
> **B.** Correct.
> **C.** Incorrect: a higher cap raises cost and latency; it does not help meet either target.

---

<!-- S08 -->

*Teaching · Sizing · 18 min*

### Use-case sizing and feasibility

The production readiness checklist tells you what a system must achieve to be viable. It covers both the quality of the model's outputs and the reliability of the system around it. Output quality is validated through evals, and system reliability is validated through architecture controls like retries, fallbacks, and circuit breakers. Meeting both bars is what production readiness means.

Sizing tells you whether a specific business problem can meet that bar, and what constraints govern the design. Feasibility fits into one of three states: feasible as scoped, feasible with constraints, and not feasible. Identifying the state correctly is what makes a scoping document useful.

#### How to size a use case

Sizing a use case means producing a cost model before any code is written. The model does not have to be precise, but it must be accurate enough to validate the architecture against the budget and surface token distribution assumptions before they are formalized.

Four inputs drive the model: call volume, token budget per request, model tier, and sensitivity parameters.

- **Step 1: Estimate call volume.** How many requests are made per day or per month? This number comes from the business requirement, not from the developer's intuition. A customer service agent that handles 1,000 conversations per day produces 1,000 Claude calls per day, plus any multi-turn continuation calls. Get this number from the business owner. A sample dataset will not give you an accurate figure.
- **Step 2: Set the token budget per request.** The token budget has two components: input tokens (system prompt, retrieved context, and user message) and output tokens (expected response length). Model the distribution rather than just the average. If document lengths vary widely, the cost model should account for the typical cases as well as the extremes. If the system prompt is long and stable, prompt caching can meaningfully reduce input costs. Caching requires explicit cache_control markers in the request. Cache writes incur a higher per-token cost than standard input, so the cost model must account for the write cost on first use. The default cache TTL is 5 minutes; workloads with request frequency lower than TTL will not realize consistent caching savings.
- **Step 3: Project the monthly cost.** Multiply call volume by the input token count at the input token rate. Separately, multiply the output token count at the output token rate. Then, add both figures. Input and output tokens are priced at different rates on all model tiers. If prompt caching applies, use the cache read rate for cached input tokens, not the standard input rate. Verify current rates at *platform.claude.com/docs/en/about-claude/pricing* before finalizing the model. Add caching savings if applicable. Compare the result to the cost ceiling from the production readiness checklist. If the projection exceeds the ceiling, the architecture needs to change before a line of code is written. If, for example, Batch API provides a 50% price reduction relative to standard API pricing and supports up to 100,000 requests per batch, model it as a cost alternative for any workload where the SLA permits asynchronous processing. For regulated workloads, verify whether batch processing is covered under the partner's BAA and compliance configuration before routing PHI or similarly governed data through it. Find the most current Batch API discount rate and batch size limit at *platform.claude.com/docs/en/about-claude/pricing*.
- **Step 4: Run sensitivity analysis.** What happens to cost if call volume doubles? What if the token distribution shifts toward the tail? Sensitivity analysis tells you how fragile the cost model is and where the assumptions need to be verified with the business owner before committing to the design.

#### How to scope a use case

The discovery sequence for turning a business requirement into a scoped architecture runs in four steps. Skipping any step produces a commitment that will not survive the next conversation with the business owner.

- **Step 1: Business requirement to capability list.** What does the system need to do? Name each capability separately. "Process insurance claims" is a goal. The capabilities might include extracting structured fields from the claim document, looking up policy coverage from the policy database, routing the claim to the appropriate adjuster queue based on claim type and value, and drafting the adjuster notification. Identify them separately so you can assign each to the appropriate owner.
- **Step 2: Capability list to architecture sketch.** For each capability, decide where it belongs. Which capabilities does Claude own? Which belong to existing systems? Which require a human in the loop? This is the decomposition step from Module 1, applied to a specific use case.
- **Step 3: Architecture sketch to boundary conditions.** State the conditions under which the architecture works and the conditions under which it does not. Feasibility is a verdict plus the constraints that make the verdict true. An architecture that works for documents up to 20 pages but fails for longer documents has a boundary condition that must be documented.
- **Step 4: Boundary conditions to scope in the SOW.** The statement of work contains the boundary conditions. This ensures that the development team and the business owner both understand what the system is designed to handle and what it is explicitly out of scope.

#### How to conduct a technical feasibility assessment

A feasibility assessment that only asks "can Claude do this" is a capability check. The four AI properties give you a structured way to identify where the design will require compensating controls, and what those controls should be.

Select each property to see the feasibility question it raises and where the design compensates.

#### Tab: Next-token prediction

**The feasibility question to ask:** Does this task require probabilistic generation, or does it require precision on specific values? Classification, summarization, and drafting are probabilistic tasks where the model excels. Extraction of specific authoritative values (account numbers, policy dates, claim amounts) requires verification against the source of truth.

**Where design compensates:** Generator-verifier loops; code-based evals on extracted values; tool calls to retrieve quantitative data.

#### Tab: Knowledge

**The feasibility question to ask:** Does this task depend on information that is rare, contested, recent, or domain-specific in ways that may not be represented in training data? If yes, the design must bring the knowledge into the context window. Do not rely on the model to supply it.

**Where design compensates:** Retrieval-augmented generation for stable knowledge; tool calls for live-state data; flagging uncertainty on contested claims.

#### Tab: Working memory

**The feasibility question to ask:** Do the inputs fit comfortably in the context window, or does the task require processing inputs that, in aggregate, exceed the window? Long documents, multi-document tasks, and extended conversations all hit this constraint.

**Where design compensates:** Chunking strategies; progressive context loading; summarization across turns; pipeline architecture for inputs exceeding the context limit.

#### Tab: Steerability

**The feasibility question to ask:** Are the instructions specific, concrete, and verifiable? Abstract or ambiguous instructions, long reasoning chains, and tasks that require precise numerical or logical computation are all places where the model can drift from intent.

**Where design compensates:** System prompts with explicit output schemas; structured outputs; code execution for numerical precision; evaluator-optimizer loops.

#### Feasibility verdicts

Once the scoping sequence and technical assessment are complete, the architecture is ready for a feasibility assessment. There are three possible outcomes.

| Verdict | What it means | What to document |
| --- | --- | --- |
| **Feasible as scoped** | The arguments across the four AI properties favor Claude for each capability. The cost model is within the ceiling. The latency p95 is within the SLA. No capability requires a compensating control that changes the architecture. | State the assumptions clearly. Feasible-as-scoped verdicts become infeasible-with-constraints when assumptions change. |
| **Feasible with constraints** | The design works under specific conditions that must be enforced. The document length must stay under a threshold. The retrieval index must be refreshed on a defined schedule. A human review gate must exist for outputs above a confidence threshold. The constraints are part of the architecture. | Document each constraint explicitly. For each violated constraint, identify the failure mode. The development team needs to know what they are designing for, not just what they are building. |
| **Not feasible** | At least one capability faces an AI property limitation that cannot be compensated for within the scope and budget. The cost model exceeds the ceiling by a margin that cannot be closed by model tier, caching, or architecture changes. A not-feasible verdict is a correct assessment that saves the engagement from a more expensive failure later. | State which constraint is disqualifying and why. Where a scope reduction would change the verdict, name it and present the business owner with a choice. |

#### Business value and ROI mapping: turning a feasible design into a justified investment

A feasibility verdict tells the business owner that the system can be built within the budget and the constraints. It does not tell them whether building it is worth doing. Determining business value and ROI mapping are the steps that answer that second question. They connect the scoped architecture to the financial and operational outcomes the business expects, expressed in terms the business owner already uses: hours saved, error rates reduced, cycle time shortened, or revenue protected. The mapping turns a technical design into a decision a budget holder can defend.

The business case rests on five main pillars, and identifying them keeps the ROI conversation in the language the blueprint and the business owner both use: efficiency (the same work done faster or cheaper), transformation (work that was not feasible before becoming possible), productivity (more output from the same people), solution cost (the run cost of the system itself), and performance SLAs (the service levels the deployment must hold). Map each ROI claim to the pillar it advances so the value statement captures both the number and the kind of value it represents.

The mechanism is a comparison between two states. The baseline state is how the work is done today, measured in the unit the business cares about. The projected state is how the work is done once Claude is in the workflow, measured in the same unit. The value is the difference between the two states, minus the cost of running the system. The cost figure comes directly from the sizing model produced earlier in this cluster, so the ROI calculation reuses work you have already done rather than starting over.

The mapping is built in four steps, and each step must be grounded in a number the business owner will recognize:

- **Step 1: Name the baseline in a business unit.** Start from how the task is performed today and measure it in the unit the business already tracks. For a claims review workflow that is the analyst hours per claim or the average days to resolution. The baseline must come from the business owner's own operational data, because every later number is compared against it. A baseline pulled from intuition produces an ROI figure no finance team will accept.
- **Step 2: Predict the post-deployment state in the same unit.** Estimate how the same task performs once Claude is in the workflow, measured in the identical unit as the baseline. Where the feasibility verdict requires human review, the projection must include that cost. Routing low-confidence output to a reviewer reduces labor, but it does not eliminate it entirely. When the design specifies human-in-the-loop review, projecting full automation overstates the value and produces a number operations will reject.
- **Step 3: Subtract the run cost from the sizing model.** Take the projected monthly cost produced during sizing and treat it as the recurring cost of the new state. The value of the deployment is the operational gain from Step 2 minus this run cost. This step isolates recurring run cost only. Build cost is treated separately and is accounted for in the payback period calculation in Step 4. Including the sizing output in the ROI calculation keeps the two analyses consistent. A change to the token budget or model tier then updates both the cost ceiling and the value case together.
- **Step 4: State the payback period and the sensitivity.** Express the result as a payback period, which is the time it takes for the accumulated operational gain to cover the build cost and the run cost. Then state how that period moves if the volume assumptions or the gain-per-task assumptions are wrong. Quoting a payback period without sensitivity analysis invites decisions based on a single optimistic scenario, one that often fails when the business case meets real volumes after launch.

The output of the mapping is a short value statement the Architect hands to the business owner alongside the feasibility verdict. It ties the answers to "Can we build this?" and "Is it worth building?" back to numbers the business already owns. The two artifacts travel together into the statement of work.

These are the most common ROI map errors, what causes them, and where they tend to appear.

| Risk | Why it happens and where it shows up |
| --- | --- |
| **The baseline is estimated rather than measured.** | When the business owner does not have clean operational data, the baseline gets filled in from intuition. This makes the apparent gain misleading. The error stays hidden until the finance team asks for the source of the baseline number during business case review. At this point the whole case must be rebuilt. |
| **The projection assumes full automation when the design requires human review.** | A feasibility verdict that requires a human review gate means the labor is reduced, not fully eliminated. The value case often misleadingly models it as eliminated. The gap surfaces in the first operational period after launch, when actual analyst hours fail to fall as far as the business case promised. |
| **The run cost is taken from an average rather than the sizing distribution.** | Reusing an average token cost instead of the distribution from the sizing model understates the recurring cost, which overstates net value. This concentrates on workflows with heavy-tailed inputs, where a small fraction of large requests drives most of the cost. |

> **Cost · Complexity · Risk**
> 
> **Cost:** Sizing based on average token counts will underestimate cost when some requests are much larger than others. Getting this wrong means renegotiating the architecture after the contract is already signed.
>  **Complexity:** A feasibility assessment that skips any of the four AI properties risks missing a constraint that changes the design. Working memory is the most overlooked, since it rarely shows up during development on small, clean inputs, but it will surface in production.
>  **Risk:** A feasible-with-constraints verdict that is not documented becomes an infeasible system when the constraints are violated in production. The constraints are part of the design and carry the same weight as the architecture they qualify.

---

<!-- S09 -->

*Watch Out · Sizing · 5 min*

### The scoping call that skipped the constraints

> **The demo trap**
> 
> When a business owner is excited about a use case and the initial demo works, confirming feasibility before gathering the volume and SLA constraints feels like the efficient path. The capability is there, the prototype is working, and slowing down to ask about constraints can feel like looking for reasons to say no. The problem is that "technically feasible" is meaningless if the constraints aren't applied to the expected scale.

#### A scoping conversation: Commitment made too early

The following is an extract of a pattern that surfaces in discovery calls when the capability question is answered before the constraint questions are asked.

**Partner:** *"We need a document review assistant that can process our legal contracts and flag non-standard clauses."*

**Architect:** *"We can do that. The model is good at reading contracts and identifying clause patterns. Let me put together a feasibility write-up."*

**Partner:** *"Great, how long will the build take?"*

**Architect:** *"Six weeks for the initial version."*

[Two weeks into the build]

**Partner:** *"I should mention: we process about 800 contracts a day. Some of them are framework agreements that run to 300 pages. And we need results in under 30 seconds."*

#### What went wrong

The feasibility verdict was issued before three essential constraints were gathered: call volume (800 per day), input size (up to 300 pages), and latency requirement (30 seconds).

Whether a lengthy contract fits within the context window depends on the model tier selected. Models with a 1 million token context window can handle a 300-page contract without chunking; a model with a 200k token window may require a chunking strategy for the longest documents. Context window capacity is therefore part of the model tier decision, not a settled assumption.

At 800 requests per day, the 30-second latency requirement is not as limiting as it seems. This averages out to one request every 108 seconds. Sequential processing is viable at that volume without running requests in parallel. At that request rate, volume pressures cost, not latency. Latency is driven by task complexity, model size, and output length. Those are the variables the model tier decision needs to be built around.

The architect confirmed capability as a necessary first step, but it was also the last step, which meant the commitment was made before the design was possible.

> **What to Watch Out for**
> 
> The capability question was answered before the questions were even asked. The volume, latency, and input-size constraints are inputs to the feasibility verdict. The verdict is only as sound as the constraints gathered before it.

---

<!-- S10 -->

*Checkpoint · Sizing · 5 min*

### Justify the feasibility call

For each scenario, choose the option that names both the correct feasibility verdict and the single load-bearing constraint behind it. The verdict alone is not enough, the constraint is what makes the verdict defensible.

**SCENARIO 1 OF 3 — A professional-services firm wants a research assistant that summarizes 10–40 page industry reports and drafts client briefings. 50 reports per week, briefings within 24 hours, $500/month ceiling.**

- **A.** Not feasible, the reports are too long for the context window.
- ✅ **B.** Feasible as scoped, input size fits the context window, and volume, latency, and cost are all within range at the Sonnet tier; no AI property presents a disqualifying constraint.
- **C.** Feasible with constraints, needs a human review gate on every briefing.

**Answer: B**

> **B.** verdict: Correct. · msg: All four AI properties are evaluated. The input size (10–40 pages) fits well within Sonnet's context window. Volume (50/week) is low and easily handled. The 24-hour latency target is generous. The $500/month ceiling is feasible at the Sonnet tier for this volume. No AI property presents a disqualifying constraint.
> **A.** verdict: Not quite. · msg: 10–40 page reports fit within Sonnet's context window without chunking. Input size is not the binding constraint here.
> **C.** verdict: Not quite. · msg: A human review gate is a design choice, not a feasibility constraint. The question asks for the constraint that governs the verdict, not a recommended safeguard.

**SCENARIO 2 OF 3 — A logistics company wants a delay predictor that reads unstructured carrier emails, extracts delay reasons and new ETAs, and writes them to the order-management system. 5,000 emails/day, under 10 seconds, $1,000/month.**

- **A.** Feasible as scoped, Haiku with caching handles the volume and latency.
- **B.** Not feasible, the volume is too high.
- ✅ **C.** Feasible with constraints, the load-bearing constraint is extraction accuracy on a transactional write, so it requires a code-based eval on extraction accuracy plus a human review gate on low-confidence extractions before writing to the system of record.

**Answer: C**

> **C.** verdict: Correct. · msg: The load-bearing constraint is extraction accuracy on a transactional write. Getting the ETA wrong and writing it to the order-management system has real downstream consequences. A code-based eval on extraction accuracy is appropriate because the output is structured (dates and reasons) and scoreable against the carrier email. Low-confidence extractions need a human gate before the write.
> **A.** verdict: Partially right. · msg: Haiku with caching can handle the volume. But the answer misses the load-bearing constraint: extraction accuracy on a transactional write. Feasibility here is governed by what happens when the extraction is wrong, not by whether the volume can be processed.
> **B.** verdict: Not quite. · msg: 5,000 emails/day with a 10-second window is very achievable. Volume is not the binding constraint.

**SCENARIO 3 OF 3 — A financial-services firm wants real-time trading recommendations from current market conditions plus its proprietary model, delivered in under 2 seconds.**

- ✅ **A.** Not feasible as described, the load-bearing constraint is the live-state knowledge gap: real-time market data requires a tool call to a live feed, and whether that round trip fits inside the 2-second budget must be validated before any feasibility verdict can be issued.
- **B.** Feasible as scoped, Claude already knows current market conditions.
- **C.** Feasible with constraints, just add a human gate.

**Answer: A**

> **A.** verdict: Correct. · msg: Claude's training data has a knowledge cutoff, real-time market data is not available in the model's base knowledge. The system needs a tool call to a live data feed. Whether that round trip, tool call, data retrieval, model response, fits inside a 2-second budget must be tested before any feasibility verdict can be issued. Issuing a feasibility verdict before this is confirmed is the same mistake as the scoping call that skipped the constraints.
> **B.** verdict: Incorrect. · msg: Claude does not have access to real-time market data. Its training has a knowledge cutoff date, and current market prices, positions, and conditions are outside that boundary.
> **C.** verdict: Not quite. · msg: A human gate is a mitigation for risk in autonomous recommendations. It does not address the foundational constraint: whether real-time market data is accessible within the latency budget.

---

<!-- S11 -->

*Teaching · Integration · 14 min*

### Enterprise integration patterns: identity, auth, data, and observability

Compliance constraints eliminate entry point options before any other decision is made, so entry point selection comes first. The remaining five layers govern how the integration is built from there.

Sizing tells you what the system needs to do and whether it can do it within the constraints. Integration patterns tell you how it connects to the enterprise stack. That connection has five layers, and each layer has an architectural decision that belongs to the Architect, as opposed to the implementation team.

#### Entry point selection: which integration to use and when

The first decision in any integration is which entry point the system will connect through. Compliance constraints eliminate options at this first stage, before any other architectural decisions are made. The table covers the five available entry points, when each one applies, and what each one costs in flexibility or maintenance.

**▸ Entry points: which integration to use and when**

| Entry Point | Use it when | What you trade off |
| --- | --- | --- |
| **Direct API** | You need full control over how requests are built, how responses are handled, and how errors are managed. Every part of the system is your own code. | You are responsible for building and maintaining retry logic, streaming, tool orchestration, and error handling. The implementation effort is higher than the SDK path. |
| **SDK** (Python/TypeScript) | You want a convenience layer that handles the basics without giving up control over how the system is designed. The SDK handles the HTTP layer and gives you typed interfaces while leaving orchestration to your code. | Less granular control than the raw API. SDK version upgrades can occasionally change behavior in ways that require code review before deploying. |
| **Claude Code** | The primary user is a developer, and the task involves writing, reviewing, or navigating code. Not appropriate as the backend for an embedded product. | Not designed for products with multiple users or customer-facing deployments. Claude Code is designed for developer workflows, not as a backend for multi-tenant products; product integrations should use the Claude API, client SDK, or Agent SDK. |
| **Agent SDK** | You need Claude to act across multiple turns inside your own product, with your application controlling the surrounding workflow. The Agent SDK runs a managed loop, handling iteration, tool execution, and termination, so your team does not have to build that infrastructure. Available in Python and TypeScript. Not the right choice when a single request and response is sufficient, or when the task does not require multi-turn reasoning over tools. | The managed loop gives up fine-grained control over each iteration step. If your use case requires custom logic between turns, a raw API loop gives you that control at the cost of building and maintaining the loop yourself. |
| **MCP** (Model Context Protocol) | You are connecting Claude to existing tools or internal services and want a standard way to manage those connections without mixing them into your orchestration logic. MCP provides a protocol for tool integration that keeps the integration layer separate from the orchestration layer. | MCP adds a protocol layer between Claude and your tools, which makes debugging tool calls more complex than direct function calls. |

#### Security and compliance constraints at the integration layer

Module 1 established that regulatory and policy constraints, laws like HIPAA, GDPR, and FedRAMP, attorney-client privilege, and data-residency requirements eliminate entry point options before any other decisions are made. This section applies the same logic one level deeper: which integration pattern on that entry point may, with appropriate architectural choices, internal policies, contractual terms, and other items, help satisfy or otherwise mitigate concerns about the constraint.

The table below extends that analysis from entry point selection to full integration design.

*Note: This should not be seen as legal guidance - work with your own legal and compliance team to implement controls that meet your organization's needs.*

**▸ Constraint-to-integration matrix**

| Constraint | Where it runs (Route) | How it connects (Integration pattern) | Who it trusts (Identity) | What it handles (Data handling) | What it logs (Observability) |
| --- | --- | --- | --- | --- | --- |
| **Attorney-client privilege*** | The API runs behind the firm's own application, through a firm-approved gateway that logs every request. | The gateway sits between the user and Claude. It holds the API key, enforces who can access what, and produces an audit log the firm owns. | Users log in through SSO. User identity and permissions are assigned by the server and cannot be claimed by the user. | All privileged content flows through the gateway, which serves as the official record. | Every request and response is logged at the gateway and retained according to firm policy. |
| **HIPAA (PHI handling)** | The API runs on a configuration covered by a Business Associate Agreement (BAA). HIPAA-eligible cloud paths include the Claude API directly (with a signed BAA from Anthropic), AWS Bedrock, and Google Vertex AI. The BAA must cover the specific configuration in use, not just the provider in general. | The cloud provider mediates the integration. The BAA must cover the specific configuration in use, not just the provider in general. | Users are verified through the partner's authentication system. Access to PHI is limited to the minimum necessary under HIPAA. | PHI is stripped down to only what the task requires before the API call is made. Where possible, reference IDs are used instead of full data fields. | Logs capture the request, model version, user identity, and data scope, and are retained per HIPAA requirements. |
| **GDPR and data residency** | The model execution is confined to an approved region. This can be achieved through a cloud route (AWS Bedrock or Google Vertex AI) or through the Claude API directly using the `inference_geo` parameter, which currently supports "us" and "global" as values. Note that `inference_geo` does not support EU pinning directly – while GDPR compliance does not require EU residency, as cross-border transfers are lawful with a valid transfer mechanism, where a deployment has an EU data residency requirement, a cloud route rather than the direct API should be used. Where the Claude API is used, the DPA is with Anthropic directly. Where a cloud route is used, DPA terms are inherited from the cloud contract. Note: Microsoft Foundry EU data residency is listed as Coming 2026 with no confirmed timeline at publish. If the deployment references Foundry and requires EU data pinning, verify current availability before committing to that route. | The execution region is locked at the integration layer and checked on every request. Data does not leave the approved region. | Users are verified within the approved data region and handled per GDPR requirements. | Personal data is only processed within the pinned region. Moving data across borders requires a documented legal basis and is only built in when explicitly justified. | Logs record who accessed what data, the legal basis for processing it, and when it will be deleted. |
| **FedRAMP and government** | The integration runs on a cloud configuration that holds the required FedRAMP authorization at the correct impact level. FedRAMP-eligible paths are Claude for Government, AWS Bedrock GovCloud, and Google Vertex Assured Workloads. Claude Enterprise on the direct API is not FedRAMP authorized and cannot be used as a substitute for these paths. | The architecture is limited to the specific cloud and configuration that carries the authorization. Nothing outside that boundary is allowed. | Users authenticate through the agency's approved identity provider. Access is controlled by the agency's role and policy layer. | Data is handled according to the agency's classification rules. Controlled unclassified information stays within the authorized boundary. | Logs meet the agency's continuous monitoring requirements. |
| **Internal data-residency policy** | The integration runs on the cloud provider the partner's organization has already approved. The right route is the one the CIO has cleared, regardless of convenience. | The architecture is constrained by what procurement has approved, regardless of engineering preference. | Users log in through the partner's standard SSO. Roles are assigned according to the partner's existing policy. | Data handling per the partner's existing classification scheme. The Claude layer inherits existing controls and does not introduce new ones. | Logs feed into the partner's existing logging infrastructure rather than a separate system. |

* Privilege preservation depends on appropriate contractual terms, retention settings, internal policies, and other items. The information in this chart is intended to help mitigate privilege waiver concerns.

Before any integration design begins, work through the constraints in order: identify the governing regulation or policy, determine which entry point and route are still available, choose the integration pattern that fits, and document the identity, data handling, and observability requirements that follow. Skipping any step risks building something that works technically but fails a legal or security review.

#### 

Every enterprise Claude integration requires decisions at the layers defined in the table below. Compliance comes first, constraints from regulations like HIPAA, GDPR, and FedRAMP, and policies like data residency and attorney-client privilege, eliminate routes and entry points before any other decisions are made. The remaining four layers operate within whatever options survive that filter. Note these sections don't address ZDR use cases.

| Layer | The architectural decision | What breaks when it's wrong |
| --- | --- | --- |
| **Compliance and regulated-industry constraints** | *Which delivery routes and entry points survive the governing constraint?* BAA coverage, FedRAMP authorization, data-residency pinning, and approved-vendor lists each eliminate options before the rest of the design begins. | The integration is built on a route that fails the next legal or security review. The cost of redesign at that point is the time already invested plus a new architecture from scratch. |
| **Identity and SSO** | *Where does the user identity boundary sit relative to the Claude integration point? Who is the user in the context of a Claude call, and how does that identity get passed into the prompt safely?* | When user identity is not passed into the prompt correctly, Claude cannot scope its responses to what that user is authorized to see. Identity passed as a raw field in the user message is manipulable. Server-side injection removes that risk. |
| **Authorization and policy** | *Which capabilities does this user or role have? What data can they access?* The authorization model that governs your existing systems needs to govern the Claude layer as well. | A Claude integration that bypasses the authorization model of the underlying system gives users access to data they are not authorized to see, through a path that was not designed to enforce the access policy. |
| **Data handling and PII** | *What data goes into the context window?* Sensitive fields passed directly in the user message or system prompt become part of the API request. Anthropic does not retain conversation content by default; only what is technically necessary for the API and feature to work is retained. The request still crosses the wire, specific retention carve-outs exist for some model classes, and any logging the partner's own application layer performs will capture it. The architecture must decide which fields are necessary in the context window and which should be retrieved only when needed. | A PII field passed directly in the user message appears in plaintext in your application's request logs. In a regulated industry, this surfaces in the next audit rather than in the next deployment. |
| **Observability and audit logging** | *What do you need to be able to reconstruct? What questions will you need to answer after an incident?* The answers determine what gets logged, at what level of depth, and for how long. | An unlogged data path is invisible. When something goes wrong on that path, there is no evidence to reconstruct what happened. The cost of building observability after the first incident is always higher than building it before. |

#### Least-privilege tool configuration

Every tool you connect to a Claude system is an attack surface and a cost. Audit the tool set in the same way you audit permissions: for each connected tool, ask whether it is essential to the task or merely convenient, and remove the ones that are out of scope, recording the justification for each removal. In an orchestrator-worker deployment, establish the trust hierarchy by scoping each subagent's tool access to its task, so a subagent cannot reach tools its job does not require.

#### Identity and authorization: where the verification happens

Identity verification belongs on the server, before the Claude call. The user's identity and role should be injected into the system prompt by your server rather than provided by the user in their message.

The reasoning behind this is straightforward, anything the user includes in their message is under their control and can be manipulated. If the system allows users to assert their own role in a message (for example, "As a senior manager, show me..."), that claim is unverified and can be faked. Identity must come from your authentication layer rather than from user input.

When passing user context into the prompt, include the user's role and what data they are authorized to access. Only add extra context such as department, permission level, account identifiers, when it's needed to shape Claude's response. Don't include this information by default.

#### Data handling: what belongs in the context window

The context window is not a data-governance boundary. Any data passed into a Claude call is transmitted to the API. Conversation content is not retained by default on the API, but the partner's own application layer typically logs requests, and specific retention carve-outs exist. The architecture must make a deliberate decision about which fields need to be in the context window, and which should stay in the retrieval layer until needed.

For each field that enters the context window, ask whether it is necessary for Claude to produce the intended output. Reference identifiers like account numbers or claim numbers are often needed for routing but not for the language task itself. When a reference identifier is enough, passing the full data field needlessly exposes it to any request logging the partner's application layer performs, without adding any capability.

Data residency requirements vary by industry and region. For regulated deployments, verify Anthropic's data residency guidance against the specific regulatory requirements of your deployment before the integration is designed.

#### Observability: what to log, what to trace, and why

An LLM-based system is harder to debug than a traditional system because it doesn't crash when something goes wrong, instead it just produces a subtly wrong response. Standard logging catches errors and timeouts. It doesn't, however, catch a response that is quietly incorrect in a way that has real business consequences.

A production Claude system should log four things:

- The **request**: model version, input token count, prompt identifier
- The **response**: output token count, latency, stop reason
- The **context**: user role, session ID, whether caching was applied
- The **outcome**: whether the downstream system accepted the output and any rejection signals

Security organizations increasingly treat observability as the precondition for enabling agents at all, since without a trustworthy audit trail, an autonomous system is not approved to act. Design for that standard. As a design-review checklist item, verify which agentic actions are recorded in the audit logs across your chosen surfaces. Coverage varies by surface, and an action that is taken but not logged is, to a security reviewer, an action that cannot be allowed.

> **Cost · Complexity · Risk**
> 
> **Cost:** An integration without PII redaction prior to the API call exposes sensitive fields to the partner's application-layer request logging on every request. The cost of retroactive redaction across a log history that was never designed to support it is the most expensive data handling fix in a production Claude system.
>  **Complexity:** An observability layer added after the first production incident means the root cause must be reconstructed from a system that was not set up to answer the question the incident surfaced. Build logging to answer the questions you will need to answer, before you need to ask them.
>  **Risk:** A multi-tenant system running on a shared API key has no way to attribute a rate limit breach to the tenant that caused it. When the org-level limit trips at peak load, the spike is visible but the source is not, and every tenant absorbs the impact. Separate API keys per tenant are required for attribution and isolation in any production multi-tenant deployment.

---

<!-- S12 -->

*Watch Out · Integration · 5 min*

### The PII field that went straight into the prompt

> **The demo trap for skipping security**
> 
> When the goal is to get a demo working quickly, the fastest path to a working Claude integration is to pass the data you have directly into the prompt. Adding a PII redaction layer, building a server-side identity injection, and instrumenting the observability stack all add time. They also add no visible capability, as the system works without them. The cost of skipping them does not appear until the first audit.

#### A trace excerpt from a regulated-industry deployment

The trace below is a composite of a field pattern in a healthcare-adjacent deployment. The team built a patient intake summarization tool. The summarization worked correctly. The data handling did not.

API request: captured in the application layer's request logs

Model: claude-sonnet-4-6
 System: "You are a clinical intake summarizer. Extract key presenting concerns, medications, and allergies from the intake form."
 User: "Patient: Jane Doe, DOB: 1978-04-12, SSN: 123-45-6789, Insurance ID: BCB-88712. Chief complaint: chest pain, onset 3 days ago..."

The SSN and Insurance ID are in the user message and therefore travel with the API request, exposed to any application-layer request logging, despite not being needed to produce the summary. The system prompt asks for presenting concerns, medications, and allergies. None of those require the patient's SSN or Insurance ID to be in the context window.

#### What broke

The tool worked as designed, but the data handling was wrong. Several fields that qualify as Protected Health Information (PHI) under HIPAA, the patient's name, date of birth, SSN, Insurance ID, chief complaint, medications, and allergies, were passed into the API call and captured in plaintext in the application layer's request logs. These were not necessary for the language task. When the deployment was reviewed prior to production certification, the application layer's request logs contained thousands of entries with patient SSNs in the user message field.

The fix was a data architecture change: a server-side redaction step that strips non-essential PII fields before the Claude call, and a retrieval function that supplies only the fields the language task needs. Both should have been in the original design.

> **What to Watch Out for**
> 
> The data handling architecture was designed around what was convenient to pass, not around what was necessary to pass. Necessity is the correct filter: if the field is not required for the language task Claude is performing, it should not be in the context window.

---

<!-- S13 -->

*Checkpoint · Integration · 5 min*

### Critique the integration diagram

The diagram below shows a Claude deployment for a customer-service agent at a multi-tenant SaaS company. Review the labeled components and connections, and select every one that represents an integration problem.

*Select all problems. Leave sound components unselected.*

- [x] ProblemClaude Code used as the backend for the customer-facing chat product
  - *Claude Code is designed for developer workflows, one user, code-centric tasks. It is not designed for multi-user, customer-facing products. Customer-facing chat products should use the Claude API, client SDK, or Agent SDK.*

↓

↓

↓

- [x] ProblemShared API key used for all tenants
  - *One tenant's spike rate-limits everyone and load can't be attributed by tenant. Isolate tenants with Workspaces: API keys are scoped to a single workspace and can only access resources within that workspace, with per-workspace spend and rate limits. Organizations are capped at 100 workspaces, so one-workspace-per-tenant does not scale infinitely; group tenants when counts run high. Workload Identity Federation is an authentication mechanism (short-lived IdP-minted tokens that operate within a workspace), not an isolation mechanism.*

- [x] ProblemCapability check based on "I am a premium customer" in the user message
  - *An unverified claim in the user message is not authorization. Any user can write "I am a premium customer", the server must inject role and capability from the authentication layer, not read it from the user turn.*

- [x] ProblemAccount number and email passed in the user message and appearing in request logs
  - *Account number and email in the user message become part of the API request log in plaintext. These are not required for the language task and should not be in the context window.*

↓

↓

↓

- [ ] SoundServer-side authentication layer in front of the API
  - *A server-side authentication layer in front of the API is the correct pattern. It ensures users cannot reach Claude without being authenticated by the partner's system. Sound component.*

↓

- [ ] SoundTenant data isolated per tenant at the storage layer
  - *Tenant data isolation at the storage layer is the correct baseline for a multi-tenant system. Sound component.*

↓

- [x] ProblemClaude response passed to the downstream CRM with no logging at the integration layer
  - *An unlogged CRM write cannot be attributed, audited, or diagnosed. Every agentic action that writes to a downstream system must be captured in the audit log at the integration layer.*

---

<!-- S14 -->

*Teaching · A/B & Obs · 17 min*

### A/B testing and observability at scale

Integration patterns get Claude into the enterprise stack. The question that follows is whether it is performing the way it should once it is there. Observability answers the monitoring question. Structured A/B testing answers the improvement question. Without both, you are either flying blind or making changes you cannot measure.

#### Structured A/B testing for live Claude systems

An A/B test for a Claude system follows the same structure as any experiment: a hypothesis, a treatment group, a control group, a metric, and a sample size large enough to make the result statistically meaningful. The difference from traditional software A/B testing is that LLM outputs are probabilistic, which makes the results noisier and the interaction effects harder to control.

The hypothesis must be specific and testable. "The new prompt is better" fails on both counts: it names no treatment, no metric, and no threshold. A usable hypothesis reads like this: *"Replacing the instruction to summarize with an instruction to extract the three most important action items will increase task success rate by at least 5% without degrading response latency p95."* It names the treatment, the metric, the threshold for success, and the constraint.

| Component | What it requires | What goes wrong when it is missing |
| --- | --- | --- |
| **Hypothesis** | A specific, falsifiable statement naming the treatment, the expected direction of the primary metric, and any constraints on secondary metrics. | Without a hypothesis, any result can be interpreted as a win. You can always find a metric that moved in the right direction if you look at enough of them after the fact. |
| **Treatment and control assignment** | Random assignment of requests to treatment (new version) or control (current version). Assignment must be consistent for a given user or session to avoid contamination. | Non-random assignment means the groups are not comparable. If the treatment group happens to receive more complex queries, an apparent win may be an artifact of input distribution. |
| **Primary metric** | A single metric defined before the experiment runs. Task success rate, cost per completion, latency p95, or user satisfaction proxy. Choosing the metric after seeing the results is outcome-shopping. | An unspecified primary metric turns an experiment into a retrospective correlation, which is a much weaker basis for a decision. |
| **Sample size** | Calculated from the minimum detectable effect, the baseline metric value, and the required confidence level. For LLM systems, the variance in outputs is higher than for deterministic systems, which means the required sample size is larger. | An underpowered experiment produces results that cannot distinguish a real effect from noise. A team that runs until they see what they want will find what they were looking for, whether it is real or not. |

#### Reading results without overclaiming

Statistical significance means the result is unlikely to have occurred by chance given the sample size. Whether it is large enough to matter is a separate question. A change can be statistically significant but still too small to justify the operational cost of shipping and maintaining the new version.

The two questions to ask before declaring a winner are: is the effect large enough to justify the operational overhead of maintaining the new version? And did any secondary metric degrade? A prompt change that improves task success rate while increasing cost by 30% may not be a net win, depending on the budget constraints of the deployment.

LLM experiments have an additional failure mode that classical A/B tests do not: interaction effects between the treatment and specific input types. A prompt change that improves performance on typical inputs may degrade performance on edge-case inputs that appear rarely in the test period but frequently in a future seasonal spike. Test period and input distribution alignment matters more in LLM experiments than in most other software contexts.

#### Shadow testing: validating a change before any user sees it

A live A/B test sends real users to the new version, which means a regression reaches some fraction of them before the experiment closes. There is a way to test against real traffic without taking that exposure. You run the new version in parallel with the current one, send it a copy of live requests, and serve every user the current version's response. The new version's outputs are logged rather than returned, and you score them offline after the fact. The deployment decision is made before a single user has seen the new version. That pattern is called shadow testing.

The choice between the two patterns comes down to how much risk the deployment can carry and how much traffic it sees.

- Use a **live A/B test** when the deployment can absorb a small, bounded amount of exposure to a worse version and the traffic volume is high enough to reach a statistically meaningful sample in a reasonable window. The payoff is that you measure the new version against real user behavior, including the downstream signals a live response produces, such as whether the user accepted the answer or followed up.
- Use **shadow testing** when a single bad output carries too much risk, or when traffic is too low to support a live split before the change is needed. The cost of shadow testing is the loss of downstream signal: with no users receiving the shadow output, scoring relies on an offline rubric or golden answers rather than real user behavior. For a regulated-industry deployment, where exposing users to an unvalidated model change may not be permissible at all, shadow testing is often the only acceptable way to validate the change.

#### Observability at scale: instrumentation design, dashboards, anomaly detection

Production observability for a Claude system needs to answer four questions: what is the system doing, how well is it performing, when did it change, and why did it change? Each question requires a different layer of instrumentation.

- **Request-level tracing.** Every request should produce a trace that includes the model, model version, input token count, output token count, latency, stop reason, and any tool calls made. This is the raw material for everything else.
- **Metric aggregation.** Aggregate the request-level data into the metrics the dashboard displays: cost per request, latency p50 and p95, task success rate (if the downstream system provides an acceptance signal), and error rate by error type. Per-request decomposition is critical: aggregate metrics can look healthy while a small fraction of requests consume most of the budget.
- **Anomaly detection.** Set threshold alerts on the metrics that matter for the deployment. A cost spike that exceeds 150% of the 7-day average deserves an alert. A latency p95 that crosses the SLA threshold deserves an alert. Model drift (gradual change in the distribution of model outputs over time) is harder to detect with threshold alerts and benefits from periodic distribution comparison.
- **Change attribution.** When a metric moves, the instrumentation should be able to distinguish Model drift (the model's behavior on stable inputs changed), data drift (the input distribution changed), and model update effects (the model version changed and the new version behaves differently on existing inputs). These three causes have different mitigations and mixing them up produces the wrong fix.

#### A failure taxonomy: classifying what you are looking at

Instrumentation tells you a metric moved; diagnosis tells you what kind of failure moved it. Before attributing a change, classify the failure. The common classes are distinct and call for different fixes:

- **Prompt failure.** The instruction was ambiguous or underspecified and the model filled the gap. The fix is in the prompt, not the model.
- **Hallucination.** The model produced confident, fluent content that is not grounded in the input or a reliable source. The fix is grounding through retrieval, tool use, or verification. Stronger instruction will not resolve it.
- **Model mismatch.** The chosen tier is wrong for the task or was swapped without re-evaluation. The fix is model selection, gated by an eval.
- **Orchestrator-workers failure.** In multi-agent systems, trace across the orchestrator and its subagents: a recoverable subagent failure (retry or flag) looks different from an unrecoverable orchestrator failure. Attribution requires a trace that spans both.

#### Discernment: judging the output

Discernment is one of the four AI Fluency competencies, defined as the discipline of judging the quality of what the model produced rather than accepting it at face value. Applied to a production system, Discernment is the habit of classifying each output as acceptable, needs revision, or needs override, and feeding that judgment back into the evals and the monitoring. A team without Discernment watches metrics move and never asks whether the underlying outputs were actually good.

#### Connecting observability data to business value

The people who funded the Claude deployment are not reading the request-level trace. They are reading a KPI dashboard that measures the outcome the deployment was designed to improve. The observability stack needs a translation layer that connects the technical metrics to the business metrics they drive.

For a customer service agent, the business metric might be average handle time, first-contact resolution rate, or customer satisfaction score. The observability stack measures latency, task success rate, and error rate. The translation layer maps task success rate to first-contact resolution and latency to handle time, so the business owner can see whether the system is moving the numbers they care about.

Build this translation layer when the system is designed, not after the first business review. If the technical and business metrics are not mapped at build time, the first business review will raise a question about what is driving the change in handle time. Without that mapping, answering it requires a retrospective reconstruction rather than running a live query.

> **Cost · Complexity · Risk**
> 
> **Cost:** Running an A/B test without pre-specifying the primary metric means you can always find a result you want. Underpowered experiments produce false positives. A change that looks like an improvement gets deployed, and the team ends up maintaining a version no better than what it replaced while absorbing the full operational overhead.
>  **Complexity:** Observability instrumentation added after the first production incident means the root cause question cannot be answered from the existing log data. The incremental complexity of building the instrumentation correctly the first time is lower than the complexity of retroactive log reconstruction.
>  **Risk:** An LLM system with aggregate-only observability metrics can look healthy while a small fraction of requests is consuming most of the budget and producing wrong outputs. Aggregate metrics protect against obvious failures. Per-request decomposition protects against the non-obvious ones.

---

<!-- S15 -->

*Watch Out · A/B & Obs · 5 min*

### The 50-session winner that wasn't

> **Why this mistake is easy to make**
> 
> Running a proper A/B test takes time, requires sample size calculation, and can take days or weeks to reach significance. Comparing 50 sessions of the new version to 50 sessions of the old version takes an afternoon. A 50-session comparison that looks positive is a confirmation check rather than a meaningful test. The sample is too small to distinguish signal from noise.

#### The prompt change that looked like a win

The following is a composite representing a pattern that surfaces in teams that have a working system and want to improve it but do not have a formal experimentation process.

A team running a customer service agent wanted to test a revised instruction in the system prompt. They ran the new version against 50 customer sessions and the old version against 50 sessions. The task success rate was 68% on the new version and 62% on the old version. They declared the new version a winner and deployed it.

Two weeks later, the task success rate on the new version had settled at 61%. The apparent 6-point gain had disappeared.

#### What broke

The comparison had three problems, any of which was sufficient to invalidate the result.

- **The sample size was too small.** A 6-point difference on a metric with high variance requires a sample size in the hundreds to reach statistical significance. At 50 sessions per group, the observed difference was within the noise floor.
- **The input distribution was not controlled.** The 50 sessions in the treatment group happened to contain fewer edge-case inputs than the 50 sessions in the control group. The apparent improvement was partly an artifact of which inputs were routed to which group.
- **The primary metric was not pre-specified.** The team compared the task success rate because it moved in the right direction. If it had moved in the wrong direction, they would have looked at another metric. Selecting the metric after seeing the result turns a test into a search for whatever metric happened to move.

> **What to Watch Out for**
> 
> An underpowered experiment with metric selection after the fact produces confirmation rather than evidence, since the result reflects the hypothesis you started with. The result was noise, and the noise looked like a signal because the sample was too small to tell the difference.

---

<!-- S16 -->

*Checkpoint · A/B & Obs · 5 min*

### Place on the experiment-design plane

The plane below has two axes: the **expected effect size** (how large a difference you expect to see) and the **confidence requirement** (how certain you need to be before acting on the result). Place each scenario in the correct zone. The correct placement determines the right experimental posture, which in turn determines the minimum sample size.

← Small effect

Large effect →

↑ Confidence increases

High confidence

Small effect · High confidence

Large effect · High confidence

Moderate confidence

Small effect · Moderate confidence

Large effect · Moderate confidence

Low confidence

Small effect · Low confidence

Not used in this exercise

**Sorting exercise (answer key):**
- **Small effect · Low confidence:**
  - A. A minor wording change to a clarification message in a low-stakes FAQ chatbot. — *Small effect · Low confidence. The effect of a wording change on a clarification message is unlikely to be large. The cost of being wrong is low. A small, fast comparison is appropriate.*
- **Small effect · High confidence:**
  - B. A prompt architecture change for a medical intake summarizer where an error could delay treatment. — *Small or unknown effect · High confidence. In a high-consequence deployment, a small sample that happens to look positive is not sufficient. The confidence requirement is driven by the consequence of a wrong call, not the expected effect size.*
- **Large effect · High confidence:**
  - C. Adding a new classification category to a routing model expected to capture 30% of incoming volume. — *Large effect · High confidence. A 30% routing shift has a large effect that affects a substantial fraction of requests. High confidence is required before deploying a change of this magnitude.*
- **Large effect · Moderate confidence:**
  - D. Testing whether switching from Sonnet to Haiku on a simple formatting task saves cost without degrading quality. — *Large effect on cost · Moderate confidence. The cost effect of a model tier change is expected to be large and is easy to measure. Quality degradation is the risk to monitor, but the cost signal is strong enough to reduce the confidence requirement for the cost component.*
- **Small effect · Moderate confidence:**
  - E. A small change to the retrieval prompt in a RAG system processing 200 requests per day. — *Small effect · Moderate confidence. Retrieval prompt changes tend to have subtle, distributed effects on output quality. At 200 requests per day, reaching significance on a small effect takes longer, which raises the effective confidence requirement.*

---

<!-- S17 -->

*Exercise · Evals · 8 min*

### Exercise: define the evaluation framework

> **The brief**
> 
> A regional insurer is deploying a Claude system that reads a submitted claim, extracts structured fields (claimant, policy number, loss amount, date of loss), summarizes the narrative for an adjuster, and flags claims that may warrant fraud review. The system must respond within a few seconds, stay within a defined per-claim cost, never leak one claimant's data into another's summary, and never auto-deny a claim.

Draft the evaluation framework for this system. For each of the five dimensions below, write the metric, the grading method (code-based eval, LLM judge, or human review), and a one-sentence reason for your choice. Write your framework, then reveal the model answer below.

*[Click-to-reveal an answer to compare with your response; feel free to ask Claude to compare what you've written with the provided answer.]*

*(Free-response exercise: 1. Accuracy: field extraction)*

*(Free-response exercise: 2. Latency: response time)*

*(Free-response exercise: 3. Safety: summary faithfulness and no auto-deny)*

*(Free-response exercise: 4. Security: no cross-claimant data leakage)*

*(Free-response exercise: 5. Cost: per-claim spend)*

> **Model answer**
> 
> **1. Accuracy, field extraction:** Code-based eval. The expected values (claimant name, policy number, loss amount, date of loss) are known and verifiable by exact or schema match. No interpretation required; a function checks the output against the ground truth.
>  **2. Latency, response time:** Code-based eval. Latency p95 is a number. The check is whether it falls below the target. No judgment involved.
>  **3. Safety, summary faithfulness and no auto-deny:** Two methods required. Code-based eval for the deny action (binary, either a denial was issued or it was not). LLM judge for summary faithfulness (whether the narrative accurately represents the source claim without fabrication is an interpretive task a function cannot encode).
>  **4. Security, no cross-claimant data leakage:** Code-based eval. Cross-claimant leakage can be checked by scanning each summary for identifiers that appear in any input claim other than the one being processed. Deterministic check, no interpretation needed.
>  **5. Cost, per-claim spend:** Code-based eval. Cost is a numeric value derived from input tokens, output tokens, model tier, and whether prompt caching applies. The check is whether it exceeds the ceiling.

---

<!-- S18 -->

*Cumulative · Module · 13 min*

### Production readiness builder

> **The brief**
> 
> A 600-person management consulting firm wants to deploy an internal knowledge assistant. The assistant should help consultants retrieve relevant excerpts from past engagement reports, answer questions about firm methodologies, and generate first-draft responses to client RFPs using past work as a source. The knowledge corpus is 12,000 documents, ranging from 5 to 80 pages each. Consultants use the assistant during active engagements, with peak usage of 800 requests per day. The firm has a $3,000/month cost ceiling. Response time must be under 8 seconds at p95. The firm has an existing SSO system (e.g., Okta or others) and a document management system (e.g. SharePoint or others). Several documents contain client-confidential information that is subject to NDA.

Click-to-reveal answers to compare with your responses; feel free to ask Claude to compare what you’ve written with the provided answer.

*(Free-response exercise: Decision 1, Eval strategy. Before any build begins, you need to define what success looks like for this system. What is your primary eval task? How will you measure retrieval relevance and RFP draft quality? What eval type do you use for each? Name one behavior suited to a code-based eval and one suited to a model-based eval. What is your golden dataset strategy? How will you handle the client-confidentiality constraint?)*

*(Free-response exercise: Decision 2, POC-to-production checklist. You have a working prototype. What do you need to verify before the firm commits to deployment? Build a cost model for the scenario. Does the projected cost fall within the $3,000/month ceiling? Which reliability pattern is most critical for this deployment and why? Name the failure mode specific to this architecture type that you are most concerned about.)*

*(Free-response exercise: Decision 3, Use-case sizing and feasibility. Run the use case through the four AI properties. Is this feasible as scoped? Apply the working memory axis. Do the 80-page documents present a constraint? Apply the knowledge axis. The firm's proprietary methodologies are not in training data. What is the mitigation? State the feasibility verdict and name the load-bearing boundary condition.)*

*(Free-response exercise: Decision 4, Integration pattern selection. The firm has Okta SSO and SharePoint. Where does the Okta identity boundary sit relative to the Claude call? The documents in SharePoint include client-confidential files, how do you handle the data handling constraint? What do you instrument for observability?)*

*(Free-response exercise: Decision 5, A/B testing posture. The firm wants to test a new retrieval configuration that they believe will improve RFP draft quality. Frame the hypothesis. What is the treatment, the primary metric, and the constraint on secondary metrics? Estimate the required sample size. The baseline task success rate is 70% and you want to detect a 5-point improvement. What does this mean for the experiment duration at 800 requests per day? What input distribution control do you need given the corpus structure?)*

> **Model answer**
> 
> **Decision 1, Eval strategy:** Code-based eval: schema compliance on extracted citations (document name, page number, section). Model-based eval: relevance and appropriateness of the draft response to the RFP. Golden dataset: built from past RFPs with redacted client names, sourced from the firm's historical engagements. Client-confidential documents are excluded from the eval set unless the client has given explicit approval.
>  **Decision 2, POC-to-production checklist:** Cost model: 800 requests/day × 30 days = 24,000 requests/month. System prompt ~2,000 tokens (methodology overview + instructions) + retrieved context ~3,000 tokens + query ~200 tokens = ~5,200 input tokens. Output ~600 tokens. At Sonnet tier with caching on the stable system prompt, projected cost is within range. These are flat averages, and the answer should make that clear: the projection assumes requests cluster near the mean with no heavy tail. The corpus runs from 5 to 80 pages, so retrieved-context size is likely bimodal, and a tail of large excerpt requests understates input cost on a flat average model. The within-ceiling verdict holds under the assumed distribution and should be checked with the sensitivity analysis from the sizing cluster before it is relied on. Reliability: fallback chain from Sonnet to Haiku for latency spikes. Most critical failure mode: retrieval quality drift as documents are added to the corpus. If new documents are indexed inconsistently, retrieval precision degrades and draft quality degrades with it.
>  **Decision 3, Use-case sizing and feasibility:** Working memory: No individual document in this corpus (up to 80 pages, approximately 29,000 tokens) exceeds the current Claude context window of 1 million tokens on most current models. The binding working memory constraint is corpus scale: 12,000 documents cannot be loaded into context simultaneously. This is what drives the RAG architecture. At ~29,000 tokens per 80-page document, a single document at the maximum length fits well within the context window and does not present a working memory constraint on its own. Across the full 12,000-document corpus, average document length across the 5–80-page range is roughly 14,600 tokens. The total corpus represents approximately 175 million tokens. This far exceeds any context window. For individual documents within this size range, chunking strategies are available but are not the load-bearing constraint here. The architecture requires a retrieval layer to surface relevant excerpts at query time. Knowledge: The firm's proprietary methodologies are not in Claude's training data, which means the model cannot supply them from memory. The mitigation is retrieval: the methodology documents are indexed in the same RAG layer as the engagement reports and are surfaced into the context window at query time when a question is relevant to them. This is the standard compensating control for knowledge gaps on domain-specific content. The system does not need Claude to know the methodologies; it needs Claude to reason over methodology excerpts that the retrieval layer puts in front of it. The constraint is that retrieval quality must be high enough to surface the right methodology content for a given query. If retrieval misses the relevant section, the response will be incomplete regardless of how well the model reasons over what it receives. Retrieval precision on methodology queries should be tracked as a separate metric in the eval suite and in production observability. Feasibility verdict: Feasible with constraints. All four AI property axes are addressable within the scoped architecture. Working memory constraints are resolved by the RAG layer. Knowledge gaps on proprietary methodologies are resolved by indexing those documents into the same retrieval corpus. The steerability requirement is met by the system prompt structure and the output schema for RFP drafts. The load-bearing boundary condition is retrieval index coverage and freshness. The system works as long as the retrieval index contains the relevant methodology and engagement documents and is kept current as the corpus changes. If the index is incomplete, if documents are added without being indexed, or if the index drifts out of sync with the document management system, the knowledge axis mitigation fails and the system will produce responses that omit or misrepresent firm methodology. That condition must be documented as an explicit operational constraint in the statement of work.
>  **Decision 4, Integration pattern selection:** Identity: Okta token is verified server-side. User role and authorized document sets are injected into the system prompt by the server, not supplied by the user. Client-confidential handling: documents tagged as confidential in SharePoint are only retrievable by consultants whose role includes the relevant client engagement. The retrieval layer enforces this access control before passing content to Claude. PII: client names in documents are replaced with anonymized identifiers before the document enters the context window. Observability: log model version, input token count (with caching hit/miss), retrieval precision per request (measured against the grounding documents), and output token count. Log user role and session ID at the context layer. Capture the consultant's acceptance or revision of the RFP draft as the outcome signal. Alert on latency p95 crossing 8 seconds and on retrieval precision dropping below threshold.
>  **Decision 5, A/B testing posture:** Hypothesis: The new retrieval configuration will increase RFP draft task success rate (as measured by consultant acceptance of the draft without major revision) from 70% to at least 75%, without increasing latency p95 above 8 seconds or cost per request by more than 10%. Sample size: detecting a 5-point improvement at 70% baseline with 80% power and 5% significance requires approximately 1,500 sessions per group. At 800 requests per day split evenly, this takes approximately 4 days, which is feasible. Input distribution control: ensure the treatment and control groups have similar distributions of RFP complexity (proxy: document length and number of source documents retrieved). Segment by RFP type if possible.

---

<!-- GLOSSARY -->

*Reference · Wrap-up*

### Glossary

The key terms used across this module, in alphabetical order. Click a term to expand its definition.

**▸ 5xx errors**

The class of HTTP status codes (500–599) indicating a server-side failure to fulfill an otherwise valid request. Common examples include 500 (Internal Server Error), 503 (Service Unavailable) and 529 (Overloaded Error). Usually transient and resolvable with retry and backoff, distinct from 4xx codes which indicate a client-side problem.

**▸ BAA (Business Associate Agreement)**

A contract required under HIPAA between a covered entity (or business associate) and a vendor that handles protected health information on its behalf. The BAA specifies the safeguards the vendor will apply to PHI. For Claude deployments, BAA coverage is configuration-specific: the same surface may be BAA-covered on one delivery route and not on another. Check coverage by configuration, not by product.

**▸ Caching**

Caching stores reusable prompt content so the system does not need to reprocess it on every request. It is most effective when the system prompt is long and stable, reducing both token cost and response latency; the response you receive is identical to what you would get without caching.

**▸ Circuit breaker**

A reliability control that monitors the error rate on a downstream dependency and, when errors exceed a defined threshold, blocks further requests to that dependency for a cooldown window so that one degraded component does not consume the calling system's capacity. Sits at the service boundary, distinct from retries (close to the API call) and fallback chains (in the orchestration layer).

**▸ Data-residency pinning**

Configuring the integration so that model execution happens in a specified geographic region, typically to satisfy sectoral regulations, or internal data-residency policy. Pinning is implemented at the delivery route level on CSP-mediated integrations. The pin must be set at the integration layer and verified at request time, not assumed by the entry point choice alone.

**▸ DPA (Data Processing Agreement)**

A contract between a data controller and a data processor defining how personal data may be handled on the controller's behalf, including processing scope, security obligations, sub-processor terms, and breach notification.

**▸ Eval**

A structured test set used to measure whether a model is performing well enough on a defined task. An eval pairs inputs with expected outputs or quality criteria, runs them against the model, and produces a score you can compare across model versions, prompts, or configurations. Evals are how teams decide whether a change is an improvement or a regression before it reaches production.

**▸ Exponential backoff**

Exponential backoff is a retry strategy where, after a failed request, the system waits before trying again and each successive wait is longer than the last, typically doubling each time.

**▸ GDPR (General Data Protection Regulation)**

The European Union (EU) regulation governing the processing of personal data of individuals in the EU and European Economic Area (EEA). Establishes lawful-basis requirements, data subject rights, controller and processor obligations, and fines up to 4% of global annual turnover.

**▸ Generator-verifier loop**

A two-stage pattern in which a model-generated output is checked by a second pass before being used downstream. The verifier may be a deterministic code-based check (schema validation, comparison against an authoritative value) or a second model call scoped to evaluation. Used as a compensating control where the underlying task requires more precision than single-pass generation reliably provides.

**▸ Hallucination rate**

The percentage of responses in which the model invented, inferred, or stated information that was not supported by the input, source data, or allowed logic.

**▸ Live state**

Data that changes during the lifetime of a conversation or process: an order status, an inventory count, a price, a calendar slot, a user's current session. Live state is distinct from static reference material because the correct answer at 10:00 a.m. may be wrong by 10:05. Systems that need live state require a direct lookup against the source of truth, not a stored snapshot.

**▸ Median latency**

Median latency is the time it takes to complete the middle request in the distribution, which means 50% of requests are faster and 50% are slower. It is also called p50 latency.

**▸ p95 (95th-percentile latency)**

The latency value below which 95% of requests complete, with the slowest 5% falling above it. Used as a production design target because SLA breaches and user abandonment are driven by the slow tail of the distribution rather than the median.

**▸ PHI (Protected Health Information)**

Individually identifiable health information held or transmitted by a covered entity or business associate under the US Health Insurance Portability and Accountability Act (HIPAA). Processing PHI requires a Business Associate Agreement with any third party that handles it.

**▸ RAG (retrieval-augmented generation)**

A pattern in which a knowledge corpus is chunked and indexed in a preprocessing step, and at query time the chunks most relevant to the user input are retrieved and passed into the model's context. Suited to static or slow-moving knowledge such as manuals, internal documentation, and regulatory text. Not suited to live transactional state, where retrieval returns a snapshot that may already be stale and a tool call to the system of record is the correct mechanism.

**▸ Rate limit**

A server-enforced cap on the number of requests a client may make within a defined time window. When the cap is exceeded, the server rejects further requests (typically with HTTP 429) until the window resets. A rate-limit response indicates throttling rather than failure and is a transient condition that resolves with backoff.

**▸ Regex**

Regex stands for regular expression. It is a rule-based pattern used to find or validate text that matches a specific format, such as email addresses, phone numbers, Social Security numbers, or credit card patterns.

**▸ Schema**

The required structure, format, and rules for the output. This defines what fields must appear, their data types, allowed values, and how the response should be organized.

**▸ SSO (single sign-on)**

An authentication arrangement in which a user signs in once to a central identity provider and gains access to multiple downstream applications without re-authenticating.

**▸ Structured fields**

Structured fields are those which require specific outputs that must be populated in a defined format, such as customer name, invoice number, date, amount, or policy ID. These are discrete data elements, not free-form narrative text.

**▸ Timeout**

A failure mode in which a request does not receive a response within the client's or server's configured wait period and is terminated. Typically caused by transient server load, network latency, or a downstream dependency under stress, rather than a permanent fault.

**▸ Tool use**

The capability that lets Claude call external functions, APIs, or services during a response instead of only generating text. The model decides when to invoke a tool, what arguments to pass, and how to use the result in its next step. Tool use is what turns Claude from a text generator into a system that can read files, query databases, search the web, or take action in other software.

**▸ Transient error**

A transient error is a temporary failure that is expected to resolve on its own without any permanent fix, meaning if you try the same request again after a short wait, it will likely succeed.

---

<!-- S19 -->

*Recap · Module · 3 min*

### Five takeaways

Key takeaways:

- **01 Evals as acceptance criteria** — Write the eval suite before the production code. Keep the golden dataset current with every system change. Use the eval as the gate for every model swap or prompt revision.

- **02 POC to production** — Estimate cost and latency at production volume before committing to architecture. Build retries, fallback chains, and circuit breakers into the initial design. Name the failure mode specific to your architecture type and document the mitigation.

- **03 Use-case sizing and feasibility** — Run every new use case through the four AI properties before issuing a feasibility verdict. State the verdict in one of three forms: feasible as scoped, feasible with constraints, or not feasible. Document the load-bearing boundary condition for every constrained verdict.

- **04 Enterprise integration patterns** — Enforce identity at the server side. Pass only the minimum necessary data into the context window. Build observability instrumentation at design time, not after the first incident.

- **05 A/B testing and observability** — Identify the primary metric and the sample size before running any experiment. At scale, separate per-request observability from aggregate dashboards. Build a translation layer that maps technical metrics to the business metrics the stakeholder cares about.

Module 3 covers responsible AI, safety, and risk for Architects: guardrail design, regulated-industry considerations, and human-in-the-loop validation strategies.

#### Sources

- Anthropic Skilljar, Building with the Claude API: eval workflow stages, model-based vs. code-based evals, cost and latency modeling, caching, tool use, streaming.
- Anthropic Skilljar, Claude 101: model family overview, context windows, general Claude capabilities.
- Anthropic Skilljar, Claude Code in Action: Claude Code as an integration entry point, agentic patterns in practice.
- Anthropic Skilljar, AI Capabilities and Limitations: four AI properties framework, foundational concepts.
- platform.claude.com/docs: models overview page (capability and context-window figures), pricing page (per-token price points for cost modeling), and prompt caching page (caching mechanics and consistency risk guidance).
- Anthropic, Building Effective Agents: workflow and agent design patterns; when to use agents vs. simpler architectures.
- Anthropic Cookbook: failure-mode candidates and worked patterns.

---

<!-- CERT -->

**

## Congratulations! You have successfully completed this module.

Module 2 covers the integration patterns, production infrastructure, and operational decisions that take a Claude deployment from prototype to enterprise scale.

**Production reliability is an architecture decision, not an operational one; you now have the patterns to make it at design time.**

0
 of 0 checkpoints passed

M1

Claude Platform & Solution Design

Model selection, prompt architecture, tool design, and platform-layer tradeoffs.

M2

Enterprise Integration & Production

Deployment patterns, integration architecture, and production reliability.

You Are Here

M3

Responsible AI, Safety & Risk

Safety frameworks, risk identification, and governance practices.

Up Next

M4

Stakeholder Engagement, Lifecycle & Go-to-Market

Stakeholder communication, lifecycle management, and go-to-market strategy.

M5

Team Enablement and Operational Productivity

Team tooling configuration and operational support practices.

---
## Appendix: Inline term tooltips

- **model-based from code-based evals** — Model-based evals use a judge model to assess outputs requiring interpretation. Code-based evals run deterministic programmatic checks.
- **retries** — Retry with exponentially longer delays between attempts to avoid flooding a recovering endpoint.
- **fallbacks** — Automatic routing to an alternative model or cached response when the primary endpoint is unavailable.
- **circuit breakers** — Monitors error rate on a dependency; trips when errors exceed a threshold, blocking further requests during the cooldown period.
- **SSO** — Single sign-on: a user signs in once to a central identity provider and gains access to multiple downstream applications.
- **p95** — The latency value below which 95% of requests complete. The slowest 5% fall above it. More useful than median for SLA design.
- **Circuit breakers** — Monitors error rate on a dependency; trips when errors exceed a threshold, blocking further requests during the cooldown period to prevent cascading failures.
