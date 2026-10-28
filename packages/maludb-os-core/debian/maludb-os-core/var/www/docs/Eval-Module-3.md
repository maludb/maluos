# Claude Certified Architect — Module 3: Responsible AI, Safety & Risk for Architects

*Source: Anthropic Partners Skilljar (personal study notes)*

---

<!-- S01 -->

*Orientation · Module · 2 min*

### The safety stack: who owns each layer, and what happens when one fails

The earlier modules ended with an operational production system: each step of a partner problem was assigned to the right owner, a reference architecture and a model were chosen, the use case was sized, evals were built as acceptance criteria, and the integration layers were put in place to embed Claude inside an enterprise stack.

This module addresses the major security question: what controls are in place to stop a system from refusing a valid request, producing an unfair outcome, or taking an action no one approved? Safety is a full set of controls, each covering a different part of the request path, each with a blind spot the next one has to catch. The Architect is responsible for placing each control and deciding what to do if it fails.

#### By the end of this module, you will be able to:

- 1Distinguish between what the model's training reduces and what your application layer must still enforce.
- 2Place input screening, output screening, and tool-call authorization at the appropriate points in the request path and determine when to use model-based versus deterministic checks, so the system fails closed instead of failing open.
- 3Identify where unequal outcomes can arise within a system and define the explanations required for users, regulators, and your own debugging team, so fairness and transparency are built into the design.
- 4Route decisions to the appropriate reviewer/ decision maker based on confidence, reversibility, and the cost of a wrong answer, so review effort is focused on the decisions that warrant them.
- 5Map each compliance obligation to a named control, an owner, and an evidence artifact, so the architecture can be accurately audited.

This module is for the Architect who has already built a working system: ownership assigned, architecture chosen, evals built, and Claude wired into an enterprise stack. Claude arrives with broad safety behavior in place, but it does not know the partner's data-handling rules, authorization model, or domain policy. Assuming Claude enforces a rule it was never given is the most common way a safety design can fail.

Everything in this module is built around one context: a system that passes every architecture review and still fails in production. The responsibility layer was incomplete, assumed, or correct at design time but wrong by the time someone audited it. The partners are enterprise buyers in regulated settings, where a control that looks solid in a demo becomes an audit finding when configurations drift or a reviewer asks for evidence the control is running.

> **The decisions map onto the sections that follow**
> 
> **The alignment boundary** is where you draw the line between what the model's training already reduces and what your application layer must still enforce. Assuming that trained alignment covers a domain policy leaves the rule unenforced in every layer. The module starts here because this impacts every downward decision.
>  **Guardrail placement** is where you position input screening, output screening, and tool-call authorization on the request path, choose whether each check is model-based or deterministic, and decide what the control does when it fails. A single filter at the end of the path does not cover the other two points, and a control that fails open is worse than no control, because it provides the appearance of protection without any of the function.
>  **Fairness and transparency** is where you identify where unequal outcomes can enter the system, and they build the logging that lets you explain any decision afterward. The four injection points are yours to instrument.
>  **Human-review routing** is where you decide which decisions a person should weigh in on and what that reviewer needs to do their job. Simply routing by volume floods the queue and often forces reviews to collapse into approvals. The decisions that warrant attention are the ones with high stakes and low confidence, and those stakes need to be pre-identified.
>  **The compliance control register** is where each obligation becomes an identified control, an accountable owner, and an evidence artifact that a reviewer can inspect. Choosing a compliant entry point is a prerequisite. A control with no owner and no living artifact can go non-operational without anyone noticing, and then appear as a gap during an audit.

These topics build on each other. The boundary you draw in the first section is enforced by the controls in the second, the logging you build for fairness is the same logging the reviewer uses in the fourth section, and the control register in the fifth section draws on every instrumented layer above it. The cumulative task at the end asks you to assemble all five into a defensible deployment from a single brief, which is exactly what this module equips you to do in front of a security reviewer or compliance auditor.

> **Disclaimer / Notice for Educational Content**
> 
> We built this Architect course Module 3: Responsible AI, Safety, and Risk for Architects to help you get real work done with Claude. Treat it as educational content. It doesn't constitute legal, financial, or other professional advice, so adapt what you learn to your own situation. Our products and services evolve quickly, so certain content may contain errors or be outdated; remember to verify on Anthropic's website or docs. Examples and scenarios used in the course are illustrative and often fictitious. If the course material mentions a company or product, it doesn't mean Anthropic endorses them, they endorse Anthropic, or that we're affiliated. Also note your use of Anthropic products and services is covered by our terms, policies and documentation; if anything in this course conflicts with them, they control.

---

<!-- S02 -->

*Teaching · Alignment · 11 min*

### What the model's training enforces versus what you own

Earlier work established the architecture, the model, and the integration. Here we answer: before you start adding controls, how much safe behavior is already handled by the model, and how much is still yours to build? You need to understand this boundary clearly to avoid creating duplicate protections or assuming the model is enforcing a rule it has never seen.

Anthropic trains Claude against a constitution: a written document that describes the values and behavior the model should exhibit, so the model is deployed with broad safety behavior already in place. Anthropic revises this document over time, and the most recent published version is from January 2026. The document is used during training to generate examples the model learns from and to rank candidate responses. This shapes how the model responds to ambiguous or sensitive requests but does not necessarily catch bad outputs. It sets a priority order for the model to follow when goals conflict: be broadly safe, be ethical, comply with guidelines, and be genuinely helpful to operators and users. That ordering matters because a helpful answer is sometimes unsafe. The ordering is holistic rather than strict, so higher-priority goals generally take precedence when they conflict, though the model weighs them together rather than applying them in a rigid sequence. The model arrives with a class of harmful output already reduced before you write a single prompt. The built-in layer handles broad, general-purpose harm, but does not cover your specific domain: any policies specific to your users and product are still yours to enforce.

#### Training-time alignment and inference-time control are two layers with distinct purposes

Training-time alignment shapes model behavior before deployment. It reduces broad classes of harmful output by steering Claude to refuse dangerous requests and default toward safer responses. Because it is set before any deployment exists, it is general by design. This is both a strength and a weakness: it does not know your partner's domain policy, data-handling rules, or authorization model. A request can fit Claude's general alignment and still violate a deployment-specific rule, such as disclosing another customer's order information or advising outside an approved script. Remember, Claude cannot enforce a rule it was never given.

Deployment-specific rules are enforced by the second layer: inference-time control. This includes the runtime guardrails you configure for your deployment, such as system instructions, input and output checks, tool permissions, and human review gates. System instructions shape the model's behavior, but deployment-specific policy is enforced only when those instructions are paired with runtime controls such as screening, authorization, and review. Training-time alignment lowers baseline risk, and inference-time control enforces the rules specific to your deployment.

#### A layered view: each layer has a job and a blind spot

Treat safety as four layers stacked from Claude outward. Each one covers something the layer below cannot, and each one fails in a way the next must catch.

Select each layer to see what it reliably covers, what it does not, and who owns it.

#### Tab: Trained behavior

**What it reliably covers:** Broad classes of harmful or unsafe output, applied to every request without configuration.

**What it does not cover:** Your domain policy, your data rules, your authorization model.

**Who owns it:** Anthropic.

#### Tab: System-prompt instruction

**What it reliably covers:** Role, tone, and stated constraints that steer Claude inside one request.

**What it does not cover:** Anything an adversarial or unusual input can talk Claude out of, since instructions are not enforcement.

**Who owns it:** Architect.

#### Tab: Runtime screening

**What it reliably covers:** Input and output screening that detects disallowed content.

**What it does not cover:** Actions with side effects, which screening does not authorize, and novel attacks that a classifier misses.

**Who owns it:** Architect.

#### Tab: Authorization

**What it reliably covers:** Whether a specific action with a side effect is permitted for this caller in this context.

**What it does not cover:** Content quality and fairness.

**Who owns it:** Architect.

> **Cost · Complexity · Risk**
> 
> **Cost:** Each added layer costs latency and engineering. A pre-screen on input and a check on output add two extra calls or rules to every request.
>  **Complexity:** Four layers means four places to design, version, and test. The system prompt and the screening logic drift independently if not governed.
>  **Risk:** The most dangerous failure is a silent one: assuming Claude enforces a domain rule that it was never given. Since the rule doesn't exist in any layer, nothing prevents a violation.

---

<!-- S03 -->

*Watch Out · Alignment · 3 min*

### When trained refusals are mistaken for a domain policy

> **Setup hook**
> 
> You are a strong systems Architect. Claude already refuses broadly harmful requests in testing, so you assume its training also covers your partner's data handling policy. You move on without building a separate enforcement layer.

#### A postmortem: a policy that was never encoded in any layer

A team deployed an internal assistant for a partner whose data-handling policy prohibited users from accessing records belonging to other business units. In review, Claude had refused every harmful prompt the team threw at it, so they assumed cross-unit disclosure was covered by the same safety behavior and never built an authorization check for it.

In production, a normal-looking, in-domain request asked for a forbidden record. Nothing in the request looked harmful in general terms, so Claude answered it. The rule the team believed was enforced actually did not exist. It was never part of Claude's training, and the team never encoded it in a classifier, system prompt, or application control, because they assumed the model already covered it.

> **Why this broke**
> 
> A domain policy was conflated with trained alignment. Trained refusals cover broad harm, not deployment-specific rules. Any rule that is specific to your partner must be enforced in a layer you build. Remember, Claude cannot enforce what it was never given.

---

<!-- S04 -->

*Checkpoint · Alignment · 3 min*

### Sort the responsibility

**Try it now.** You are reviewing the safety design for a partner's Claude assistant. Drag each obligation into the bucket that should enforce it: either Claude's trained behavior, or the application layer. The feedback explains why each one falls where it does.

**Sorting exercise (answer key):**
- **Claude's trained behavior:**
  - Refusing to help synthesize a dangerous weapon — *Claude's trained behavior, a broad harm class.*
  - Declining to produce plainly hateful content — *Claude's trained behavior.*
- **Application layer (you own it):**
  - Never returning another tenant's data — *Application layer, a deployment-specific authorization rule.*
  - Blocking advice outside the partner's approved script — *Application layer, a domain policy Claude never saw.*
  - Requiring a sign off before a refund is issued — *Application layer, an action-authorization rule.*

---

<!-- S05 -->

*Teaching · Guardrails · 9 min*

### Risks, limitations, and failure modes of LLM systems

You have placed the controls; now identify what they defend against. An Architect is expected to conduct and document a risk assessment for a proposed system as part of a security deliverable. This screen covers the risk categories that recur in LLM systems and turns them into a written assessment that you can run.

#### The risk categories that recur in LLM systems

Most LLM-system risk falls into a small set of categories. Identify these categories and check your designs against each:

1. **Direct prompt injection:** A user crafts input that overrides the system's instructions and redirects its behavior.
2. **Indirect prompt injection:** Malicious instructions arrive through retrieved content or tool outputs that the model treats as trusted and the vector input screening does not catch.
3. **Token-budget exhaustion:** Oversized or adversely padded inputs consume the context or output budget, truncating work or inflating cost.
4. **Tool and action abuse:** The model is induced to call a side-effecting tool outside policy, the failure the action-authorization control exists to stop.
5. **Data exposure:** Sensitive fields enter the context window or the logs where they should not, creating a leak independent of model behavior.

#### System vulnerability assessment: where to look

Walk the request and data paths together. At each entry point, user input, retrieved content, tool outputs, the model's own output, and the logs, ask what an adversary could do and which control stands in the way. Look for anywhere without a control where there could be a plausible attack.

#### Documenting the risk assessment as a deliverable

The risk assessment should be a written artifact. For each identified risk, record the category, the affected component, a likelihood-and-impact judgment, and the mitigation control with an owner and an evidence artifact. That document is what the security reviewer will sign off on, and it is what the cumulative exercise at the end of this module expects you to be able to produce.

---

<!-- S06 -->

*Checkpoint · Guardrails · 4 min*

### Assess the risks in a proposed architecture

**Try it now.** You are reviewing a proposed architecture: a customer-support agent that retrieves answers from a partner knowledge base and issues refunds through a connected tool, with all activity written to a request log. Identify at least three risk categories present in this design, and for each one name a workable mitigation. Both the risk and a mitigation that addresses it are required.

*(Free-response exercise: Identify the risk categories present in this design and pair each with a mitigation.)*

> **Model answer**
> 
> **1. Indirect prompt injection via the knowledge base.** Retrieved content can carry instructions; mitigation is to treat retrieved text as untrusted and screen tool/content inputs, not just user input.
>  **2. Tool and action abuse on the refund tool.** Mitigation is an action-authorization check that runs before the refund tool executes, independent of the model's output.
>  **3. Token-budget exhaustion on large knowledge-base documents.** Mitigation is chunking and input limits plus budget monitoring so a large document cannot truncate the work silently.
>  **4. Data exposure in the request log.** Mitigation is server-side redaction of sensitive fields before anything is logged.

---

<!-- S07 -->

*Teaching · Guardrails · 14 min*

### Placing screening and authorization so the system degrades safely

A control that screens requests can fail the same way any dependency fails. It can time out, return an error, or become unreachable under load. The difference is that a failing guardrail can still look healthy: when a screening service errors but still passes traffic through, requests keep flowing while the control does none of the work it was placed there to do. So, when a guardrail errors, the system must do one of two things: let it through or block it. If you have not made that choice explicitly, the surrounding code decides for you. The default is almost always to let the request through, which means falling back to the unprotected path. The same reasoning that put retries and circuit breakers around your model calls applies here: decide how the control behaves when it fails, rather than inheriting whatever behavior happens to keep requests flowing.

#### Where guardrails sit in a request path

A guarded request path has a few decision points, each answering a different question.

- **Input screening** runs before the model call and decides whether the request should reach the model at all.
- **Output screening** runs before the response reaches the user and decides whether what the model produced is safe to return.
- **Tool-call authorization** runs before any action with side effects, such as sending an email, writing to a database, or issuing a refund, and determines whether this caller may perform this action in this context.

Because they sit at different points and check different things, a control at one place does nothing for the others, which is why a single filter cannot cover the whole path.

#### 

**▸ Where each check fits: model-based vs deterministic by decision point**

| Decision point | A model-based check is needed when | A deterministic check is better when |
| --- | --- | --- |
| **Input screening (before the model call)** | Intent is ambiguous and you are catching jailbreak or prompt-injection patterns that cannot be exhaustively captured with rules. A lightweight model classifies the input. | The rule is clear and defined: a blocklist, a regex, a length or format check. It is faster, predictable, and cannot be talked out of its decision. |
| **Output screening (before the response reaches the user)** | You are evaluating qualities like toxicity or policy compliance that need language understanding. A judge model scores the output. | You are checking for a known string, a forbidden field, or a schema violation that a validator catches with certainty. |
| **Tool-call authorization (before any side-effecting action)** | Rarely. Authorization should be deterministic, so it is auditable. | Almost always: an allowlist of permitted actions, identity checks, and scope validation. Authorization must be a decision you can prove and replay, so it must be deterministic. |

#### Why model-based and deterministic checks fail differently, and why you chain them

A model-based classifier can be evaded: a user can phrase an input in a way that bypasses even the strongest of judge models. A deterministic rule is brittle: it blocks exactly what it is programmed to detect and nothing more. It misses anything it did not anticipate and over-blocks anything that resembles a restricted pattern. There is no control that catches everything, so these controls are deployed in series. Identifying what each one misses ensures each gap is deliberately covered by a different control rather than left open.

#### A second injection vector: instructions arriving through retrieved content and tool outputs

User-input screening catches instructions the user sends directly. It does not catch instructions embedded in content the system retrieves or receives from tools. In a RAG system, a malicious instruction in a retrieved document reaches the model after input screening has already passed the request. In an agentic system, a tool response can carry instructions the model treats as authoritative. This is the dominant injection vector in enterprise deployments with retrieval or tool use, and it requires a separate control: screen retrieved content and tool outputs before they are appended to the model's context, using the same model-based classifier you apply to user input. The blind spot is different because the source is different; identify it explicitly in your control design to ensure coverage.

On the API, responses return a refusal when streaming classifiers intervene. The Messages API reports this as `stop_reason: "refusal"` accompanied by a `stop_details` object (available since Claude Opus 4.7). That object carries a policy category along with a readable explanation; both fields are null when the refusal does not map to a named category. The category set is enumerated in the stop-reasons documentation on platform.claude.com. As of this writing it includes `cyber`, `bio`, `frontier_llm`, and `reasoning_extraction`. Re-check the list at publish time rather than hardcoding it. Your application should read the category and route different refusal classes accordingly, rather than treating every refusal as a single, undifferentiated event. On models that do not return `stop_details`, your handler must tolerate an absent object and fall back to generic handling. Verify current model support against platform.claude.com at publish time. As a rule, once a refusal is received, reset the conversation context before continuing: remove or rephrase the turn that triggered the refusal, or clear the history. Sending the next request on the same refused context returns further refusals.

#### Fail open versus fail closed: how your guardrail layer behaves under failure

When the operator-built classifier errors under load, or your operator-built screening service is unreachable, the application does one of two things. It can fail open and pass the traffic through unscreened, or it can fail closed and block any additional actions until the control is healthy again. The choice belongs to you as the Architect; these are components your team builds, hosts and configures. They are separate from Anthropic's built-in model safety controls, which are not operator-configurable and do not fail open. An operator-built guardrail that silently passes traffic when it errors is worse than one that blocks traffic, because it gives you the reassurance of having control while providing none of the protection. This is the same reasoning as the circuit breaker from the production work: when a dependency in your stack is failing, degrade deliberately based on the situation.

#### The full guarded request path, as one system

A request moves through the path in order: it arrives, input screening decides whether it reaches the model, the model produces a response, output screening decides whether that response is returned, and any tool call the model emits passes through authorization before it runs. Each gate can pass, block, or fail, and each fail resolves to the direction you chose. Every blocked or failed gate is logged, so an incident can be reconstructed from the record.

**The full guarded request path**
 **User request** → **Input screening** (model-based for ambiguous intent, deterministic for defined rules, set to fail closed)
 → **Model call** → **Output screening** (judge model or validator, set to fail closed)
 → **Tool-call authorization** (deterministic allowlist plus identity and scope) before any side-effecting action
 → **Response to user**, with every blocked or failed gate logged for later reconstruction

#### Skill supply-chain security

You may hear the following objection in the field: "Skills are a black box. I can't see everything inside one until it runs, so how am I supposed to trust it?" The architect's job is to build a control that compensates for this.

As a reminder, skills are reusable, distributable code paired with an instruction set, bundled together and dropped into your environment. That distribution model is what makes it a supply-chain risk. An untrusted skill can carry a code-execution exploit: logic that runs commands, reaches out to the network, or touches files the moment it's invoked. That's risky because the skill may include hidden malicious instructions that your input filters and prompt screening can't see; these watch the conversation, but the threat was baked into the bundle upstream in the skill. Output monitoring might catch a downstream effect after the fact, but by then the code will have already run.

So, the defense must move earlier in the chain. Before you can trust and call a skill, you need to audit it: open the bundle and read it for two things. First, look for anomalous calls: network requests, shell execution, file-system access, credential reads. Second, out-of-scope operations: behavior that doesn't match the job it claims to perform. A formatting skill that phones home is out of scope; a summarizer that writes to disk is out of scope. The stated purpose of a skill should be your audit baseline, and anything that goes beyond it is a finding you should investigate.

Your audit tells you what's in your bundle; a skill that passes review clean can still reach out at runtime to fetch code that was never in the package you read. That's why the gate needs a net. Run skills with least privilege and in a sandbox giving them limited file access, limited network, no standing credentials they don't need. The audit decides what gets in; runtime confinement contains it if the audit misses something. You should use both, because no single control will work perfectly without the other.

You should also consider where skills are allowed to come from; only trust skills from a vetted internal registry, verified publishers, signed releases only. A trusted-source policy shrinks the surface you must audit and stops untrusted bundles before they reach review. One rule of candor always applies: do not assume the platform screens skills for you. Verify what automated vetting actually exists; read the documentation, confirm the scope of any scanning, find out what it does and doesn't catch.

Every audit must end in an explicitly recorded verdict: approve, reject, or remediate. Approve means it's clean and cleared for use. Reject means it does not enter the environment. Remediate means you found a fixable problem; in this case, strip the offending call, sandbox the operation, pin a safer version, and then re-audit it. Even though you may never see everything a skill can do, the audit verdict and a trusted-source policy are the compensating controls that let you act responsibly.

> **Cost · Complexity · Risk**
> 
> **Cost:** Each screening point adds a call or a rule evaluation to every request. A judge model on output roughly doubles the model cost for that turn.
>  **Complexity:** Three control points, each with a check type, a fail direction, and a log line, are materially more to build and test than a single filter.
>  **Risk:** Failing open is the costly mistake: underloading the system quietly drops protection while still appearing guarded, so the gap surfaces only in an incident. This risk does not apply to Anthropic's API-level controls, which are outside your configuration. It applies exclusively to the components your team builds and operates.

---

<!-- S08 -->

*Watch Out · Guardrails · 4 min*

### When a single output filter looks like a finished design

> **Setup hook**
> 
> Output filtering is a clear control you can point to; it shows up as a clean box on the architecture diagram, it fires where a reviewer can watch it work, and it sits at the end of the path where the risk feels most concrete, right before the user sees a response. So, if you add one classifier on the output, the diagram looks complete, and the review passes. The problem is that the most important thing the system does may have happened before that classifier ran.

#### A trace excerpt where the side-effecting tool ran before anything checked the request

The model received a request, called a tool that issued a refund, and the tool ran. A refund is a financial action: the tool reverses a charge and returns money from the company to the customer's account. Only after the money moved did the output filter look at anything. It inspected the text the model generated, found nothing unsafe, and passed. The refund had already happened. A control could have sat in three places on this path: screening the request on the way in, authorizing the tool call before it executed, and filtering the response on the way out. This system only had the last one, and it sat downstream of the only action on the path that could not be undone.

A customer service agent has access to an issue_refund tool. A user submits a request.
 **1** request received *(no input screening configured)*
 **2** model emits tool_use: issue_refund(order=…)
 **3** tool executes, refund issued *(no authorization gate before the side effect)*
 **4** output filter inspects generated text *(it passes, because the action it described had already happened)*

> **Why this broke**
> 
> A control was placed at one point but was treated as covering three points. Output screening judges text, not actions. A side-effecting tool needs authorization before it runs, and an unscreened input has no gate. One filter at the end is not a guarded path, you should be adding all three filters when necessary.

---

<!-- S09 -->

*Checkpoint · Guardrails · 4 min*

### Place the controls on the path

**Try it now.** You are given four controls. Each one answers two questions: where it sits on the request path, and what kind of check it is. Drop each control onto a grid. The horizontal axis is the placement point, from input screening to action authorization before a tool runs, to output filtering. The vertical axis is whether a deterministic check or a model-based check fit. Correct placement reveals the reasoning. **Not every zone will be filled, two cells will remain empty.**

**Sorting exercise (answer key):**
- **Input screening · Model-based:**
  - A. Jailbreak and prompt-injection screen — *Input, model-based, because the attack patterns are open-ended and a fixed rule list misses the next variant.*
- **Input screening · Deterministic:**
  - B. Banned term blocklist on the user message — *Input, deterministic, because the match is exact and the check should run fast and cheap.*
- **Output screening · Model-based:**
  - C. Toxicity judge on the generated response — *Output, model-based, because judging toxicity requires understanding that a function cannot encode reliably.*
- **Action authorization · Deterministic:**
  - D. Refund authorization policy check before the tool runs — *Action authorization, deterministic, because who is allowed to issue a refund must be auditable.*

---

<!-- S10 -->

*Teaching · Fairness · 11 min*

### Where unequal outcomes enter, and what the system must explain

Runtime controls stop disallowed outputs from leaving the system, ensuring users never see them. However, runtime controls don't account for an output that technically passes every check but produces different outcomes for different people. That failure is harder to detect and harder to attribute, because, on its surface, it looks like a normal output.

#### Unequal outcomes enter at identifiable points

Fairness becomes easier to design for once you stop treating it as a single attribute of the model and start treating it as something that enters at specific, identifiable points. In a Claude system there are four common entry points:

1. The **retrieval corpus** can over-represent or under-represent groups, so the context the model sees is already skewed.
2. The **framing of the prompt** can encode an assumption that pushes outcomes in one direction.
3. The **examples used in few-shot prompting** can carry the same skew the corpus does.
4. And the **downstream routing**, what happens to the model's output after it is produced, can direct some groups down different paths.

Each of these is an injection point you can inspect, which is what makes fairness a true architectural property.

#### Who asks determines what the system explains

| Audience | What they need | What that requires you to capture |
| --- | --- | --- |
| **An affected user** | A clear explanation of why a decision affecting them was made or expressed in terms they can act on. | The inputs that drove the decision and the reason the outcome was reached, in a digestible form. |
| **A regulator** | Evidence that the system treats comparable cases consistently and that a specific decision can be reconstructed on demand. | A durable, queryable record of inputs, outputs, and decision path. |
| **Your build team** | Enough detail to find why a flagged decision went wrong and fix it. | The full trace: prompt, retrieved context, model output, and every routing step, tied to the existing observability. |

#### Decision logging is what makes those explanations possible

To replay and explain a single decision, capture the inputs that drove it, the retrieved context, the model output, and the routing it went through. This is the same observable instrumentation from the production work, applied to a different question. This time, instead of asking whether the system is healthy, we're asking why a specific decision happened. The instrumentation is the same, but the retention and the query path are different.

#### A fairness-and-transparency checklist in action

Consider a credit-decision support system. Review the checklist once and the criteria stop being abstract:

- Which of the four entry points could skew this outcome, and is each instrumented?
- For an adverse decision, can you produce the inputs and the reason in terms the applicant can act on?
- If a regulator asks whether similar applicants were treated comparably, can you query the log and provide an answer?
- Can your team pull the full trace for any flagged decision?

A 'no' anywhere is a design gap.

#### Discernment: judging outputs for unequal treatment

Discernment is one of the four AI Fluency competencies: evaluating AI outputs and behaviors. In practice it means judging whether a model output is acceptable, needs revision, or needs override rather than accepting it. Applied to fairness, discernment is what lets a reviewer recognize a skewed or unjustified outcome instead of only confirming that a value was produced. A transparency record is what makes that recognition possible in the first place.

> **Cost · Complexity · Risk**
> 
> **Cost:** Capturing and retaining decision-level logs on every request adds storage and a query path, and the cost grows with traffic rather than staying fixed.
>  **Complexity:** Instrumenting four entry points and serving three audiences is more design work than a single audit log, because each audience needs a different slice of the same record. On top of that, the retention policy now must be governed, since you are holding decision-level data longer and for a specific purpose.
>  **Risk:** The outcome metric can look fine overall while harm is concentrated in one subgroup. An unlogged or unmeasured injection point can hide unfairness until someone outside the team finds it.
>  **Data handling:** The decision log is itself in scope for the compliance register. In HIPAA or GDPR contexts, logged inputs and retrieved context contain sensitive personal data. Apply minimization, retention limits, and access controls to the log, and map it as a named control in your compliance register. Logging everything for transparency and pinning data for compliance are not in conflict, as they require the same log, governed differently.

---

<!-- S11 -->

*Watch Out · Fairness · 3 min*

### When fairness is treated as the model provider's problem

> **Setup hook**
> 
> Fairness may seem like a property of the model. The model provider trained it, ran the bias evaluations, and published the results, so it feels reasonable to treat fairness as something handled upstream before the model reaches your architecture. That framing holds up until your system pairs the model with your own retrieval corpus, because a corpus that over-represents some cases produces unequal outcomes the model provider never tested and cannot see.

#### A post-incident review

This failure mode is worth recognizing early; the team made a reasonable assumption that ended up being wrong. They used a model that passed its fairness evaluations, and the skew entered at a point they had not thought to watch. What follows is one architect describing the gap in a post-incident review.

*"We assumed fairness was the model's job. The skew was in our retrieval corpus, and we had logged so little that we could not prove it."*

The unequal outcomes did not come from the model's training. Instead they came from a corpus that over-represented some cases, an injection point the team never monitored because they had assigned fairness to the vendor. When the outcomes were questioned, the team had no decision-level log to reconstruct what had happened. They could neither explain the specific decisions the system made nor rule out the corpus as the cause, which left them unable to answer the only question the regulator was asking: where did the skew come from?

> **Why this broke**
> 
> Fairness was treated as a model property the vendor owns. Unequal outcomes enter at points the architect controls, and the retrieval corpus is one of them. Without decision logging at those points, the team could not explain the harm or disprove its source. Fairness and explainability are architecture requirements. Instrument them at the points where skew can enter. Assuming they arrive with the model leaves those points unmonitored.

---

<!-- S12 -->

*Checkpoint · Fairness · 3 min*

### Critique the decision-logging design

**Try it now.** You are looking at a system sketch for a decision-support flow. Click the components where transparency is missing or insufficient, such as a routing step that is never logged or a decision that cannot be reconstructed. Each click reveals what that gap means for an affected user or a regulator.

*Select all gaps. Leave adequately logged components unselected.*

- [x] GapA routing step that sends some cases down a different path with no log entry.
  - *A regulator could not be shown that comparable cases were treated consistently.*

↓

- [x] GapA retrieval step whose returned context is not captured.
  - *An affected user could not be told what drove the decision about them.*

↓

- [x] GapA model output stored without the inputs that produced it.
  - *The build team cannot replay the decision to figure out why it went wrong.*

↓

- [ ] AdequateInputs, outputs, and routing are all logged and tied to a session ID.
  - *Inputs, outputs, and routing all logged and tied to a session ID, adequate instrumentation.*

- [ ] AdequateThe log is queryable per decision and retained for 90 days.
  - *Queryable and retained for 90 days, adequate retention policy.*

- [x] GapAn aggregate accuracy dashboard with no per-subgroup breakdown.
  - *Harm concentrated in one group stays hidden behind a healthy average.*

---

<!-- S13 -->

*Teaching · Review routing · 10 min*

### Routing decisions to people by stakes, not by volume

Decision logging gave you a record of what each automated decision was based on: the inputs it saw, the path it took, and the output it produced. A logged decision can be explained after the fact, but a log alone does not decide which decisions a person should weigh in on before they take effect. A log explains decisions after the fact. A routing rule stops the wrong ones from taking effect at all. You will work out which decisions warrant a human review step and what that reviewer must see on the screen to make the call quickly. The log you have already built is the raw material for that view, so this is a matter of deciding what to surface from it and when, rather than instrumenting the system again from the start.

#### What sets the stakes of a decision

Think of human review as a budget: you have a finite amount of reviewer attention, and you must focus it on the highest-stakes items. The following variables work together to set the stakes of a decision.

- **Reversibility** is how easily a wrong decision can be undone.
- **The cost of a wrong decision** is what the mistake causes if it goes through uncorrected. These two set the stakes of the decision: a choice that is hard to reverse and expensive when wrong is high stakes, regardless of how the system arrives at it.
- **Confidence** is the third variable that sits on top of the other two. It is the score the system produces about its own output, and it is useful only to the degree it is calibrated, because a model can be confidently wrong. Confidence does not change the stakes of a decision; it estimates how likely this output is to be wrong, which tells you how much of your volume should be routed to a person for review.

Combine these variables into one rule: route decisions to a person when they are low-confidence and either irreversible or high-cost; let confident, reversible, low-cost decisions through. A confident, easily reversed, low-cost decision can usually run without a human. A low-confidence, irreversible, high-cost decision almost always needs human review.

The decisions that consume your review budget are the ones where these variables disagree. A case can be high cost but easily reversed, or low confidence on something trivial to undo. When they conflict, give greater weight to cost and reversibility, because they determine the consequences of a mistake. Let confidence decide how much of that high-stakes volume you can safely let through unreviewed. Routing on confidence carries one assumption worth identifying: the confidence signal must be calibrated for the rule to hold, and confirming that calibration is a task of its own.

#### Where the human sits is a tradeoff between safety and speed

Once a decision is routed to a person, you choose where they sit in the flow. Involving a human earlier is safer and slower.

| Placement | What it gives you | What it costs |
| --- | --- | --- |
| **Pre-action approval** | The action cannot take effect until a person approves it, so nothing irreversible happens unreviewed. | It adds latency to every routed decision and a person must be available, so it does not scale to high volume. |
| **Post-action audit** | The action runs immediately and a person reviews it afterward, so throughput stays high. | A wrong action has already taken effect by the time it is caught, so it only suits reversible, lower-cost decisions. |
| **Sampled review** | A fraction of decisions are reviewed to monitor quality without slowing the overall process. | A bad decision can slip through unsampled, it monitors the system rather than guarding individual outcomes. |

#### What the reviewer sees decides whether review is accurate

A reviewer who cannot see why a decision landed in their queue may approve without reviewing with the judgement it needed. Ensure your reviewers have three things: the inputs that drove the decision, the model's output, and the reason it was flagged. Without this reason, they cannot tell the difference between an edge case and routine traffic. Without the inputs, they cannot tell if the output is correct. What you put in front of the reviewer determines whether the review is accurate.

Anthropic's research on agent autonomy found that requiring sign-off on every action adds friction without meaningful safety gain. A better approach is to have a person monitor what is happening and step in when needed. One Anthropic pattern in agent workflows is to reduce per-step approvals and move review to higher-value checkpoints such as plan review or exception handling, to avoid consent fatigue; the exact review design depends on the risk of the workflow. Without this discernment, consent fatigue can happen. Consent fatigue is when a system asks for approval dozens of times in a row, and reviewers start clicking through and approving items without reading or providing the quality of review needed. That pattern is what led to plan-level review in Claude Code, where a person approves the plan rather than each step. Verify current framing against anthropic.com/research/measuring-agent-autonomy and anthropic.com/research/trustworthy-agents at publish time.

#### Diligence: the competency behind human review

Diligence is one of the four AI Fluency competencies: ensuring responsible AI collaboration. Applied to deployment, it means maintaining explicit human accountability checkpoints, recognizing when automation pressure is eroding oversight, and auditing workflows for gaps where AI acts without review, especially as automation scales.

For agent workflows, the routing rule becomes a checkpoint pattern: a gate that pauses execution for human review based on that task's risk and reversibility. Place a gate before any irreversible or high-stakes action an agent would otherwise take autonomously, and sample lower-stakes actions instead of gating each one. This is the same gate vocabulary that multi-agent design depends on.

> **Cost · Complexity · Risk**
> 
> **Cost:** Pre-action review adds latency to every routed decision and needs reviewer time, which is a recurring operating cost.
>  **Complexity:** Routing logic, a reviewer interface that shows inputs and flag reasons, and three placement paths are more complex to build than a single review queue.
>  **Risk:** Routing by volume rather than stakes either overwhelms reviewers and risks review quality degradation, or allows a high-stakes, irreversible action with no gate at all.

---

<!-- S14 -->

*Watch Out · Review routing · 3 min*

### When routing everything to review makes review meaningless

> **Setup hook**
> 
> Deciding which decisions count as high stakes takes judgment, and sending everything to review removes that crucial step. It might feel like the conservative default: it is easy to defend to a compliance reviewer or an auditor, and it requires no call about where the stakes sit. Routing everything feels like the safe answer precisely because it spares you from drawing the line.

#### A short transcript of a handoff that was sloppily reviewed

A reviewer's queue is rarely seen until it fails. The pattern below shows what happens when a system routes every output to a person and gives that person nothing to review against. Two separate things go wrong at once, and the dialogue surfaces both: the volume is more than anyone can read, and each item arrives stripped of the context that would let the reviewer judge it.

**Reviewer:** *There are four hundred items in my queue today. Same as yesterday.*

**Lead:** *Are you reading the inputs on each one?*

**Reviewer:** *There's no way. I get the output and an approve button, that's it. I don't even see the inputs, or why this one landed with me. After the first hour I have to just hit approve to keep up with the pace.*

The design sent all outputs for review and gave the reviewer the output alone, with no inputs and no flag reason. The volume made careful review impossible, and the missing context made it pointless, so review collapsed into approval. A high-stakes decision in that queue got the same routine approval as a trivial one.

> **Why this broke**
> 
> Two independent failures stacked here, and either one alone is enough to cause review to become sloppy.
>  **The first is volume.** When the number of items routed to a person exceeds what they can read in the time they have, oversight that covers everything reviews nothing, because the reviewer disengages to keep up. The fix is the routing rule: send decisions to a person by stakes, using confidence, reversibility, and cost, so the queue holds only the decisions that warrant attention rather than all of them.
>  **The second is missing context.** A reviewer who sees only the output and an approve button has nothing to check the output against, so even a short queue is hard to accurately judge. The fix is to shift what sits in the reviewer's view: surface the inputs the decision was based on and the reason the item was flagged, so the reviewer can see what they are being asked to weigh.
>  If you only fix one of these failures, it's still possible for the review to fail. A small queue with no context and a well-built reviewer view drowning under volume both fail.

---

<!-- S15 -->

*Checkpoint · Review routing · 3 min*

### Build the review-routing rule

**Try it now.** A routing rule has three controls: a confidence threshold, the cost of a wrong answer, and a reversibility setting. The goal is to route high-stakes, low-confidence decisions to a person before they take effect, while keeping the review queue under the reviewer ceiling. Choose the rule that meets both targets at once.

- **A.** Route everything below a high confidence threshold to review, regardless of stakes.
- ✅ **B.** Route decisions that are low-confidence AND either irreversible or high-cost to pre-action review; let confident, reversible, low-cost decisions through.
- **C.** Route by confidence alone, set low enough to keep the queue small.
- **D.** Send every decision to review to be safe.

**Answer: B**

*(Free-response exercise: Now complete this step: In 1–2 sentences, name the single deciding control, what makes a low-confidence case still route to a person even when confidence is within tolerance?)*

> **Model answer**
> 
> Reversibility and the cost of a wrong answer are the deciding controls, not confidence. Confidence filters the volume you route, but it does not change the stakes of the decision. A case can be confident and still route to a human if it is irreversible or high-cost enough to warrant it.

---

<!-- S16 -->

*Teaching · Compliance · 10 min*

### Turning each compliance obligation into a control with evidence

The compliance layer of the integration model used the governing obligation as a pre-filter: HIPAA, GDPR, FedRAMP, attorney-client privilege, or a data-residency policy each ruled delivery routes and entry points in or out before cost or engineering preference entered the conversation. That work gets you to an entry point and a route that survives the obligation, but the next step is narrower and harder. Each surviving obligation must now become a control with a named owner. A reviewer does not treat a compliant entry point alone as proof that the rule is being followed. They also ask who owns the control and what evidence shows its holding in practice.

#### A regulation states an outcome, but you supply the control and the proof it is operating

Frameworks such as GDPR, HIPAA, and FedRAMP state outcomes, not implementations. They say what must be true: that protected data must be handled a certain way, that access must be controlled, and that processing must happen in an authorized environment, but they leave the technical control to you. Each obligation becomes three things you own: a specific technical control that achieves the outcome, an owner accountable for it, and an evidence artifact that shows it is live. Always remember to include the evidence artifact; this is what the reviewer will check and is the most often missed.

#### Mapping obligations to controls, owners, and evidence

**▸ Mapping obligations to controls, owners, and evidence**

| Obligation (framework) | Technical control | Evidence a reviewer accepts | Owner |
| --- | --- | --- | --- |
| **Protected health data handled under an agreement (HIPAA)** | Use only a HIPAA-ready Enterprise plan or first-party API configuration covered by a signed Business Associate Agreement, with HIPAA compliance enabled and only eligible features in scope. | The signed BAA and the admin setting showing HIPAA compliance enabled, plus the eligible-feature list. | Security lead |
| **US government workload at the required impact level (FedRAMP)** | Deliver through an Anthropic-documented authorized route that meets the required impact level, not a non-authorized entry point. | The authorization record for the chosen route and confirmation that the workload runs exclusively on it. | Platform owner |
| **Data handled and stored in an approved region (data residency)** | Configure supported regional processing and storage for the approved region, and validate whether logs, caches, monitoring, and retention paths remain within the approved boundary. | The residency configuration and a data-flow record showing where every copy lives. | Data owner |
| **Decisions reconstructable on demand (transparency, cross-framework)** | The decision logging built in the fairness cluster, retained and queryable for the required period. | A sample reconstruction of one decision from the live log. | Architect |

> **Training use vs retention, two distinct claims**
> 
> Do not collapse training use and retention into the same claim: data may be excluded from model training by default while still being retained or monitored for logging, abuse prevention, legal compliance, or configured audit purposes.

#### The evidence artifact is what makes the handoff effective

The constraint-elimination reasoning from the integration work carries forward here. Back then you eliminated delivery routes that could not survive a constraint. Now you record, for each obligation, the control that satisfies it and the artifact that proves it.

A security and legal reviewer accepts proof that a control is live: a signed agreement, a configuration screen, an authorization record, or a returned log query. What they do not accept is a design document that identifies a control with no owner and no evidence; a control no one can demonstrate is indistinguishable from one that is not running.

> **Cost · Complexity · Risk**
> 
> **Cost:** Producing and maintaining evidence for every obligation is ongoing work. Configurations drift and artifacts go stale, so the register is revalidated on a regular cadence.
>  **Complexity:** A control, an owner, and a living evidence artifact per obligation is more governance than an entry point choice, and it spans security, legal, and platform owners who each must agree on who holds what.
>  **Risk:** A control specified with no owner and no evidence is invisible at the audit. It can stop operating with no one accountable, and the gap surfaces in review rather than in design, which is the most expensive place to find it.

---

<!-- S17 -->

*Watch Out · Compliance · 3 min*

### When passing entry point selection feels like finishing compliance

> **Setup hook**
> 
> Passing the constraint pre-filter and being able to prove compliance are two different things. The pre-filter gives you a clean signal. Choosing a delivery route that survives HIPAA, GDPR, or FedRAMP produces an immediate, visible result: the route is allowed, the entry point is cleared, the design can move. Proving that each obligation is being met produces nothing visible at design time, because the proof is an artifact you must build, attach to an owner, and keep alive as configurations change. That gap is easy to miss, because the moment that feels like a finish line and the moment a reviewer checks are often months apart.

#### A deployment that chose the right route but produces no proof

A team selected a compliant delivery route for a regulated workload and treated compliance as settled. They had mapped obligations to controls once, at design time, in a document. No owner was attached to the controls, and no logging was wired to show any control was operating.

The data residency obligation is where the failure concentrated. The control was correct on paper: processing pinned to the approved region. However, months later a logging configuration changed and started writing request metadata to a store in a second region. Nothing identified the change, because no one owned residency control and no artifact tracked where data was landing. The gap surfaced at the audit, not at design, when a reviewer asked for evidence that data stayed in-region and the team had a design document instead of a data-flow record.

> **Why this broke**
> 
> Surviving the pre-filter was mistaken for establishing compliance. A compliant route is a prerequisite, not proof. Each obligation needs a control, a named owner, and a living evidence artifact that is revalidated as the deployment changes. The residency control in this story was real at design time and silently false in production, and nothing caught the difference because no artifact was watching it.

---

<!-- S18 -->

*Checkpoint · Compliance · 3 min*

### Justify the control choice

**Try it now.** You are given one compliance obligation for a regulated deployment. Pick the technical control that evidences it, then select the single load-bearing reason a security and legal reviewer would accept that control as proof. You pass only when both land: the control must fit the obligation, and you must name why it counts as evidence a reviewer can inspect.

**Obligation:** Protected health data must be handled under a formal agreement (HIPAA).

- ✅ **A.** A HIPAA-ready plan or first-party API under a signed BAA, because the signed agreement plus the enabled configuration is the artifact a reviewer can inspect as proof.
- **B.** A HIPAA-ready plan under a signed BAA, because the model is instructed to handle health data carefully.
- **C.** A model-based content filter on health terms, because it catches sensitive data at runtime.

**Answer: A**

---

<!-- S19 -->

*Cumulative · Module · 8 min*

### Assemble a responsible deployment

**Try it now.** You are handed a self-contained brief, and you make five sequenced decisions that build a responsible deployment. The decisions run in order because each one sets the conditions for the next. A weak early choice narrows what the later ones can do. If you leave a domain rule in trained behavior in decision one, there is no layer downstream that can put it back.

You built each layer on its own across the module. Here is the stack you are assembling, in order:

- Trained behavior shapes baseline safety; your application policy defines domain-specific rules; the runtime controls below enforce those rules in operation.
- Runtime screening and authorization sit on the request path and stop disallowed content and unpermitted actions.
- Fairness and transparency controls address unequal outcomes at their source and ensure each decision can be reconstructed. They depend on effective logging.
- Human-review routing sends the decisions a model should not finalize alone to a person, by stakes. It depends on the same logging.
- The control register ties each obligation to a control, an owner, and an evidence artifact.

> **The brief**
> 
> A public-sector benefits assistant helps an agency determine program eligibility, recommending whether to approve, deny, or refer. The brief gives you what the decisions need and nothing more:
>  **Framework:** FedRAMP at the agency's required impact level, plus the agency's rule that a denied applicant gets the specific reason.
>  **High-stakes, low-confidence case:** An applicant near the eligibility threshold with incomplete documentation, where a wrong denial removes someone's benefits.
>  **Skew-prone output:** The recommendation and the reason attached to a denial.
>  **Data:** Applicant-submitted fields, agency records retrieved at decision time, and any derived features.

*(Free-response exercise: 1. Set the boundary between trained behavior and your application layer.)*

*(Free-response exercise: 2. Place the runtime controls.)*

*(Free-response exercise: 3. Specify the fairness and transparency controls.)*

*(Free-response exercise: 4. Define the human-review routing.)*

*(Free-response exercise: 5. Build the control register.)*

> **Model answer**
> 
> **1. Set the boundary between trained behavior and your application layer.** Trained behavior refuses broad harm classes but never saw this program's eligibility rules, so those belong to the application layer. Leave them in trained behavior and no control downstream can reach them.
>  **2. Place the runtime controls.** Position input screening, output screening, and tool-call authorization, choose model-based or deterministic at each, and set the failure direction. Fail closed, because a screen that fails open lets an unscreened denial reach an applicant.
>  **3. Specify the fairness and transparency controls.** Name which of the four injection points (corpus, prompt framing, examples, routing) could skew this outcome, and build the decision logging once, since the affected applicant, the regulator, the build team, and the control register all draw on it.
>  **4. Define the human-review routing.** Route by confidence, reversibility, and cost of a wrong answer, and pick a placement: pre-action approval, post-action audit, or sampled review. Send a low-confidence, hard-to-reverse denial to pre-action approval. Key the rule to stakes, not volume, or a quiet queue waves a high-stakes denial through.
>  **5. Build the control register.** Map each FedRAMP obligation to a control, an owner, and the evidence a reviewer accepts. A control with no evidence artifact is a claim you cannot prove operated.

---

<!-- GLOSSARY -->

*Reference · Wrap-up*

### Glossary

The key terms used across this module, in alphabetical order. Click a term to expand its definition.

**▸ BAA (Business Associate Agreement)**

A contract under HIPAA that permits a vendor to process protected health data on a covered entity's behalf, defining each party's safeguards and liabilities. Without it, handling that data through the vendor is non-compliant regardless of the technical controls.

**▸ Consent fatigue**

The breakdown of oversight when a reviewer is asked to approve too many actions, so they approve almost everything without real review. It is the failure mode of routing every decision to a human. Verify Anthropic's current framing against anthropic.com.

**▸ Constitution**

The written document Anthropic uses during training to shape Claude's values and behavior, stating a priority order of broadly safe, ethical, compliant with guidelines, and genuinely helpful. It shapes the model's trained behavior but does not encode any one deployment's domain policy. Verify the current version against anthropic.com.

**▸ Control register**

A table that maps each compliance obligation to its technical control, an accountable owner, and an evidence artifact, so a regulated deployment can be audited as a register rather than asserted as a narrative.

**▸ Data residency**

The requirement that data is processed and stored within a specified geographic region, including copies in logs and caches. It is the control behind many data-sovereignty obligations.

**▸ Decision logging**

Capturing the inputs, retrieved context, model output, and routing for each decision, keyed so one decision can be replayed and explained later. It is the same observability instrumentation pointed at the question of why a specific decision happened.

**▸ Evidence artifact**

The concrete proof a security and legal reviewer accepts that a control is live: a signed agreement, a configuration screen, an authorization record, or a returning log query. A control named in a design document with no artifact is a claim, not proof.

**▸ Fail open vs fail closed**

How a guardrail behaves when it itself errors. Fail open passes traffic through unscreened, while fail closed blocks until the control is healthy. For safety controls, failing closed is the deliberate choice, because a control that silently passes traffic offers no protection.

**▸ FedRAMP**

The FedRAMP classification (low, moderate, or high) that sets the security controls a cloud service must meet to handle US government workloads of a given sensitivity. The required level is set by the workload, and the delivery route must be authorized at or above it.

**▸ GDPR**

The EU's data protection law regarding how organizations collect, process, store, and transfer the personal data of people in the EU and EEA. It grants individuals rights over their data and requires a lawful basis for processing, data minimization, and protection.

**▸ HIPAA**

A US federal law setting standards for protecting individuals' health information. It governs how protected health information (PHI) is used, disclosed, and safeguarded by covered entities and their business associates. When a vendor processes PHI on a covered entity's behalf, HIPAA requires a Business Associate Agreement (BAA) defining each party's safeguards and liabilities. In this module it drives the requirement to deliver through a HIPAA-ready plan or first-party API under a signed BAA.

**▸ Human-in-the-loop routing**

A rule that sends decisions to a person based on confidence, reversibility, and the cost of a wrong answer, rather than by volume, with the reviewer placed pre-action, post-action, or in a sample.

**▸ Injection point (fairness)**

A specific place where unequal outcomes can enter a system: the retrieval corpus, the prompt framing, the chosen examples, or the downstream routing. Naming them makes fairness an architecture property you can instrument rather than a model attribute you assume.

**▸ Input screening**

A check that runs before the model call to decide whether a request should reach the model, using a model-based classifier for fuzzy intent like jailbreaks or a deterministic rule for crisp patterns.

**▸ Judge model**

A model used to score or classify another model's output, for qualities like toxicity or policy compliance that a deterministic rule cannot reliably encode. It can be evaded, which is why it is chained with deterministic checks.

**▸ Output screening**

A check that runs before the response reaches the user, judging the generated content with a model for qualities like toxicity or a validator for known strings and schema violations.

**▸ Tool-call authorization**

A check before any action with a side effect that decides whether this caller may perform this action in this context. It should be deterministic, an allowlist plus identity and scope, so the decision is provable and auditable.

**▸ Training-time alignment vs inference-time control**

Training-time alignment is the safe behavior baked into the model for every user. Inference-time control is the screening and authorization you add at request time to enforce rules specific to your deployment. Conflating the two leaves deployment-specific rules unenforced.

---

<!-- S20 -->

*Recap · Module · 3 min*

### Five things that hold across everything here

- **01 Safety is a stack of layers, not a setting** — Training reduces broad harm for every request but never saw your partner's domain policy, data rules, or authorization model, so draw the boundary explicitly and identify what each layer covers. The dangerous failure is silent: assuming Claude enforces a rule that doesn't live in a layer.

- **02 A guarded path has three control points and a chosen failure direction** — Input screening, output screening, and tool-call authorization answer different questions, so only one filter at the end does not cover the other two. Let control errors fail closed for decisions where a wrong pass causes harm, because a guardrail that silently passes traffic gives you the appearance of protection without any of the function.

- **03 Fairness and transparency are instrumented, not assumed** — Unequal outcomes arise at points you control, such as the corpus, prompt framing, examples, and routing, so treating fairness as the vendor's responsibility leaves those points unmonitored. Log every decision so users, regulators, and your team can reconstruct it. If you cannot reconstruct an explanation, you cannot reliably provide one.

- **04 Route review by stakes, not by volume** — Confidence, reversibility, and the cost of a wrong answer set which decisions a person should review, so send the high-stakes, low-confidence ones to a human with the inputs and the flag reason and let the rest through. Routing everything floods the queue until reviewers click through without reading.

- **05 A compliant entry point is a prerequisite, and an evidenced control set is the proof** — A regulation states an outcome and leaves you the control, so turn each obligation into a specific control, a named owner, and a living evidence artifact you revalidate over time. A control with no owner and no evidence eventually goes non-operational and fails at the audit, because what a reviewer accepts is proof the control is live, not the control itself.

#### What comes next

The next module shifts from building a responsible deployment to handing it off and stewarding it. You will take the architecture you can now evidence and communicate its tradeoffs to non-technical stakeholders, document it to a standard, and steward it through the discovery-to-hand-off lifecycle. The control register and the layered boundary you built here become the documentation and the baseline that handoff rests on.

#### Sources

- Building with the Claude API (Skilljar Course 4), used for model graders, tool-call mechanics, structured outputs, and the evaluator pattern.
- platform.claude.com/docs and platform.claude.com, used for content moderation, the guardrails guide, streaming refusals, and structured outputs.
- anthropic.com, used for the January 2026 constitution and current safety posture.
- Anthropic Trust Center and Privacy Center, used for HIPAA, FedRAMP, and data-residency posture.
- Architect M1 and M2 storyboards, used to reference rather than re-teach owner assignment, reference architectures, model and context strategy, evals, integration layers, and observability.

---

<!-- CERT -->

**

## Congratulations! You have successfully completed this module.

Module 3 covers the safety frameworks, risk categories, and control design decisions that responsible AI architects apply before and during production deployment.

**A guarded path is not a filter at the end, it is a control at every stage where harm can enter.**

0
 of 0 checkpoints passed

M1

Claude Platform & Solution Design

Model selection, prompt architecture, tool design, and platform-layer tradeoffs.

M2

Enterprise Integration & Production

Deployment patterns, integration architecture, and production reliability.

M3

Responsible AI, Safety & Risk

Safety frameworks, risk identification, and governance practices.

You Are Here

M4

Stakeholder Engagement, Lifecycle & Go-to-Market

Stakeholder communication, lifecycle management, and go-to-market strategy.

Up Next

M5

Team Enablement and Operational Productivity

Team tooling configuration and operational support practices.
