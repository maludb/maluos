# Claude Certified Architect — Module 1: Claude Platform & Solution Design

*Source: Anthropic Partners Skilljar (personal study notes)*

---

<!-- S01 -->

*Teaching · 2 min · Module Introduction*

## Designing solutions with Claude goes beyond just choosing a model.

When designing solutions with Claude, there are four key decisions to make before you begin building.

- **01 What part of the work should Claude own?** — Before you shape anything, you should decide what to hand to Claude, what to leave with existing systems, and what stays with a human.

- **02 What shape is the work?** — Are you augmenting a live call, automating a workflow, or deploying an agent that acts on its own?

- **03 Can you name the reference architecture you're committing to?** — Picking a reference architecture upfront can save you from expensive pivots later.

- **04 Where does your work interact with Claude?** — Selecting the right entry point, model, and context strategy will keep your solution working and cost-conscious.

In this module, you will learn how to make these decisions to translate an ambiguous business problem into a proposed solution and defend your choices against credible alternatives.

### By the end of this module, you'll be able to:

- 1Break down a partner's request into what Claude does, what existing systems do, and what humans do, using the four properties of generative AI as your decision lens.
- 2Choose between an augmented call, a workflow, and an agent by naming what each choice costs.
- 3Pick a reference architecture pattern for the problem shape in front of you and recognize when retrieval is doing a job that live-state should own.
- 4Make defensible model, context-window, and context-strategy decisions, and use evaluations as the gate before any model swap.
- 5Know where each platform entry point fits (Claude.ai, the API, an SDK, Claude Code, or an MCP server) and what customization belongs at each layer.
- 6Distinguish between the Claude entry points a user sees, the build-time interfaces an engineer codes against, and the delivery routes an enterprise procures, as well as identify which are ruled out by governance or regulated-industry constraints before any other tradeoff applies.

> **Who this module is for**
> 
> This module is for the Architect who turns a partner's ambiguous request into a solution someone can build, fund, and defend. You are technical, decisive, and tradeoff-aware. You are not writing the production code in this module, and it does not teach you to. It teaches the decisions that sit above the code: what work Claude should own, what shape that work takes, which reference architecture fits, and what model, context, and entry point choices keep the system accurate and affordable once it is real.

### "The work" in this module

Everything here is built around one sample engagement: taking a business problem from a partner and arriving at a proposed architecture you can stand behind when a credible alternative is on the table. In this scenario, the partners are enterprise buyers in high-stakes, often regulated, settings where a design choice that looked clean in a demo becomes a misroute discovered in an audit three months later. This scenario is presented as a series of decisions, with each decision asking something different from you.

The decisions map onto the following sections:

- **Decomposition** is where you assign each part of the request to Claude, to an existing system, or to a human, using the four properties of generative AI as the lens. Getting this wrong by over-assigning to Claude is the most common and most expensive early mistake.
- **Pattern selection** is where you decide whether the work is an augmented call, a workflow, or an agent. Each choice provides and costs you something, naming the costs is the objective.
- **Reference architectures** are where a known, good blueprint either fits the problem shape or is misapplied. The failure to watch for is retrieval quietly doing a job that the live transactional state should own.
- **Model, context, and entry point** are where you choose a model tier, a context strategy, and a delivery route, and where evaluations become a stage-gate before any model swap. Check if governance and regulated-industry constraints rule-out a route before considering any cost or latency tradeoffs.

Rather than memorizing these as stages, the objective in this module is to recognize which decision is in front of you, as each one rewards a different move: the decision that serves you well in decomposition is different from when you are choosing an entry point. In the cumulative task at the end of this module you will put all this together to assemble full architecture from a new brief.

> **Disclaimer / Notice for Educational Content**
> 
> We built this Architect course Module 1: Claude Platform & Solution Design to help you get real work done with Claude. Treat it as educational content. It doesn't constitute legal, financial, or other professional advice, so adapt what you learn to your own situation. Our products and services evolve quickly, so certain content may contain errors or be outdated; remember to verify on Anthropic’s website or docs. Examples and scenarios used in the course are illustrative and often fictitious. If the course material mentions a company or product, it doesn't mean Anthropic endorses them, they endorse Anthropic, or that we're affiliated. Also note your use of Anthropic products and services is covered by our terms, policies and documentation; if anything in this course conflicts with them, they control.

---

<!-- S02 -->

*Teaching · 12 min · How Claude Behaves*

## The four properties architects design around

Before you decide what Claude should do in a solution, you need a clear understanding of how Claude behaves. Four properties of the model shape every following design decision. None of these properties are a flaw to be fixed, each is a force you design around – like how a structural engineer designs around the properties of their building materials.

Consider this screen as initial groundwork, you are not being asked to make any design decisions at this point. The goal is to recognize the four properties by name and understand each property's design consequences to prepare you to make informed choices in judgment exercises later in the module.

### The four properties and their design consequences

For each property below, the same characteristics that make Claude capable in one situation are the same that makes it fail in another. Read each row as a capability paired with its matching limitation, and the mitigation that an architect reaches for.

Select each property to see its paired capability, limitation, and mitigation.

#### Tab: Next-token prediction

**Capability:** Tasks built on common patterns: summarizing, reformatting, and explaining well-established concepts.

**Limitation:** Anything requiring precision on specifics. Claude can produce text that appears accurate but isn't. This risk concentrates around names, dates, citations, and statistics.

**Mitigation:** Use citations, uncertainty signaling, and generator-verifier loops. Route specific factual lookups through tool calls or authoritative sources rather than relying solely on the model's output.

#### Tab: Knowledge

**Capability:** Topics in the model's training data that are common, recent, and consistently included where the model can answer reliably from what it learned.

**Limitation:** Topics that are rare, niche, contested, or frequently changing. The model may present stale or incomplete information with the same confident tone it uses for established facts.

**Mitigation:** Use web search, retrieval (RAG), tool use, or MCP servers to make an external system the source of truth instead of the model. Instead of checking the model's parametric knowledge, the authoritative answer comes from the retrieved source. When freshness or authority matters, re-introduce the data yourself rather than relying on what was provided in the model's training data.

#### Tab: Working memory

**Capability:** Anything that fits in the active context window.

**Limitation:** The context window is a hard edge: once content falls outside the window, the model has no access to it at all. Two different errors happen at the edge, but they can be easy to conflate. One is an oversized request, meaning a prompt or conversation that is already too large to send. When an oversized request is sent it is rejected before generation. If the request exceeds the model's token limit, the API returns a `400 invalid_request_error` with a message indicating the prompt is too long. If the raw request body exceeds the API's byte limit, the API returns a `413 request_too_large` error with a message indicating the request exceeds the maximum allowed number of bytes. The other error occurs when a prompt fits, but its generation runs into the window ceiling and stops early instead; on current models the response comes back with a `model_context_window_exceeded` stop reason and truncated output. To avoid hitting the limit, you can check the `usage` field on every response and the token-counting API before you hit send.

**Mitigation:** Use progressive context loading, chunking, and front-loading of critical information. For extended work, projects can help manage what stays in scope. Get into the practice of summarizing across turns when context is getting long.

#### Tab: Steerability

**Capability:** Short, concrete, and verifiable instructions with defined formats, explicit length limits, clear roles.

**Limitation:** Abstract or ambiguous instructions, long reasoning chains, and tasks requiring precise numerical or logical computation. For high-stakes numerical accuracy, deterministic computation or tool execution should own the answer. The model may follow the letter of an instruction while drifting from the intent.

**Mitigation:** Use system prompts, structured outputs, and code execution for anything requiring logical precision. When intent and literal instruction might diverge, restate the goal explicitly alongside the instruction.

### From property to design consequence

We will revisit each of these properties in a later part of this course. Map each property to their design consequence now so the connection is in place before you need it:

- **Non-determinism.** The same input can produce different outputs across runs. This is why evaluation frameworks exist: you cannot certify behavior you only observed once. (Feeds the evaluation work in Module 2.)
- **Context as a finite resource.** The context window is a hard edge with a fixed token budget. What you put in it, in what order, and what you leave out are design decisions that affect both what the model can work with and what it costs to run. (Feeds model and context strategy, later in this module.)
- **Confidence is not validity.** Claude can produce a wrong answer in the same fluent, assured tone it uses for a right one. This is why human-in-the-loop placement and verification are architectural choices, not afterthoughts. (Feeds the responsible-deployment work in Module 3.)
- **Knowledge and capability boundaries.** The model is reliable with topics that are common, recent, and consistent in its training data, and unreliable with topics that are rare, private, or fast-changing. For unreliable topics, web search, retrieval, tools, and MCP can be used to make an external system the source of truth instead of the model. (Feeds reference architectures and RAG, later in this module.)

> **Scenario: A failure that began with a misread property**
> 
> An architect saw a demo run cleanly five times in a row and concluded the behavior was deterministic. On that basis the team shipped a financial reconciliation pipeline that treated each model output as a fixed, repeatable result and built no checks around it. In the second week of production the outputs drifted: the same statement, re-processed, produced a different categorization. This discrepancy was discovered by chance only when an analyst happened to re-run a batch. Nothing had changed in the input, but different outputs were produced because the model is a non-deterministic system and the architecture had been built as though it was deterministic.
>  The lesson is not that the model is unreliable, it's that a demo is not evidence of determinism and that the four properties are present whether your architecture acknowledges them or not.

Cost · Complexity · Risk

**Cost:** Designing without considering these properties is the most expensive mistake an architect can make, because the cost lands after launch, when rework is most expensive and rebuilding trust is the hardest.

**Complexity:** Naming the four properties up front keeps later design conversations precise. You can acknowledge "this is a knowledge-boundary problem" instead of debating if the model is "good enough."

**Risk:** The properties do not announce themselves. A system that does not design around these properties won't produce an error; it drifts quietly and the gap results in variable outputs that may be found in an audit or by an angry user, not by the system itself.

---

<!-- S03 -->

*Teaching · 12 min · Platform Map & Primitives*

## Entry points, build-time interfaces, delivery routes

Throughout this course you will choose how a user reaches Claude, but before that, you need a consistent set of vocabulary. Three terms are often used interchangeably, but they sit at different layers of the architecture. This screen teaches each of these terms. Choosing between them comes later, once the rest of the design is in place.

### Three layers, three distinct decisions

These three layers are not alternatives to one another. Every deployment involves all three and confusing them is the most common source of muddled architecture conversations.

- **Entry Points** — What a person or system directly interacts with. Entry Points are the wrappers that decide who can talk to Claude and how.
 **Examples:** Claude.ai (web, mobile, desktop), Claude Code, a custom application built on the API.

- **Build-time interfaces** — How an engineer programs against Claude, the layer the partner's code is written to.
 **Examples:** The direct API, the SDKs, MCP, the Agent SDK.

- **Delivery routes** — Where API traffic terminates. Delivery routes determine whose infrastructure the request runs on.
 **Examples:** Anthropic directly, AWS Bedrock, GCP Vertex AI, Microsoft Foundry.

### Why keeping the layers distinct matters

An entry point is chosen for the user and the work. A build-time interface is chosen for the engineering team and the integration. A delivery route is chosen for the partner's cloud commitments and compliance posture. These are three different conversations with three different stakeholders, and a decision in one layer rarely dictates the others.

For now, focus on learning their names and their distinction. Selecting among them under real constraints will be taught later, once you have a model, a pattern, and an architecture to fit them to.

> **A failure that came from collapsing the layers**
> 
> A proposal for a retail banking workflow solution put Claude Code, an engineering entry point, in front of a non-engineering audience because, in the author's words, "it's all Claude." It is all Claude, in the sense that the same model sits underneath every entry point. But the entry point is the wrapper, and Claude Code was built for developers running a terminal, not for bank branch staff following a workflow. Treating the three layers as one erased the distinction that should have ruled the choice out immediately.

Cost · Complexity · Risk

**Cost:** Every entry point carries its own integration cost. Picking the wrong layer because the vocabulary was unclear can lead to paying for the wrong solution, then paying again to replace it.

**Complexity:** When the three layers are named and discussed precisely, a design review can isolate exactly which decision is contested. When they are blurred, the review argues in circles.

**Risk:** An entry point chosen before the user is named is a common and avoidable architecture error that is often traceable to collapsing these three distinct layers into one concept.

---

<!-- S04 -->

*Checkpoint · 4 min · Platform Map & Primitives*

## Place each piece in its layer

Click a platform piece to select it, then click the right layer bucket to place it. Click a placed chip to return it to the pool. All 8 items must be placed before submitting.

**Sorting exercise (answer key):**
- **Entry Points:**
  - claude.ai
  - Claude Desktop
  - Claude Code
- **Build-time Interfaces:**
  - Direct API
  - SDKs
  - MCP
  - Agent SDK
- **Delivery Routes:**
  - Bedrock / Vertex / Foundry

---

<!-- S05 -->

*Teaching · 16 min · Platform Map & Primitives*

## The parts an architect assembles solutions from

Every pattern and architecture in this course is an assembly of a small set of primitives. Name them once, here, so the later lessons become combinations of parts you already recognize.

This screen names the seven primitives, their job, and a one-line statement to teach you what each one is for. You are not choosing among them yet; you are learning what each one is for.

### Seven primitives, seven jobs

Read each primitive as a single job. Rather than going deep on any one primitive, keep a wholistic view of all seven for now. A key skill as an architect is composing these primitives to develop a solution.

Click each card to flip it: the front names the primitive and its one-word job, the back gives the one-line definition.

- **Tools** *(Act)* — What lets the model take an action or fetch a result from your code, a function the model can call.

- **MCP** *(Connect)* — A protocol for exposing a set of tools so multiple Claude clients can reach the same entry points.

- **Subagents** *(Isolate / parallelize)* — Hand a scoped sub-task to a separate context so work runs in isolation or in parallel.

- **Hooks** *(Guarantee)* — Deterministic code that fires on defined events to enforce a rule the model cannot skip.

- **Skills** *(Package a procedure)* — A versioned, reusable unit (instructions plus optional scripts) that packages a repeatable procedure.

- **Agent Teams** *(Coordinate peers)* — Multiple agents working as coordinated peers, each owning part of a larger goal.

- **Dynamic Workflows** *(Compose at runtime)* — Assemble the steps of a workflow at runtime rather than fixing them in advance.

Agent Teams (coordinated peer agents) and Dynamic Workflows (runtime composition) extend older vocabulary of single agents and fixed workflows. You will see them named in current practitioner conversations even though many existing systems predate them.

### Why inventory them now

The patterns taught later in this module, the augmented call, the workflow, the agent, are not abstract categories. Each pattern is a particular assembly of the seven primitives. A workflow is steps wired in your code, often using tools. An agent is the model choosing its own sequence of tool calls. A multi-agent system is an orchestrator delegating to subagents. When you reach those lessons, you will be composing primitives you have already named, not meeting them for the first time.

> **Scenario: A failure that came from missing shared vocabulary**
> 
> In an architecture review, someone said "we'll use an agent." Five people in the room heard five different things: one heard a single tool-using model, one heard a multi-step workflow, one heard a team of subagents, one heard Claude Code, and one heard a chatbot. The design conversation stalled for twenty minutes before anyone realized they were describing different architectures with the same word. By establishing a common understanding of the primitive vocabulary, the team can operate with clarity and efficiency.

Cost · Complexity · Risk

**Cost:** Reaching for a heavier primitive than the job requires is paid for in latency, tokens, and operational surface area, every request. E.g., Using a team of agents when a single tool call would suffice.

**Complexity:** Each primitive added to a design is a part to build, observe, and govern. The discipline is to use the fewest primitives necessary to meet the requirement.

**Risk:** Without a shared vocabulary, teams cannot effectively communicate because they do not agree on what the parts are.

---

<!-- S06 -->

*Checkpoint · 4 min · Platform Map & Primitives*

## Match the primitive to the job

Match each item on the left to its match on the right across the three sets. This is the readiness check before the design half of the module. Answer all three sets, then submit.

### Set 1 of 3: Behavior properties to their design consequence

Match each property to the design consequence it creates.

- Non-determinism → **Why evaluation frameworks exist**

- Knowledge boundary → **Why retrieval and tools exist**

- Context as a finite resource → **Why context strategy is a design decision**

- Confidence is not correctness → **Why human-in-the-loop placement matters**

### Set 2 of 3: Platform pieces to their layer

Match each platform piece to the layer it sits in.

- Claude Code → **Entry point**

- MCP → **Build-time interface**

- Bedrock → **Delivery route**

### Set 3 of 3: Primitives to their job

Match each primitive to the one-word job it does.

- Tools → **Act**

- Subagents → **Isolate / parallelize**

- Hooks → **Guarantee**

- Skills → **Package a procedure**

**Course answer data:**
**ANSWERS:**
- **S06g1.** C
- **S06g2.** B
- **S06g3.** D
**RATIONALE:**
- **S06g1.** C: Correct. Working memory is the hard-edge property, things work until they don't, and the transition is abrupt. Progressive context loading is the mitigation. Generator-verifier loops address next-token prediction; RAG/tool calls address the knowledge edge; restating the goal addresses steerability. · wrong: Incorrect. Working memory is the context-window property, the model has no access to anything outside the window. The mitigation is progressive context loading, not verification loops (next-token) or tool calls (knowledge) or goal restatement (steerability).
- **S06g2.** B: Correct. MCP is a build-time interface, the programmatic layer engineers code against. It is not a product users open (entry point) and it does not determine where API traffic terminates (delivery route). · wrong: Incorrect. MCP is a build-time interface, engineers write against it, it's not a product end users open, and it doesn't determine where API traffic terminates.
- **S06g3.** D: Correct. MCP's job is multi-client reuse: build the server once, connect it everywhere. When the same tool entry point must be reachable from more than one Claude client, MCP is the primitive. Hooks are lifecycle gates; subagents are isolated task agents; Skills are versioned procedures. · wrong: Incorrect. When the same tool must be reachable from multiple Claude clients, the primitive is MCP, build once, connect everywhere. Hooks are lifecycle gates, subagents are isolated task agents, and Skills are versioned procedures.

---

<!-- S07 -->

*Teaching · 9 min · Decomposition*

## Where Claude fits (Claude / systems / humans)

When you're architecting a solution for a partner, you're already making three kinds of decisions: what the ask is, which systems you have available to address it, and where human judgment needs to be involved. This module adds a fourth decision: determining where Claude can help.

That fourth decision is one architects get wrong because they lack deep understanding of Claude's predictable strengths and failure modes. The goal of this module is to give you a concrete decision framework to determine where "Claude can help" with specificity.

### Who does what? Every solution has three owners: assigning them early sets you up for success

Every solution you architect with Claude lands in one of three buckets:

| Owner | What belongs here |
| --- | --- |
| What Claude does | The work that benefits from language understanding, summarization, planning, drafting, or tool-mediated action. |
| What existing systems do | Anything your partner has already paid to make reliable: the order-status service, the policy engine, the rules table, the database of record. |
| What humans do | The judgment calls, the exception paths, the approvals, the moments where being right matters more than being fast. |

Architects sometimes collapse all three into "what Claude does", but over-assigning tasks to Claude almost always makes the process more expensive, slower, and harder. The key is knowing what Claude does best and what it should be responsible for in your solution.

### Delegation: deciding what Claude is trusted to own

Decomposition produces a delegation map. For each part of the request you decide not just whether Claude can do it, but whether Claude should own it: AI-appropriate work, human-retained work, or collaborative work where Claude drafts and a person decides. Justify each assignment through:

- **Reversibility:** Can a wrong call be undone?
- **Stakes:** What does a wrong call cost?
- **Accountability:** Who must answer for it?

This screen will teach you the discipline of delegation, the first of the four AI Fluency competencies. The four behavior properties that tell you what Claude can be trusted with were taught in the foundations section; here you will apply them.

> **Scenario: Decomposing a partner request, assigning each step to the right owner**
> 
> A partner asks for a "claims triage assistant that reads a claim, decides priority, looks up policy coverage, and emails the adjuster." An architect's first instinct might be to put all four steps in the "What Claude does" bucket, but the four-properties lens stops this from happening:
>  **"Read the claim."** This is squarely in Claude's capability zone. Reading and interpreting a claim is pattern-rich language work, and if the output schema is constrained, both next-token prediction and steerability are working in your favor. This is work that Claude does.
>  **"Decide priority."** This step may appear like a language task, but it isn't. Priority is a deterministic rule your partner already defines and maintains. What counts as priority in the partner's organization lives in a rule engine, not in Claude's training data. Routing this to Claude introduces an unnecessary knowledge limitation. Instead, Claude calls the rule engine and the existing system does the work to decide priority.
>  **"Look up policy coverage."** This runs into the same problem as priority, but with higher stakes. Policies change and coverage tables get updated, and the model has no reliable way to know when the version it learned during training stopped being current. The answer must come from the system that holds the live coverage data, retrieved through tool use or an MCP server.
>  **"Email the adjuster."** This step needs to be split up. Drafting the message is language work and is something for Claude to do. Sending the message belongs to the email system. A human should review and approve anything above a value threshold, because if Claude decides on its own, its working-memory and steerability limitations both become risks.
>  Decomposition should be driven by answering the question "where do the four properties argue for Claude over the system that already does this right?" rather than "Where can Claude help?" Pay close attention to this shift in framing, it the key concept this module is building towards.

Cost · Complexity · Risk

**Cost:** Every lookup that a simple deterministic system could have handled gets sent to Claude instead. You end up paying for the model to do work that a database query or a rules table could have done for a fraction of the cost, and across thousands of requests that can add up fast.

**Complexity:** When you move logic out of a table-driven system and into the model, errors stop being traceable. A deterministic rule fails in a predictable, debuggable way. A model handling the same job produces variable outputs that are much harder to observe and diagnose.

**Risk:** The model has no reliable way to know when its information is out of date, and it will not flag the gap. When the model becomes the source of truth instead of the partner's actual system, authoritative answers can drift quietly, with no error thrown and no warning raised.

---

<!-- S08 -->

*Watch Out · 4 min · Decomposition*

### When the deterministic check quietly drifted

> **Setup hook**
> 
> When the team is excited about Claude, putting a deterministic check inside the model provides a cleaner design: one component, fewer integrations, and easier to demo. It is the type of move a senior Architect makes when a team is moving fast and the rule looks "easy enough" for the model.

### A scoping call, transcribed

The conversation below is a real scoping exchange. Two people make a reasonable call to simplify a design, and in the moment it looks like a clean win. What they've actually done is hand a deterministic business rule, one that has to be right every time, to the model, a probabilistic system, which is right most of the time but not all of the time. That gap didn't surface during development, instead it surfaced three months later, in an audit.

This section explores a failure mode where the goal is to show you what went wrong so you can recognize the pattern early and make a different decision.

> **Partner:** "We have a rule that any claim over £5,000 needs a senior adjuster. Today we're doing an SQL check against the claims table. Can Claude handle that instead?"
>  **Architect:** "We can prompt Claude to extract the amount and route accordingly if it's over 5K. That keeps it in one step instead of reaching out to a separate system to check, so it's way simpler."
>  **Partner:** "Perfect, that works for me."

*[Three months later, in production]*

> **Of 14,000 claims processed, 41 routed incorrectly**
> 
> All 41 shared the same problem. The amount was not written as a clean number. It was tucked inside a sentence, like 'damages estimated around five thousand pounds.' The model treated 'around five thousand' as a loose estimate rather than a figure that should trigger senior review, so those claims went to standard handling. The rule was precise. The information it had to work with was not, and the model followed the letter of the rule instead of its intent.

### What broke: a deterministic rule handed to a probabilistic system

The threshold didn't change, but what enforced the rule did. A deterministic rule that needs to be correct every time was folded into Claude, which is right most of the time. The gap between them is where the 41 misroutes lived.

The team never built a set of test cases to check the routing, because they had treated routing as something the model would just handle rather than a rule the business was counting on. That difference is the crux of the problem. A rule the business is counting on must be tested, watched, and owned by a human. Something you assume the model will handle is left alone until it breaks.

The misroutes were caught by an audit, not by the system's own monitoring. The kind of logging that would have caught a broken SQL check does not record the choices a model makes inside a single request, so nothing flagged the drift. The failure remained invisible until someone went looking for it.

> **Why this broke**
> 
> A rule that needs to be right every time was handed to a system that is right most of the time. That tradeoff is easy to miss during scoping because the model handles the clean cases correctly, and clean cases are what you see in demos and early testing. The cost of "most of the time" doesn't reveal itself until you audit and by then the partner is calling.

---

<!-- S09 -->

*Checkpoint · 4 min · Decomposition*

## Sort the field-service capabilities

A field-service partner has handed you a request list for a knowledge assistant their engineers will use on-site. Click a capability to select it, then click the right owner bucket to place it. All 8 items must be placed before submitting.

**Sorting exercise (answer key):**
- **Claude:**
  - Summarize the engineer's case notes into a one-page handover
  - Extract the part number from a photo of the unit label
  - Draft a follow-up email to the customer explaining the delay
- **Existing Systems:**
  - Return the current stock level of part SKU 78-A at the closest warehouse
  - Calculate the total billable time across three job tickets
  - Tell the engineer whether the warranty applies to this serial number
- **Human:**
  - Approve a refund above £2,000 if the engineer requests one
  - Decide whether to escalate a safety incident to the field manager

---

<!-- S10 -->

*Checkpoint · 4 min · Decomposition*

## Decompose the request

A partner brief is below. For each step, select the right owner: what Claude does, what existing systems do, or what humans do. The previous checkpoint tested whether you could recognize the four properties; this one tests whether you can decompose the split.

> **The brief**
> 
> A regional logistics partner wants an assistant that, for each inbound shipping exception: reads the carrier's free-text exception note, decides whether the shipment qualifies for an automatic refund under the partner's published policy, looks up the customer's contract tier, drafts a notification to the customer, and issues the refund.

**Assignment exercise (answer key):**
- Read the carrier's free-text exception note → **Claude**
- Decide whether the shipment qualifies for an automatic refund under the partner's published policy → **Existing System**
- Look up the customer's contract tier → **Existing System**
- Draft the customer notification → **Claude**
- Issue the refund → **Human**

---

<!-- S11 -->

*Teaching · 13 min · Pattern Selection*

## Composing primitives into augmented call, workflow, agent

Once you've established which parts of a task Claude owns versus what your systems and people own, the next decision is structural: what shape does Claude's involvement take?

There are three patterns to choose from: an augmented LLM, a workflow, and an agent. Each one takes a different position on two axes: predictability (how predictable the path through the work is) and model autonomy (how much autonomy you're willing to hand to the model).

### Three patterns for structuring Claude's involvement

#### Tab: Augmented LLM

A single model invocation: you send the request, the model completes the task, and your code handles the wiring around it. You can add tool use, retrieval, or extended thinking to that call, but the model is still doing one bounded job in one pass. The control flow never branches based on what the model decides. Use this when the task is well-defined, the output is something you can verify, and there's no reason to split the work across multiple steps.

#### Tab: Workflow

You decompose the task into named steps and orchestrate them in your own code. Each step may or may not call Claude. Because the control flow lives in your code rather than inside the model, you can log it, test it, and reason about its behavior the same way you would any other piece of software. Use this when error cost is real, observability matters, and the steps can be determined in advance.

#### Tab: Agent

You give Claude a goal and a set of tools and the model determines its own sequence of steps to reach that goal. The control flow lives inside the model, not in your code. That's what makes it an agent rather than a workflow: the path through the work is not written in advance anywhere you can inspect. Use this only when the path through the work cannot be enumerated in advance, and only when the cost of an unexpected or inconsistent output is acceptable and recoverable. In production, agents are typically bound by constrained tool entry points, per-turn budgets, explicit permissions, and stopping criteria. These constraints are not options; they keep an agent from becoming a liability.

### Mapping use cases by predictability and autonomy

Plot any use case on two axes: how predictable the path is, and how much autonomy you are willing to grant the model.

HIGH
 LOW
 LOW PREDICTABILITY
 HIGH PREDICTABILITY
 MODEL AUTONOMY

Agent

High autonomy, low predictability. The model owns the trajectory.

Workflow

Predictable shape; bounded model judgment inside each step.

Augmented LLM

High predictability, low autonomy. One bounded model call.

**Augmented LLMs** sit in the high-predictability, low-autonomy quadrant. You know the task, you know what good looks like, and the model executes it once.

**Workflows** occupy the middle band. The overall shape is predictable, but each step may involve model judgment in a contained way.

**Agents** sit in the high-autonomy, low-predictability corner. This is the pattern to reach for when enumerating the steps in advance and is the expensive part of the problem: open-ended investigation, long-horizon work, and tasks where the next move depends on what the last one turned up. Claude Code is a production-proven example: it explores an unfamiliar codebase, decides which files to read based on what it has already found, and runs multi-step engineering work that no one could script ahead of time. That is the capability agents unlock, but the associated cost is just as real. This is where non-deterministic failures concentrate in production, because the model's trajectory is the control flow and there's no code boundary where a guard can sit.

### Sub-patterns within workflows

Choosing a workflow doesn't fully specify the design. There are four shapes a workflow can take, and each reflects a different assumption about how the steps relate to each other.

| Sub-pattern | Shape | When it earns its place | Examples |
| --- | --- | --- | --- |
| **Chaining** | Step 2 takes step 1's output as its input, working sequentially and linearly. | Use this when the task naturally decomposes into stages with clear handoffs, such as extract, then classify, then summarize. Each stage has a defined output that the next stage consumes. | A contract review pipeline: the first call extracts all obligations and deadlines from the raw document, the second classifies each by risk level, and the third drafts a summary memo for the lawyer. Each stage has a clean output the next stage consumes. |
| **Routing** | A classifier, often Claude itself, decides which downstream path to take. | Use this when inputs vary in kind and different kinds require different handling. | An incoming support ticket arrives: A classifier reads it and routes billing questions to a retrieval index over account data, technical issues to a retrieval index over product documentation, and escalations directly to a human queue. The same input entry point, three different handling paths. |
| **Parallelization** | Multiple model calls run concurrently; results are aggregated or voted on. | Use this when sub-tasks are independent and can run at the same time. Reviewing multiple files or reviewing distinct sections of a long document fits this shape because neither sub-task depends on the other's output. | A due diligence review across twelve supplier contracts: Each contract is sent to a separate model call simultaneously. All twelve results are returned and aggregated into a single risk report. No call depends on another's output, so there's no reason to run them sequentially. |
| **Evaluator-optimizer** | One model call produces a first attempt at the output. A second call evaluates it and requests revision. The loop repeats until a quality criterion is met or a retry limit is reached. | Use this when quality is verifiable but a single attempt isn't reliable enough. Code generation ran against a test suite, or structured-output extraction with a strict schema, are common applications. | A model drafts a response to a customer complaint. A second model call grades the draft against a rubric (does it name the specific issue, take ownership, offer concrete next steps in the brand's tone) and checks whether the output matches the expected structure. If it doesn't, the evaluator returns specific feedback and the generator rewrites. The loop exits when every rubric item passes or hits a retry limit. |

These four patterns aren't mutually exclusive. Most production workflows combine more than one pattern, and the right choice is usually the simplest one that meets the error tolerance and observability requirements of the task, and revisit that choice once you have production data; escalate only when measurement shows the simpler pattern falling short.

### A framework for choosing the right pattern: five factors in sequence

Walk through these five factors in sequence. For each one, ask whether the factor rules out any of the three patterns – Augmented LLM, Workflows, Agent. The first factor that rules out a pattern is the deciding one. The table below shows what each pattern costs you on each factor, so you can see exactly where the tradeoffs land.

| Factor | The question to answer | Augmented LLM | Workflow | Agent |
| --- | --- | --- | --- | --- |
| **Predictability** | Can you enumerate the steps in advance? | Low: single bounded task. | Low: you wrote the path. | High: trajectory is unpredictable by design. |
| **Error cost** | What does a wrong answer cost: a retry, an audit, a lawsuit? | Medium: exposes you to the model's output distribution without step-level guards. | Low: deterministic guards sit between steps. | High: exposes you to the full output distribution across multiple turns. |
| **Observability** | Can your operations team see what happened and reconstruct why? | Medium: a single call is easy to log but opaque inside. | Low: steps log as code does, with standard tooling. | High: the trajectory reads like a transcript; most current observability tooling isn't built to alert on this. |
| **Latency budget** | What is the user-visible deadline? | Low: fastest in standard configurations, though extended thinking or retrieval adds time. | Medium: predictable but additive in duration. | High: runtime is open-ended; budget for the worst case, not the median. |
| **Cost** | What's the per-request token cost at your expected volume? | Low: fewest tokens per request. | Medium: scales with step count. | High: iterative reasoning, multi-turn tool use, retries, and growing context can materially increase token usage and latency. Poorly bounded agents are often the most expensive pattern. |

### Try prompting before you consider fine-tuning

If prompting feels unreliable, the instinct for many engineers is to reach for fine-tuning. On Claude, that's usually the wrong first move. Work through this sequence first:

- Optimize the prompt. Most reliability problems are prompt problems.
- Add tool use or retrieval if the prompt alone isn't enough.
- Move to a stronger pattern like an evaluator-optimizer if quality still isn't where it needs to be.
- Only then consider fine-tuning.

Fine-tuning does have a place, but in specific situations:

- The task runs at very high volume and inference cost is the real constraint.
- Latency is critical and a smaller specialized model will outperform a prompted general one.
- The output needs to follow a consistent format and prompting hasn't solved it reliably.

Outside those situations, fine-tuning locks you to a fixed model version and narrows your options without much to show for it. Treat it as the last step in a deliberate progression, not a quick fix for a prompt that isn't working yet.

> **Note on availability**
> 
> Fine-tuning Claude is not broadly available. Access is limited, varies by model and delivery route, and changes as Anthropic expands the program. Confirm current options with the Anthropic account team before recommending this path to a partner.

These three patterns are not abstract categories. Each is an assembly of the primitives you inventoried in the foundations section: an augmented call is the model plus tools; a workflow is primitives wired together in your own code; an agent is the model choosing its own sequence of tool calls. Choosing a pattern is choosing how to compose those parts.

### Skills-based architecture as a packaging option

Alongside choosing a pattern, decide how the capability is packaged. Three options sit on a spectrum: a prompt-only solution (instructions alone), direct tool use (the model calls functions in your code), and a Skills-based architecture (a versioned, reusable Skill that packages the procedure, its instructions, and any scripts as one governed unit). Reach for a Skill when the same procedure runs repeatedly, needs to be distributed across teams or products, or must be versioned and governed.

Apply the Delegation lens to the pattern itself: does this pattern grant Claude appropriate or excessive decision authority for the risk profile in front of you? An agent that can act autonomously is the right choice only when the stakes and reversibility of its actions justify the autonomy it is given.

Cost · Complexity · Risk

**Cost:** Agents don't automatically cost more than workflows. What drives cost is how much context accumulates across the conversation and how many model calls are made. A poorly designed workflow can cost more than a well-designed agent. Design matters more than the pattern label.

**Complexity:** Workflows and agents fail in different ways. A workflow fails when a step in your code fails. An agent fails when the model makes a bad decision somewhere in a sequence of turns. That second type of failure is harder to spot and harder to diagnose, and your standard debugging tools won't catch it the same way.

**Risk:** An agent's autonomy is your liability surface. An agent can do anything its tools allow, including combinations you didn't test for. The broader the tool permissions, the larger the space of things that can go wrong. Keep the tool entry point as narrow as the task allows.

---

<!-- S12 -->

*Watch Out · 4 min · Pattern Selection*

### When the team wanted flexibility and got non-determinism

> **Setup hook: when teams pick agents and shouldn't**
> 
> This is a common mistake. Agents are often chosen because a task feels open-ended, not because the task requires one. But feeling uncertain about how to structure the work is different from a task where the steps genuinely can't be determined in advance. If you could have written the steps in code, you could have used a workflow instead of an agent and avoided taking on unnecessary complexity of non-deterministic control flow.

The three quotes below are from a single team's 90-day retrospective. Each one names a different layer of the same underlying mistake.

"We picked an agent because we didn't want to constrain it too early. By month two we'd added so many guardrail tools we'd basically rewritten the workflow inside the agent loop, minus the logging."

"Compliance came in and asked which step approved the disbursement. We pointed at a model turn. They asked which version of the model. We checked the trace. The version had rolled forward two weeks earlier and nobody had re-validated."

"The actual paths through the system, when we mined the traces, fell into only four shapes. Four. We could have written that as a router and four chains and saved ourselves six months."

### What broke and why

Each quote names a distinct failure, and they compound in order.

**The team optimized for unknown future flexibility instead of the known present shape.** When the team mined their traces at month three, the actual paths through the system fell into four shapes, all enumerable from week one. The workflow they needed was a router with four chains. They built an agent instead and spent six months reconstructing that structure inside the loop.

**Non-determinism became a compliance problem.** When an auditor asked which step had approved a disbursement, the team could only point to a model turn. What the agent pattern specifically added was having no discrete, auditable step to point to. This is how agent autonomy becomes a compliance risk: not in normal operation, but when an external party needs a deterministic answer and the system can only produce a trajectory.

**An unpinned model version compounded the gap.** The auditor then asked which version of the model had run. The trace showed the version had rolled forward two weeks earlier with no re-validation checkpoint. That roll-forward is a model-governance gap and would have been a problem under any pattern: an unpinned version with no re-validation gate or a workflow that shipped the same way would have inherited the same exposure. Only one of these two failures is about the agent pattern itself.

> Choosing an agent when you're not sure if it is the right pattern is not a safe default. An agent is the right choice only when the steps through the work genuinely can't be determined in advance. If the steps are known upfront, choosing an agent over a workflow means paying for flexibility you won't use: extra tokens, latency, and audit gaps that surface when compliance asks something your traces can't answer.
>  Agents shouldn't be avoided, but they should be fit for purpose. If the work had been genuinely unpredictable, an agent would have been the right call for exactly that reason. This team's mistake was jumping to an agent when the four paths through their system were knowable from the start. A router and four chains would have given them a clean, auditable structure. Instead, they spent six months rebuilding that structure by hand inside an agent loop.

---

<!-- S13 -->

*Teaching · 9 min · Pattern Selection*

## Multi-agent systems and orchestration

Pattern selection told you when to reach for an agent. Some problems are too large or too varied for a single agent to hold in one context. When that happens, the design moves to multiple agents working together: an orchestrator that decomposes the work and subagents that each carry part of it. This screen teaches how those systems are structured, how they fail, and where a human belongs in the loop.

### Orchestrator and subagents: roles, delegation, synthesis

A multi-agent system has two roles.

### The orchestrator

Owns the goal: it decomposes the work, decides what to delegate, and synthesizes the results into a single answer. The orchestrator never does the sub-task work itself; its job is delegation and synthesis.

### The subagents

Own scoped sub-tasks: each runs in its own context, does one piece, and returns a result.

Three things must be designed, not assumed: how the work is decomposed into sub-tasks, how each subagent's result is structured so the orchestrator can combine it, and how the orchestrator resolves conflicts or gaps when the results come back.

### The worked pattern: fan-out over a large work item

The most common multi-agent shape is a fan-out. For example: A parent agent faces a work item too large for one context: a 400-file codebase to audit, a 200-document corpus to summarize, and a regulatory filing to check against fifty rules. The orchestrator splits the item into independent units, dispatches one subagent per unit (in parallel where the units do not depend on each other), and then synthesizes the returned results into a single deliverable. Here the win is twofold: each subagent works in a clean context sized to its unit, and independent units run concurrently.

### Error recovery: where a failure can be caught, and where it cannot

In a multi-agent system, the architectural question to ask is 'Where is each failure mode recoverable?'.

- A subagent failure is usually recoverable: if one unit fails, the orchestrator can retry it, route it elsewhere, or drop it and flag the gap, while the rest of the work proceeds.
- An orchestrator failure is usually not recoverable: if the agent that owns the goal and holds the synthesis loses its thread, the whole run fails, and partial subagent work may be stranded.

Design for this asymmetry, make subagent work idempotent and retryable, and protect the orchestrator's state.

| Failure | Where it lands | Design response |
| --- | --- | --- |
| A subagent returns a malformed or empty result | Subagent boundary (recoverable) | Validate each result; retry or re-route the failed unit; record the gap rather than failing the run. |
| Two subagents return conflicting results | Synthesis step (recoverable) | Give the orchestrator an explicit conflict-resolution rule, or escalate the conflict to a human. |
| The orchestrator loses the goal or its synthesis state | Orchestrator (often unrecoverable) | Protect orchestrator state; checkpoint progress so a failed run can resume rather than restart. |
| Traces fragment across orchestrator and subagents | Observability (cross-cutting) | Propagate a shared trace identifier so a single run is reconstructable end to end. |

### Human-in-the-loop checkpoint patterns for agent workflows

A multi-agent system can take many actions before a human ever sees the output, which makes checkpoint placement a deliberate design choice. A human-in-the-loop checkpoint is a gate that pauses execution for review, positioned by the risk and reversibility of the action about to be taken. Place a gate before any irreversible or high-stakes action a subagent would otherwise take autonomously; sample lower-stakes actions rather than gating each one. The full treatment of routing by stakes will be covered in a later section, here the point is that the gate is part of the orchestration design, not bolted on afterward.

Cost · Complexity · Risk

**Cost:** Multi-agent systems multiply token spend, every subagent has its own context, and the orchestrator pays to synthesize. Reach for the pattern when the work genuinely exceeds one context, not as a default.

**Complexity:** Each added agent is another failure boundary to observe and govern. The discipline is the fewest agents that meet the requirement, with clear ownership of the goal.

**Risk:** The dangerous failure is the silent one: a subagent drops a unit and the orchestrator synthesizes a confident, complete-looking answer over incomplete work. Validate coverage, do not assume it.

---

<!-- S14 -->

*Watch Out · 4 min · Pattern Selection*

### When fan-out hid a dropped unit

### The trace

A compliance team built a multi-agent system to check a 50-section vendor contract against an internal policy checklist. The orchestrator fanned the work out to one subagent per section, each returning a pass/flag verdict, and synthesized a clean summary: "48 sections reviewed, 3 flagged." The summary read as complete and was circulated to the legal lead.

Two sections had never been reviewed. One subagent had timed out and returned nothing; another had failed to parse a scanned page and returned an empty result. The orchestrator, given no coverage check, counted only the results it received and reported "48 reviewed", but there were 50 sections, and nobody had told the synthesis step to reconcile the count.

### What broke and why

- **No coverage check at synthesis.** The orchestrator synthesized over the results it happened to receive, with no rule that the number of results must equal the number of units dispatched.
- **A recoverable failure was never recovered.** A timed-out subagent is the recoverable case, but only if something retries it or flags the gap. Here the failure was silent because nothing was watching the boundary.
- **Confident synthesis over incomplete work.** The output's fluency masked the gap. A multi-agent system fails most dangerously when the summary looks complete and is not.

> **Why this broke**
> 
> Completeness was assumed, not verified. The orchestrator dispatched 50 units and reported on the results it received. Two units never came back, and nothing in the design noticed the difference. Three gaps lined up to let that through.
>  **The count was never reconciled.** The synthesis step added up the verdicts it received and stopped there. No rule said the number of results had to match the number of units dispatched, so 48 returned results became "48 reviewed" instead of "two are missing."
>  **A recoverable failure had nothing watching it.** A timed-out subagent and an empty parse result are both the recoverable case, but only when something retries the unit or flags the gap. No component owned the subagent boundary, so both failures passed silently.
>  **The output read as complete.** The summary was fluent and well-formed, which is exactly what made the gap invisible. A multi-agent system fails most dangerously when a confident summary is built over work that was never finished. The fix is a coverage check at synthesis: results returned must equal units dispatched, or the run flags the difference before anyone reads the summary.

---

<!-- S15 -->

*Checkpoint · 5 min · Pattern Selection*

## Critique the orchestration design

> **Draft architecture submitted for review**
> 
> Below is a draft multi-agent architecture submitted for review: an orchestrator fanning a large document-classification job out to subagents. Six components are listed. Select the three that carry a control or failure-boundary defect.

Select **exactly 3** components that carry a control or failure-boundary defect.

- [ ] 1Orchestrator decomposes the corpus into per-document units

↓

- [ ] 2Subagents run in parallel, each returns a verdict

↓

- [x] 3Synthesis sums returned verdicts into a report

↓

- [x] 4Irreversible action (auto-archive) taken with no human gate

- [x] 5No retry or gap-flag on a failed subagent

- [ ] 6Shared trace ID propagated to every subagent

---

<!-- S16 -->

*Teaching · 15 min · Reference Architectures*

## The shapes the industry has already paid to learn

Choosing a pattern gets you the right structure. Patterns give you the shape. The next question to ask is how that structure connects to everything around it. Reference architectures will give you the wiring.

### Reference architectures: what good looks like and where projects go wrong

Reference architectures are references, not blueprints to adhere to. The goal is not matching a problem to a fixed design and implementing it as drawn. Every partner workload is unique, so your goal here is to understand these common patterns well enough to generalize from them. Ultimately, you should be able to take the shape that fits, adapt it to the workload in front of you, and recognize when a workload draws on more than one pattern at once. Most partner problems map to one of a handful of reference architectures already proven in the Claude ecosystem: documented patterns for how to wire an LLM application together to solve a recurring class of problem. The table below covers common reference architectures, what they look like when they're built well, and the failure modes that show up repeatedly.

Expand each pattern to see what good looks like and where projects go wrong.

**▸ Agent (see S11)**

**What good looks like:** The model works toward a goal by deciding which tools to call and in what order. Autonomy is kept in check by limiting what the tools can do and setting a budget on how many turns the model gets. Use this when the path through the work can't be written in advance: investigating a codebase, pulling from multiple research sources, or triaging complex customer cases.

**Where projects go wrong:** Unbounded autonomy: Giving the model tools that change state with no human review, no turn limit, and no way to measure whether the goal was met.

**▸ Retrieval-augmented generation (RAG) (see S11)**

**What good looks like:** A stable knowledge corpus, such as product manuals, internal docs, or regulatory text, is chunked and indexed. When a question comes in, the most relevant chunks are retrieved and passed to the model as context.

**Where projects go wrong:** Using RAG to answer questions about live state: order status, inventory levels, ticket queues. The index is a snapshot. If the underlying data has changed since the last refresh, the answer will be wrong.

**▸ Document processing pipeline → Evaluator-optimizer (see S11)**

**What good looks like:** Structured extraction from semi-structured documents like claims, invoices, and contracts. The pipeline handles OCR, extracts fields against a schema, validates the output, and routes exceptions. An evaluator-optimizer is common here because first-pass extraction on edge cases isn't reliable enough to trust without a check.

**Where projects go wrong:** No exception path. Low-confidence extractions go through the same pipeline as clean documents, with no human gate to catch the ones the model got wrong.

**▸ Customer-service / ticket triage → Routing (see S11)**

**What good looks like:** Classify intent and what the user is asking for, then route to the right backend: a knowledge retrieval layer for documentation questions, a transactional API for live state queries like order status or account changes, and a human approval layer for high-consequence actions.

**Where projects go wrong:** Using retrieval for live order status instead of calling the API directly. No escalation path to a human. Deploying an agent variant before the simpler routed workflow has been properly measured.

**▸ Coding agent (agentic exploration with deterministic edit/test/review steps) (see S11)**

**What good looks like:** The work splits into two phases. First, the agent investigates the codebase to understand what needs to change: this part is agentic because the path through an unfamiliar codebase can't be written in advance. Second, the actual edits follow deterministic steps: parse, plan, propose, test, review. Subagents handle isolated tasks with enough context to do the job but not so much that the steps become unmanageable.

**Where projects go wrong:** Letting the agent edit and commit without a human review gate. Not tracking regression rates against an eval set for each language or framework in the codebase. Treating the whole thing as a conversation rather than a structured pipeline with defined handoffs.

Full RAG implementation depth, including chunking strategies, embedding approaches, hybrid lexical-plus-semantic retrieval, and reciprocal rank fusion, is covered in the RAG pipeline design screen that follows.

### How to decide if a problem needs one or several patterns

Real partner problems frequently sit at the boundary between two architectures. A routing workflow might hand certain intents to an agentic investigation loop. A document processing pipeline might use RAG over policy text when it hits an exception case. Drawing on more than one pattern is sometimes the right answer.

What matters is why you are reaching for a second pattern. Don't think of patterns as pieces you snap together. Look at why each one works and shape the idea to fit your problem. Draw on a second pattern when the two parts of your problem break in different ways that are worth managing separately. If you are reaching for a second pattern because you haven't decided what problem you're solving, adapt a single pattern instead. That's a design decision you're deferring, not a pattern you're applying.

### The most common mistake: retrieval applied to live state

The most common reference architecture mistake is using retrieval where a tool call belongs. You can recognize it by looking for these symptoms: stale chunks, results that shift with each index refresh, answers that contradict what's in the database. A better embedding model or a shorter refresh interval won't fix this issue. Instead, call the system that owns the live state directly rather than retrieving a cached version of it.

Cost · Complexity · Risk

**Cost:** Composing two reference architectures roughly double the surface area you must maintain. When in doubt, pick one.

**Complexity:** Each reference architecture carries its own eval contract. You need separate eval sets per architecture, not a single eval set for the composed system. A system that looks healthy at the top level can be masking failures in one of its components.

**Risk:** Misapplying retrieval to live state produces stale but confident answers. The system looks healthy from the outside: normal latency, no errors. Detection cost is high because there's no signal that something is wrong until a user notices the answer doesn't match reality.

---

<!-- S17 -->

*Watch Out · 4 min · Reference Architectures*

### When retrieval got reached for instead of a tool call

> **Setup hook: how RAG fails when applied to live state**
> 
> The broader underlying skill here is context engineering: deciding which mechanism is responsible for getting each kind of data in front of the model. Retrieval over a vector index is one example, and this trace shows what happens when it is asked to own data it cannot own. This often happens when a team reaches for RAG because it worked on a previous use case, without stopping to ask whether the new one shares the same properties. RAG works well when the answer lives in a body of reference material that remains stable between index refreshes, e.g., documentation, policy text, product manuals. It breaks for live state because retrieval treats your data as text snapshots, not as a system with current values. When those snapshots disagree, the model picks the most similar one and answers confidently. There is no way to know which snapshot is current. The trace below shows exactly how this plays out.

### The trace: electronics retailer customer service assistant

User asks: "Where's my order?"
RETRIEVED CHUNK #1 (similarity 0.78): "Order #88412 was placed on the 11th of June and shipped on the 12th via standard courier. Tracking number AB123…"
RETRIEVED CHUNK #2 (similarity 0.74): "Order #88412 is currently being processed. Expected dispatch within 24 hours."
MODEL OUTPUT: "Your order shipped on the 12th of June via standard courier. Tracking: AB123…"

Both chunks were real strings that existed in the corpus at different points in time. The index conflated them. The order had shipped, been returned to depot due to a damaged label, and was awaiting re-dispatch. Note that this current state appears in neither chunk: the corpus held two stale snapshots and no record of where the order was, because an index captures what was true when it was written, not at the present. A customer service tool to fetch live order status existed in the partner's API. It was not called.

### What broke and why

**▸ The category error**

Retrieval is the right mechanism for knowledge: FAQs, policies, manuals. It's the wrong mechanism for transactional state. Order status wasn't failing because retrieval is broken. It was failing because current state had been represented as historical text snapshots in the first place.

**▸ A data-architecture failure, not a retrieval failure**

Live state was indexed as text, so the system searched a corpus of past snapshots rather than querying the system of record.

**▸ Similarity is not truth**

Embedding similarity confidently merged two stale snapshots into one answer. A higher similarity score does not mean a truer answer; it means the retrieved text was semantically close to the query, which is not the same thing when the underlying state has changed since the text was written.

**▸ The fix is a tool call**

Not a better chunker, a shorter refresh interval, or a higher similarity threshold: a tool call to the order-status service. The knowledge base keeps the FAQ content. The transactional database keeps the orders. Two types of data, two access patterns, two mechanisms.

### The retrieval principle

Retrieval is for stable knowledge: things that were true yesterday and will be true tomorrow. Tool use is for live state: things whose current value is owned by a system and changes independently of your index. Conflating them produces answers that are fluent, confident, and wrong in ways that are hard to detect because the system shows no error signal. The model returned a response. The response looked correct. The customer got false information about their own order.

---

<!-- S18 -->

*Checkpoint · 6 min · Reference Architectures*

## Critique the diagram

> **Practice: review a partner's draft architecture**
> 
> Below is a reference-architecture sketch of a customer-service assistant. Six components are listed. Select the three that are misapplied for this routing design.

Select **exactly 3** components that are misapplied.

- [ ] 1Intent classifier (Claude call)

↓

↓

- [x] 2Retrieval over "Order Status Index"

- [ ] 3Retrieval over "Product Manual Corpus"

↓

↓

- [x] 4Agent loop with tool entry point: refund, cancel, update-address

- [x] 5(missing) Escalation path to human agent

↓

↓

- [ ] 6Response composer (Claude call)

---

<!-- S19 -->

*Teaching · 10 min · RAG Pipeline Design*

## Chunking and indexing

The previous screen on reference-architectures named RAG as a known-good shape and showed where it is misapplied. This screen goes one level deeper, into the design of the retrieval pipeline itself: how a corpus is broken into chunks, how those chunks are indexed, and how the retrieval strategy is matched to the query patterns the system will see.

### Chunking: how you break the corpus, by what the corpus is

A chunk is the unit that gets retrieved. The chunking approach is chosen by the structure of the source material, not by a default size.

| Chunking approach | How it works | When it earns its place |
| --- | --- | --- |
| **Fixed-size** | Split into uniform spans (with overlap) regardless of structure. | Homogeneous, unstructured text where natural boundaries are weak; simplest to operate. |
| **Semantic** | Split on meaning boundaries, topic shifts, sentence groups that hang together. | Prose where a retrieved chunk must be self-contained to answer well; reduces mid-idea cuts. |
| **Hierarchical** | Preserve document structure, sections, subsections, and retrieve at the level that fits. | Structured documents (contracts, manuals, policies) where section context carries meaning. |

### Indexing: how you make chunks findable, by how queries are phrased

Indexing decides what "similar" means when a query arrives. The strategy is chosen by the query pattern.

| Indexing strategy | What it matches | When it earns its place |
| --- | --- | --- |
| **Dense (embeddings)** | Semantic similarity, meaning, not words. | Queries phrased differently from the source; paraphrase, intent, concept matching. |
| **Sparse (keyword, e.g. BM25)** | Exact terms, identifiers, codes, names. | Queries that hinge on specific tokens: part numbers, statute citations, error codes. |
| **Hybrid** | Both, with the results combined. | Mixed query patterns, the common production case; recovers the exact-match results dense retrieval misses. |

When a hybrid index returns two ranked lists, they must be merged into one. Reciprocal rank fusion is the standard, low-tuning way to do it: each result is scored by its rank in each list, and the combined score favors items that rank well in both. The point for an architect is combining dense and sparse results is a design decision with a known, defensible default.

### Articulating the trade-off

Every retrieval design makes trade-offs among three things:

- **Retrieval quality:** Does the right chunk come back?
- **Latency:** How long does retrieval add to each request?
- **Maintenance:** How much does the pipeline cost to keep correct as the corpus grows and changes?

Smaller chunks and hybrid indexing tend to raise quality and latency together; larger chunks and dense-only indexing lower latency and maintenance but miss exact-match queries. There is no universally right point, only the point that fits this corpus and these queries, stated as a trade-off you can defend.

Cost · Complexity · Risk

**Cost:** Hybrid indexing and smaller chunks raise both retrieval compute and per-request latency. Size the pipeline to the query patterns you actually have, not to the most thorough one imaginable.

**Complexity:** Every chunking and indexing choice is something to maintain as the corpus changes. A pipeline that was correct at launch can degrade silently as documents are added.

**Risk:** The failure mode is a confident answer built on the wrong chunk. Retrieval quality is not visible in the output, it has to be measured against a labeled set, which is why this work ties straight to evaluation.

---

<!-- S20 -->

*Exercise · 8 min · RAG Pipeline Design*

## Design the RAG pipeline

> **The brief**
> 
> A professional-services partner has a corpus of roughly 4,000 documents: client engagement contracts (highly structured, section-numbered), past project write-ups (long-form prose), and a methodology handbook (structured, with defined procedures). Their team asks three kinds of question: "what does our methodology say about X?" (concept lookup), "find the clause about termination in the Acme contract" (exact-target lookup), and "summarize how we've handled engagements like this one" (broad synthesis across write-ups).

Draft your pipeline design. For each of the three document types, name the chunking approach you would use and explain why. Then name the indexing strategy for the full corpus and state the trade-off you are making. Write your answer before clicking to reveal the model answer.

Feel free to ask Claude to compare what you've written with the provided answer.

*(Free-response exercise: Your pipeline design)*

**Contracts and methodology handbook:** Hierarchical chunking that preserves section and subsection structure. Both sources are structured and section-numbered, so retrieving at the section level keeps the clause or procedure intact and self-contained. Fixed-size chunking cuts across section boundaries and loses the structural context the query depends on.

**Project write-ups:** Semantic chunking on meaning boundaries so each retrieved chunk is self-contained. Long-form prose has no section numbers to anchor hierarchical chunking, and fixed-size chunks cut mid-idea. Semantic chunking keeps each retrieved passage coherent enough to answer the question on its own.

**Indexing strategy:** Hybrid dense-plus-sparse. The query set mixes exact-clause lookups ("find the termination clause in the Acme contract") with open-ended conceptual questions ("how did we approach X?"). Sparse handles exact-target lookups where specific identifiers matter; dense handles concept-lookup and synthesis queries where meaning, not exact terms, drives the match. Neither alone covers both patterns.

**The dominant trade-off:** query variety is the load-bearing constraint. The hybrid index adds retrieval compute and a rank-fusion step, but those costs earn their place because the query set genuinely needs both modes.

How did your design compare?

**Course answer data:**
**FB:**
- **correct.** Strong design. Each source type got the chunking that fits its structure, and the indexing strategy matches the query variety. The dominant constraint, query variety, determined the indexing choice. That reasoning is what makes the design defensible.
- **partial.** Close. The most common miss is the index: with both exact-clause lookups and open-ended questions in the query set, neither dense nor sparse alone covers it. Re-read the indexing-by-query table and revise.
- **incorrect.** Match each choice to the structural property of the source and the pattern of the query. Re-read the chunking-by-corpus and indexing-by-query tables, then redo.

---

<!-- S21 -->

*Teaching · 13 min · Model & Context Strategy*

## Model, context window, and context strategy

By this point you should have a pattern and a reference architecture, but not a shippable system. Three decisions remain, and each one determines what the same architecture costs at scale: 1. Which model fits the task, 2. How much of the context window to actually use, and 3. Whether your context strategy should be progressive or monolithic. These decisions compound across every request at production volume.

### Distinct terms that are easy to conflate

The following terms often get used interchangeably in practice but conflating them produces reference architecture mistakes. Take time to carefully review each term in detail:

- **Context window.** The model's active attention space. Everything inside the context window is available for reasoning and everything outside it doesn't exist to the model. The context window resets between calls unless your application explicitly manages continuity.
- **Retrieval.** Fetched external knowledge, pulled at query time from a corpus the model doesn't hold in memory. Retrieval augments the context window; it doesn't replace it. The model only sees what the retriever surfaces.
- **Persistent application state.** Owned and managed by your system, not the model. Order status, user records, account balances. The model does not have inherent access and requires a tool call to get it.
- **Summaries and memory layers.** Application-managed continuity across turns or sessions. The model has no native memory between calls, so anything that persists does so because your application stored it and passed it back in. This is an architectural choice, not a model capability.

### Model selection: start with Sonnet, move deliberately

The Claude model family currently consists of Opus, Sonnet, and Haiku, each optimized for different cost, latency, and capability tradeoffs.

Opus is Anthropic's most capable model available for use, suited for demanding reasoning, advanced coding, and research synthesis where Sonnet doesn't meet your quality bar. The default starting point is still Sonnet. Move up to Opus only when an eval set tells you Sonnet isn't meeting your quality bar. Move down to Haiku only when an eval set confirms the quality tradeoff is acceptable for your specific task. Your decision to move models should always be measured, not reflexive.

### Context-window sizing: the working-memory cliff

Everything the model attends to lives in the context window. Inside the window, attention is available. Outside it, the model has no access at all. Working memory is the property with the hardest edge of the four: things work until they don't, and then the transition is abrupt.

The context window is measured in tokens. How much text one token covers varies by model generation, tokenizer, and language, so treat any fixed characters-per-token ratio as a rough illustration rather than a rule. Measure instead of estimating: every API response reports actual token counts in its `usage` field, and those measured counts are what the context limit and billing apply to. Everything that enters the context window, your system prompt, the conversation history, retrieved documents, tool outputs, and the model's responses, is counted in tokens. This matters for two reasons: the context window has a fixed token limit, and you're billed per token on every API call. Both constraints show up directly in the decisions covered in this section.

The practical implication is direct: do not budget the full window. Budget for the largest realistic conversation, plus retrieved context, plus system prompt, plus working scratch, plus margin for growth. The context window is a ceiling, not a target, so designing towards the ceiling means you hit it in production.

### Context strategy: spectrum between progressive and monolithic

Every production workload makes a choice, implicitly or explicitly, about how context reaches the model on each call. The choice sits on a spectrum between two poles.

At one end, a monolithic context strategy places everything into the prompt at once: the full document, the full conversation history, the full retrieved corpus. It works for bounded tasks with predictable input sizes. It's also the strategy that hits the working-memory cliff in production, because context accumulates across turns and the window fills silently before anyone notices something has been truncated.

At the other end, a progressive context strategy stages the context instead: it retrieves just-in-time, summarizes across turns, and loads only what the next step needs. Most production workloads belong here.

Two other patterns sit between the poles and show up often enough to treat as strategies. The table below lays out where each of the four strategies earns their place and where they break down.

Expand each strategy to see where it earns its place and where it breaks down.

**▸ Monolithic, load the full required context into a single prompt**

**Where it earns its place:**

- Bounded tasks with predictable input size.
- Stable prefixes that benefit from prompt caching.
- Single-shot Q&A where retrieval latency isn't worth paying.
- Reasoning that genuinely requires simultaneous access to all material.

**Where it breaks down:** Conversations or tool loops where context accumulates turn over turn. Cost and latency scale linearly with input length. Attention quality can degrade on very long contexts well before the hard limit is reached.

**▸ Progressive, carry forward only what the next step needs**

**Where it earns its place:**

- Multi-turn dialogue and iterative refinement.
- Agent loops where each step depends mainly on recent state.
- Workflows that decompose into stages with narrow, well-defined handoffs.

The right default for most production workloads.

**Where it breaks down:**

- Tasks requiring long-range coherence across the full history.
- Decisions that depend on detail dropped in an earlier turn.
- Prompt caching is harder when carried-forward context mutates each turn.

The exact input the model saw at step N is no longer reconstructable, which complicates debugging.

**▸ Retrieval (RAG), fetch relevant chunks from an external store at query time**

**Where it earns its place:**

- Knowledge bases too large to fit in context.
- Sources that change faster than the prompt is redeployed.
- Domains where any single query needs only a small slice of available material.
- Cases where source citation is a requirement.

**Where it breaks down:**

- Queries requiring synthesis across many documents the retriever scores independently.
- Chunking that splits semantic units like tables, code blocks, or multi-paragraph arguments.
- Recall failures where the correct document never enters the top-k.
- Retrieval quality becomes a system you must evaluate and maintain.

**▸ Compaction, periodically summarize or compress accumulated context**

**Where it earns its place:**

- Long-running agents and conversations where the full transcript is wasteful but recent state matters.
- Phase transitions in multi-step workflows that can checkpoint to a clean summary.
- Sessions that would otherwise hit context limits mid-task.

**Where it breaks down:**

- Summaries that drop load-bearing detail: exact identifiers, numeric values, prior decisions, edge cases mentioned once.
- The summarizer is itself a model call with latency, cost, and failure modes.
- Compaction is largely one-way.
- Measuring summary fidelity against the original transcript is an unsolved evaluation problem.

### In practice, strategies may be combined

The four strategies above are presented separately for learning clarity, but production systems almost always combine them. Each handles a different dimension of the context problem, so a well-designed system layers them deliberately rather than picking one. A worked example, long-running coding agent:

| Phase | What's happening | Strategy in play |
| --- | --- | --- |
| Session start | Load the task description and the few files the user explicitly referenced | **Monolithic prefix**, A small, stable context loaded once, ideal for prompt caching. |
| Active work | Each tool call (read file, run tests, edit) appends to the working context | **Progressive recent state**, The latest additions is what the next step needs. |
| Discovery | Agent realizes it needs a file it didn't load initially; searches the codebase and pulls in matches | **Just-in-time retrieval**, The corpus is too large to preload, and only a relevant slice is fetched on demand. |
| Context filling | After many turns, early exploration is taking up space; the conclusions matter but the verbatim tool outputs don't | **Compaction**, Summarizes "what we tried and what we learned," preserving only the insights and decisions that carry the work forward. |

Notice that no single strategy could carry this workload. Monolithic alone hits the context limit. Progressive alone has no way to surface code the agent didn't initially load. Retrieval alone loses the thread of what's been tried. Compaction alone has nothing to compact until other strategies have built up the trajectory.

The architectural takeaway: when designing a context system, ask yourself these separate questions:

- What does the model need at the start? → drives the monolithic baseline
- What does it need from the most recent steps? → drives the progressive window
- What might it need to fetch on demand? → drives the retrieval layer
- What earlier material can be compressed without losing decision-relevant detail? → drives the compaction policy

Context strategy and context sizing are separate decisions that interact but don't determine each other. Treating them as one is where most context-management designs go wrong.

### What extended thinking controls

Extended thinking is a per-request capability: the model works through the problem in a separate block of thinking tokens before it produces the final answer. How you control it has changed across model generations. On Claude Opus 4.6 and later, Claude Sonnet 4.6 and later, and Claude Sonnet 5, adaptive thinking with the effort parameter is the recommended control: you set how much reasoning effort to apply rather than configuring a token budget. Adaptive thinking is the only thinking mode on Claude Fable 5. The older manual thinking-token budget (`budget_tokens`) is deprecated on the 4.6 generation and removed on Claude Sonnet 5, where it returns a 400 error; verify current model support against platform.claude.com at publish time. Thinking tokens are billed as output tokens at the model's standard output rate and generating them adds latency to the call. When extended thinking is not engaged, none of those tokens are generated and none are billed. The decision to use extended thinking anchors on whether to add a billed reasoning pass to a call. The model reasons internally either way. What you're choosing is whether to spend tokens and latency on an expanded pass. On models that support extended thinking, the API may return a summarized representation of the thinking process rather than the full reasoning output. You are billed for the thinking tokens actually consumed during reasoning, not the length of the visible summary.

Once that distinction is clear, the decision rule is straightforward. Extended thinking is a cost and latency tradeoff. Run your evals without it first: if accuracy still isn't meeting your requirements after you've worked on the prompt itself, then consider enabling it. With extended thinking engaged, you pay for the thinking tokens and the additional latency on every call. The case for turning it on should come from a measured accuracy gap, not the assumption that it's a mode that "it can't hurt." Without that evidence, you're paying the cost with no proof it's moving your accuracy metrics.

### Gate every model change with an eval before you ship it

Any change to the model is a change to the system's behavior. A swap between two models is a code deployment and should be treated as such. At a minimum you need three things:

- A curated test set of prompts with known-good outputs that covers the real distribution of work the system sees
- A grading function (model-graded against a rubric, or programmatic where you can express the check in code)
- A delta threshold set in advance below which you do not ship. Set the threshold before you run the eval. If you set it after, you are not setting a standard, you are writing the acceptance criteria after the build.

> **Worked case: a Sonnet to Haiku downgrade, done well**
> 
> The case below shows the full sequence of a model downgrade run against a real production constraint. The pattern to carry into your own work is the rollback criterion: set in advance, refused to negotiate when the data came in, and used to motivate a partial migration instead of a full one.
>  A document-intelligence pipeline has been running on Sonnet for six months and has used their entire budget. Now the team wants to move to Haiku.
>  The team builds an eval set of 250 representative documents with hand-validated extraction targets, stratified across the document types that show up in production traffic. The sample is sized so that per-document-type scores remain meaningful, not just the overall average.
>  The team runs both models against the same set and scores each extraction with the same grading rubric.
>  The regression signature comes back as follows: Sonnet scores 0.94 on average, Haiku scores 0.86 on average, and the variance is concentrated in two document types where Haiku scores 0.71 and 0.74 respectively. The rest of the document types come in within tolerance.
>  The rollback criterion was set in advance: if any single document type drops below 0.85, the migration is rejected. Two document types crossed that line, so the migration as proposed is rejected.
>  The salvage move is to route those two document types to Sonnet via the existing classifier, and route the other types to Haiku. Cost drops materially without taking the regression on the difficult document types.
>  Rather than the specific scores, your takeaway from this case should be focused on how the rollback criterion was decided before the data came in. This meant when the data came in, the team did not have to negotiate with itself, and the eval set surfaced a partial-migration option that a single overall score would have hidden.

> **Forward pointer**
> 
> Model selection and context strategy are two of the prompting-area levers. You will learn about two other prompting area levers (system-prompt design and prompt reuse) later in this module.

Cost · Complexity · Risk

**Cost:** Monolithic context is the silent budget killer. In a document-heavy pipeline, a conversation that starts with a 4,000-token prompt can be carrying 80,000 tokens by turn 30. The per-call cost grows with the conversation, and there's no visible signal until it shows up in billing.

**Complexity:** A model swap looks like a one-line configuration change, but it rewrites how the whole product behaves. Treat model swaps as releases.

**Risk:** No eval set means no rollback signal. A regression discovered in production is a regression that wasn't detected at all, because by the time you see it, the user already has.

---

<!-- S22 -->

*Watch Out · 4 min · Model & Context Strategy*

### When defaulting to Opus everywhere produced a 7× cost overrun

> **Setup hook**
> 
> When the demo has to land and the partner is in the room, the smart-sounding answer is "use the best available model." That answer is also the path of least resistance during build: no eval set required, no defending a choice. The bill arrives later, and by then the system has been live long enough that downgrading carries an associated change-management cost.

### 90 days after launch

**Symptom.** Monthly cost is running at seven times the original modeling figure. Latency on the user-facing path is sitting at 2.3 seconds median, which is well above the 800-millisecond target the partner agreed to at launch. Customer-satisfaction scores have not moved compared to the pre-launch baseline.

**Cause.** Every call in the stack is using Opus. There is no per-step model selection in the architecture, because there was no per-step eval that would have made per-step selection necessary. The team defaulted to "the best available model" during build and never came back to revisit the choice once traffic was live.

**Contributing factors.** Three things compounded: The original architecture document did not include a model-tier decision at any step, so the implicit default carried through to deployment. Cost was reviewed monthly rather than determined during development, so the gap between projected and actual spend did not surface until weeks after launch. Extended thinking had been enabled on a routing classifier that did not need reasoning at all, and that setting added measurable latency and cost to every request that passed through the classifier.

**What the team changed.** The team built an eval set retroactively, covering the work each pipeline step was actually doing. They routed the classifier step to Haiku and confirmed no regression on the eval. They routed mid-pipeline summarization to Sonnet and confirmed no regression there either. They kept Opus on the final response-composition step, which was the one place the eval said the higher tier earned its place. Monthly cost dropped 71%. Latency dropped to 940 milliseconds median. Customer-satisfaction scores remained unchanged.

### How a model-tier decision becomes a budget conversation

Three failure mechanisms compounded, and each one is recognizable in advance.

- **The first:** "no model-tier decision" was itself an implicit decision, and the system defaulted to the most expensive option. The absence of a deliberate choice is not neutral.
- **The second:** cost visibility lagged the build by weeks. The bill arrived after launch, after the partner had already gone live. That moved the cost conversation out of design and into change management.
- **The third:** the eval set didn't exist during the build, so when "use the best model" was proposed, the team had nothing to point to that would have grounded a different choice. The eval set is not just a release gate, it's the only thing that makes the tier decision defensible during the design conversation.

> **Why does this break?**
> 
> Not choosing a model is equivalent to choosing the most expensive one. An eval set feels like extra work upfront but it's also the only thing that makes the model decision defensible.

---

<!-- S23 -->

*Checkpoint · 9 min · Model & Context Strategy*

## Cost & latency calculator

Use the calculator to explore configurations. Set the model tier (Opus / Sonnet / Haiku), context strategy (monolithic / progressive), call volume per day, and extended thinking (on / off). The readouts show cost and latency for each setting. Your goal: find a configuration that meets both the cost ceiling and the latency budget at the same time, the two cannot be traded against each other. The calculator only displays values; it does not score your exploration. More than one valid configuration exists.

Model tier

Context strategy

Calls per day

Extended thinking

Estimated monthly cost

,

Median latency

,

Illustrative figures based on published list pricing as of June 2026 (current per-million-token input/output pricing for Opus, Sonnet, and Haiku, available at docs.claude.com). Verify current pricing and latency at docs.claude.com before relying on these numbers with a partner.

### Decision: identify the load-bearing control

Once you have a configuration where both readouts are within budget, ask: which single setting, if relaxed, would breach a budget first?

- **A.** The call volume, because it is the only input you cannot change.
- ✅ **B.** The dominant constraint's control, for example, if latency is the tight budget, the model tier or extended-thinking setting that drives latency.
- **C.** None; any setting can be changed freely once both readouts are green.

**Answer: B**

> Right. The load-bearing control is the one tied to whichever budget is binding. If latency is tight, the model tier and extended-thinking setting are load-bearing; if cost is tight, the tier and context strategy are. Naming it is what makes the configuration defensible rather than lucky.

Once you have a passing configuration and have selected the correct answer above: in 2–3 sentences, name the dominant constraint in your passing configuration and identify the single setting that is load-bearing for it. Write your answer, then reveal the model answer below.

*(Free-response exercise: Your rationale)*

**▸ Reveal the model answer**

The dominant constraint depends on which budget was tighter in your configuration. If latency is the binding constraint, the model tier and extended-thinking setting are load-bearing, those are the controls that most directly move latency. If cost is binding, the tier and context strategy are load-bearing. The load-bearing control is the one tied to whichever budget had the least margin. Naming it explicitly is what makes the configuration defensible rather than lucky.

**Course answer data:**
**WRONG_FB:**
- **A.** Call volume is a real input, but it is usually the least flexible one, not the load-bearing control. The load-bearing control is whichever setting most directly moves the budget that is closest to its limit.
- **C.** Once both readouts are green you still have a binding constraint, it is just not visible until you relax a setting and watch which budget breaks first. "Any setting freely" ignores that the two budgets are not independent.

---

<!-- S24 -->

*Teaching · 10 min · Prompting as Architecture*

## Designing system prompts, templates, and guardrails

The model and context screen covered choosing a model tier and a context strategy. The other major lever in that decision area is the prompt itself. At enterprise scale the prompt is not a sentence you type, but an asset you design: a system prompt, a reusable template, and the guardrails that keep both safe and consistent. This is the first of three screens on prompting as an architectural discipline.

### System-prompt architecture for enterprise reuse

A system prompt for a one-off chat and a system prompt that hundreds of requests a day depend on are different artifacts. The enterprise version is designed for reuse, which means it has structure: a clear statement of role and scope, the constraints the model must hold (what it must not do, what it must always do), and an output contract that names the shape the response has to take. When a system prompt is reused at scale, ambiguity is a defect multiplied across every request.

### Templates: consistency and safety, enforced

A template is a system prompt with parameterized slots (the parts that change per request) and fixed scaffolding around them. The design goal is that the fixed scaffolding carries the consistency and safety guarantees, so that filling a slot cannot accidentally remove a constraint. A well-designed template makes the safe path the default path: the person using it supplies the variable content and inherits the guardrails without having to re-author them.

### Description: the 4D competency applied to prompt design

Description is one of the four AI Fluency competencies, the discipline of telling the model precisely what you want: the scope of the task, the format of the output, and the constraints that bound it. Applied to prompt design, Description is what separates a prompt that works in a demo from one that holds in production. A well-described prompt names:

- **The scope:** What is in and out of bounds
- **The format:** The exact output contract
- **The constraints:** The rules that must never be violated

Underspecification is a gap the model fills with its own assumption, differently each time, and is the key failure to watch out for.

### Diagnosing underspecification gaps

The architect's skill here is reading a prompt for what it fails to say. Where the prompt is silent, the model improvises and improvisation is exactly the non-determinism you do not want in a reused asset. Diagnosing the gap means asking, for each requirement the output must meet, whether the prompt actually states it or merely hopes for it. The fix is to make the implicit explicit: restate the goal alongside the instruction, name the format, and bound the constraints.

Cost · Complexity · Risk

**Cost:** A vague system prompt is paid for in every request that needs correction, retry, or human cleanup. Designing the prompt well once is far cheaper than diagnosing drift across thousands of calls.

**Complexity:** Templates concentrate complexity in one place where it can be reviewed and governed, instead of scattering it across ad-hoc prompts no one owns.

**Risk:** An underspecified guardrail is worse than a missing one, because it creates the appearance of a control without the substance. A constraint the model can quietly route around is not a constraint.

---

<!-- S25 -->

*Teaching · 7 min · Prompting as Architecture*

## Prompt engineering techniques across models

Once a prompt is designed for reuse, the next question is which technique to use inside it. The technique is chosen by the complexity of the task, not by habit. This screen covers the main techniques, how the choice changes across models, and how to avoid building bias into the prompt.

### Technique selection by task complexity

| Technique | What it is | When it fits |
| --- | --- | --- |
| **Zero-shot** | Instruction only, no examples. | Well-specified tasks the model already handles reliably; the default to try first. |
| **Few-shot** | A handful of input/output examples in the prompt. | Tasks where the desired format or judgment is easier to show than to describe. |
| **Chain-of-thought** | Prompt the model to reason step by step before answering. | Multi-step reasoning, arithmetic-like logic, or tasks where the path matters to the answer. |

The progression is deliberate: start zero-shot, add examples only if the task needs them, and add explicit reasoning only if the task's structure demands it. Each step adds tokens and latency, so reach for the lightest technique that meets the requirement.

### Behavioral differences across models

The same prompt does not behave identically across model tiers or generations. A more capable model may need less scaffolding (fewer examples, less explicit step-by-step instruction) to reach the same quality, while a less capable model may need more. A prompt tuned for one model is a starting point for another, not a finished artifact. This is why a model swap is treated as a release and gated with an evaluation: the prompt-model pairing is what you are actually shipping.

### Avoiding bias in prompt construction

Prompt construction can introduce bias the task never intended. Leading phrasing, unbalanced examples (few-shot sets that show only one kind of case), and assumptions baked into the instruction all steer the output in ways that can be easy to miss. The discipline is to phrase neutrally, balance examples across the cases the system will actually see, and check whether the prompt presumes an answer it should be eliciting.

### Checkpoint: technique-selection matrix

For each task below, select the technique (zero-shot / few-shot / chain-of-thought) and type a one-sentence reason. Both are required before submitting.

- Task 1. Classify a customer support ticket into one of five standard categories: billing, technical, returns, account, or general. → **Zero-shot**

- Task 2. Extract structured fields, date, vendor, and amount, from expense receipts that vary widely in layout and formatting. → **Few-shot**

- Task 3. Determine whether a multi-step contract clause creates a liability under three conditions that interact with each other. → **Chain-of-thought**

- Task 4. Summarize a 400-word product description into two sentences. → **Zero-shot**

Cost · Complexity · Risk

**Cost:** Heavier techniques cost tokens and latency on every call. Chain-of-thought on a task that does not need it is a recurring tax for no gain.

**Complexity:** Few-shot examples are content to maintain: as the task evolves, stale examples quietly steer the model wrong.

**Risk:** Bias introduced in the prompt is invisible in any single output and only shows up in aggregate, which is why neutral phrasing and balanced examples are a design requirement, not a polish step.

---

<!-- S26 -->

*Teaching · 8 min · Prompting as Architecture*

## Caching mechanics, modular prompts, and Skills

Reusable prompts raise a question the one-off prompt never does: how do you reuse them efficiently, and how do you package them so a team can share and govern them? This screen covers the mechanics of caching, the difference between a modular prompt library and a Skill, and the decision of which to use.

> **A cache that never hits**
> 
> A team put their reusable analysis prompt into production and saw none of the cost savings caching was supposed to bring. The cause was ordering: they had placed the per-request content (the document being analyzed) at the top of the prompt, ahead of the large fixed instruction block. Because the cache matches on a stable prefix, putting dynamic content first meant the prefix changed on every request and the cache never hit. The fix was to reorder with fixed content first and dynamic content last.

### Caching mechanics an architect designs around

**▸ Cache breakpoints**

Caching works on a stable prefix. Mark the boundary between the fixed part of the prompt (cacheable) and the variable part (not), and keep the fixed part genuinely fixed.

**▸ Content ordering**

Static before dynamic, always. The large, unchanging instruction block goes first; the per-request content goes after the breakpoint.

**▸ TTL selection**

Match the cache lifetime to how often the fixed content actually changes and how frequently the prompt is called. A prompt called constantly benefits from a longer-lived cache; one called rarely may never amortize the write.

**▸ When the write overhead is not worth it**

Writing to the cache has its own cost. If a prompt is called infrequently or its fixed portion is small, caching can cost more than it saves. Caching is a design decision, not a default to switch on everywhere.

### Modular prompt libraries vs Skills as versioned reusable units

There are two ways to make a prompt reusable across a team. A modular prompt library is a shared collection of prompt fragments and templates that engineers assemble in their own code. A Skill is a more formal, versioned, self-contained unit: a SKILL.md that packages the instructions, optional executable scripts, and version management, so the whole procedure travels as one governed artifact. A Skill is the reuse primitive named in the foundations screen (packaging a repeatable procedure) applied to prompting.

### The reuse decision: library or Skill

| Consideration | Lean toward a prompt library | Lean toward a Skill |
| --- | --- | --- |
| **Repeatability** | An assembled, often-tweaked prompt per use. | A stable procedure run the same way every time. |
| **Distribution** | Shared within one codebase or team. | Distributed across teams or products that need the same procedure. |
| **Governance** | Lightweight; engineers own the fragments. | Needs versioning, approval, and rollback, Skills carry that. |

Cost · Complexity · Risk

**Cost:** Caching can cut cost substantially when it hits and add cost when it does not. The economics depend on call frequency and prefix size, so model them before committing.

**Complexity:** A Skill concentrates a procedure into one versioned unit that can be reviewed and rolled back; a sprawl of copy-pasted prompts cannot.

**Risk:** An ungoverned prompt that is copied across teams drifts into many slightly different versions, each with its own quietly different behavior. Versioned reuse is the control.

---

<!-- S27 -->

*Exercise · 6 min · Prompting as Architecture*

## Author the reusable prompt asset

> **The brief**
> 
> A partner's support organization runs the same operation hundreds of times a day: given a customer's support ticket and the relevant section of the product manual, produce a drafted reply that follows the partner's tone guidelines, cites the manual section it relied on, and never promises a refund or a timeline the agent has not approved.

Draft the reusable prompt asset. Make the three design decisions below and write a brief rationale for each:

1. Where does the stable prefix end and the per-request content begin? Name the breakpoint placement and explain why.
2. How do you enforce the never-promise-a-refund guardrail structurally, not just as a stated instruction? Describe the output contract constraint.
3. Should this ship as a template or a Skill? Name the packaging choice and state the reason.

Write your answer, then reveal the model answer below. Feel free to ask Claude to compare what you've written with the provided answer.

*(Free-response exercise: Your prompt asset design)*

**▸ Reveal the model answer**

**Cache-breakpoint placement:** Put the role, tone rules, output contract, and never-promise guardrail first as the stable prefix, then the ticket and manual section as the only per-request content. Dynamic content before the breakpoint means the prefix changes on every call and the cache never hits. At hundreds of calls a day, the stable prefix is where the cost savings live.

**Enforcing the guardrail:** Build it into the output contract as a structural constraint the format requires, not as a sentence in the role text. A rule stated in the role can be drifted past. A constraint built into the output contract shapes the response format and cannot be quietly ignored.

**Packaging:** A versioned Skill. The procedure is stable, run identically hundreds of times a day across the support org, and needs versioning and rollback. A pasted prompt template each agent keeps locally has no central governance, cannot be rolled back, and drifts into slightly different versions over time.

---

<!-- S28 -->

*Teaching · 11 min · Entry Points & Governance*

## Entry point, route, and governance selection

You've chosen the model and the shape, and now it is time to choose how a partner consumes Claude. Choosing how a partner consumes Claude involves three separate decisions, made in sequence. Getting them in the right order prevents the most common architecture mistakes.

- Which entry point fits the work?
- Which build-time interface suits the team?
- Which delivery route fits the partner's cloud commitments?

The three layers (entry points, build-time interfaces, and delivery routes) were taught as vocabulary in the foundations section. This screen is the selection work: choosing among them under real constraints.

### Claude entry points: how you interact with Claude

An entry point is the wrapper that decides who can talk to Claude, what Claude can touch, and how much engineering the partner must do to get there. Think of entry points as the same intelligence packaged for different jobs. Picking the wrong entry point doesn't break the work, but it adds friction the partner will feel every day.

Beyond Claude.ai and Claude Code, Anthropic ships three entry points that extend Claude into specific applications or environments. Before building partner workflows that depend on any of them, verify the current capabilities, supported configurations, and availability against Anthropic's documentation.

**▸ End-user entry points**

| Entry point | Description | Audience and use | Core tradeoff |
| --- | --- | --- | --- |
| **Claude.ai** (web, mobile, and desktop apps) | The end-user chat product. A signed-in user opens a conversation, attaches files, uses Projects for shared context, and connects services like Slack, Outlook, or Google Drive through built-in connectors. It comes in consumer tiers (Free, Pro, Max) and in Claude for Work. Claude for Work has two tiers. The Team tier adds admin controls, SSO and SAML, domain capture, and a contractual commitment not to train on customer content. The Enterprise tier adds SCIM provisioning, configurable retention, audit logs, a Compliance API, and a HIPAA-ready option with a signed BAA. | For knowledge workers using Claude as a thinking partner for research, drafting, analysis, and review. No code is written. The web app, the mobile app, and Claude Desktop all reach the same Claude.ai product. This is the entry point for applied AI users, not builders. The consumer tiers fit individuals and small teams and Claude for Work fits organizations that need governance and identity controls on the same product. | Zero build cost vs. zero integration entry point: You get the product Anthropic ships and you cannot embed it in another product or customize what gets exposed. The right tier depends on governance needs: consumer tiers for low-sensitivity work, Claude for Work where admin controls, SSO, and no-training commitments are required. |
| **Claude Code** (terminal, IDE plugin, desktop, web) | An agentic coding tool that reads files, edits code, runs commands, and executes multi-step engineering tasks under configurable permission boundaries. | For engineers doing real development work: exploring codebases, refactoring across files, debugging, building features. The product runs in a terminal, in IDE plugins (VS Code, JetBrains, others), on the desktop, and on the web at claude.ai/code. Same agent, wherever you work. | Purpose-built for engineering: Outstanding option for code but could be the wrong shape for a customer-service product or any non-engineering workflow. |
| **Claude Cowork** | A desktop agent for non-developers that works with local files and applications, automating file and task management on the user's machine under configurable permissions. | For operations, admin, and other non-engineering roles who need Claude to take actions on their computer rather than just produce text in a chat window. Available on all paid plans (Pro, Max, Team, Enterprise) via the Claude Desktop app on macOS and Windows; Linux support is in beta. | Real system actions vs. supervision overhead: Powerful for file and task automation because Cowork operates on the user's machine directly, with the consequence that permission scoping and human review matter more than they do in a chat-only entry point. |
| **Claude in Chrome** | A browsing agent that operates inside the Chrome browser, navigating pages and taking actions on behalf of the user. | Knowledge workers whose tasks are anchored in web applications rather than in files or codebases. | N/A |
| **Claude for Excel** | A spreadsheet agent that operates inside Excel, working directly with cells, formulas, and structured data. | Analysts, finance teams, and any role whose primary working tool is a spreadsheet. | N/A |

### Build-time interfaces: how you program against Claude

Once an entry point is picked, the next decision is which programmatic layer the partner's code talks to. The table below describes the four build-time interfaces. The API, SDKs, MCP, and the Agent SDK are not alternatives to each other in every case, they layer on one another.

**▸ Build-time interfaces**

| Interface | Definition | Audience and purpose | Tradeoff |
| --- | --- | --- | --- |
| **Direct API** | The direct HTTP interface to Claude. A developer authenticates, sends a request with messages, a model name, and parameters, and gets a response back. | For teams building Claude directly into their own product. The partner's team owns everything: retries, streaming, tool use, observability, and the UI. It's the most foundational build-time interface, and the layer everything else sits on. | Maximum control vs maximum responsibility: Use this when an SDK has not exposed a feature you need, or when the team prefers raw HTTP. |
| **SDKs** (Python, TypeScript, Java, Go, Ruby, C#, PHP) | SDKs offer the same capability as the API, wrapped in language-native types and helpers that cut down on boilerplate. They handle authentication, request formatting, retries, streaming, and tool-use plumbing in idiomatic code. The agent loop, if any, is still the partner's code. | For teams using the same use case as the direct API, but the team wants language-native types, less boilerplate, and built-in ergonomics for streaming and tool use. Default choice for embedding Claude inside a product. | Ergonomics vs. control: SDK abstractions move at Anthropic's release cadence. If you need a raw API feature the SDK hasn't exposed yet, you'll drop back to HTTP anyway. |
| **MCP** | An open protocol for exposing tools, prompts, and resources from one server so any MCP-aware client including Claude.ai, Claude Code, the API, or a third-party client can discover and use them.<br>Not a calling convention for Claude in a single product, but a sharing convention across products. | Not a calling convention for Claude in a single product, but a sharing convention across products. For teams that need the same tools reachable from multiple Claude clients. The same tool entry point is needed in two or more clients: Claude.ai, Claude Code, an internal app, a partner's product. Build the server once, connect it everywhere. | Reusability across clients vs. added architectural complexity: If only one client will ever use it, MCP adds overhead without much payback. |
| **Agent SDK** (@anthropic-ai/claude-agent-sdk) | Running a managed agent loop, the same loop that powers Claude Code, from the partner's own application code. The package handles iteration, tool execution, and termination. Currently TypeScript (@anthropic-ai/claude-agent-sdk on npm) and Python (claude-agent-sdk on PyPI). | For teams that need Claude to act over multiple turns inside the partner's own product, with the partner's application controlling the surrounding workflow, and the Claude Code CLI is the wrong shape. Common case: an internal agent embedded in a web app, not a terminal tool. | Managed loop vs. custom orchestration: The Agent SDK handles iteration and termination, but the partner gives up fine-grained control over the loop itself. |

### A way to keep these terms separate

**API and SDK: the same entry point, different ergonomics.** The API and the SDK are the same entry point from Claude's perspective. The SDK is an opinionated wrapper stacked over the API. It adds language-native types, handles streaming and tool-use boilerplate, and lets the partner's team work in their preferred stack (Python, TypeScript, Java, Go, Ruby, C#, or PHP) rather than against raw HTTP. The SDK is the default for most teams. The only reason to drop to raw HTTP is when a freshly shipped API feature hasn't made it into the SDK yet.

**MCP and API tool use: different layers, not alternatives.** MCP is the protocol for sharing tools across entry point, how a tool entry point is exposed and discovered across multiple clients. API tool use is how Claude calls a tool inside a single request. MCP and API tool use are not alternatives. Under the hood, an MCP server exposes tools that any MCP-aware client can call using API tool use. The choice comes down to how frequently you're going to reuse the feature: pick MCP when one tool entry point needs to be reachable from multiple Claude clients; pick raw API tool use when the tools live inside one product only.

**Claude Agent SDK: when a partner needs an agent loop they can embed in their own product.** Partners and engineers often use "SDK" to mean either the Anthropic SDK or the Agent SDK depending on context. The Anthropic SDK is a convenience wrapper over the API. It handles boilerplate but does not run an agent loop. The Agent SDK is the managed runtime that runs the loop, the same one that powers Claude Code. The model picks a tool, runs it, sees the result, and keeps going until the task is done or a stop condition fires. The partner calls it from their own application code, and the SDK handles the rest. Which layer to use comes down to what Claude needs to do: one request, one response? Use the API or SDK. Reusable tools across multiple clients? Use MCP. Claude acting across multiple turns inside the partner's own product? Use the Agent SDK. The three layers work together, not against each other.

### Claude Code: customization and governance layers

Choosing Claude Code is the start of a second decision: which customization belongs at which layer. A layer, in this context, is a discrete configuration entry point that controls one aspect of how the agent thinks or acts: each one is independent, composable, and applied at a different point in the agent's execution. The layers fall into two groups: shape what the agent knows and does (CLAUDE.md, skills, subagents, MCP), and govern what the agent is allowed to touch (Hooks, permission boundaries, approval flows, sandboxing, and restricted execution). Shaping layers and governing layers are distinct. Getting this split right is what makes an agent both useful and safe to run in production.

**▸ Claude Code customization and governance layers**

| Layer | What it does | When it belongs here |
| --- | --- | --- |
| SHAPING: What the agent knows and does |
| **CLAUDE.md** | A markdown file loaded into context at session start. Sets standing instructions, project conventions, and background knowledge the agent should always have. | Persistent context that applies to every task in the project (coding standards, repo layout, team conventions). |
| **Skills** | Markdown-defined procedures Claude Code can invoke on demand rather than loading upfront, keeping the main context lean. | Repeatable workflows the team should not have to spell out each time. Typical examples are a commit-push-PR flow, a release-notes generator, a schema-migration procedure. |
| **Subagents** | Agent calling and creating additional agents to parse out sections of a task or isolated context-window helpers for bounded tasks like code review or codebase exploration that would otherwise clutter the main thread. | Work that should run with read-only tools, a restricted tool entry point, or a different system prompt from the main session. |
| **MCP servers** | External tools and data entry points connected to Claude Code over the standardized protocol. | When the same tool entry point needs to be reusable across clients, for example when the team's Linear MCP server should also work from Claude.ai. |
| GOVERNING: What the agent is allowed to touch |
| **Hooks** | Scripts that fire on Claude code lifecycle events (e.g. before/after a tool runs, at session start, on stop), used as deterministic gates the agent cannot skip. | Deterministic gates the agent must not skip, where the guarantee has to come from code rather than from prompting. |
| **Permission boundaries and approval flows** | Six permission modes control what Claude Code can do without prompting. Default asks before each action. acceptEdits approves file edits and common filesystem commands (mkdir, touch, rm, mv, cp, sed), though other Bash commands still prompt. Plan mode locks the session to read-only until the user approves a plan. Auto mode uses a classifier to approve safe actions and block risky ones; it is a research preview that works on all plans (admin-enabled on Team and Enterprise) and defaults to the Anthropic API as provider. An environment variable enables CSP providers. dontAsk auto-denies anything that would prompt and runs only what your allow rules cover, which makes it the mode for locked-down CI. bypassPermissions skips all checks and is scoped to containers or CI only. | Any environment where the cost of an unintended action is non-trivial. Permissions govern what the agent is allowed to touch. Hooks govern what must happen before or after an action. |
| **Sandboxing and restricted execution** | Containment around the workspace in which Claude Code runs, including filesystem boundaries, network egress rules, and constrained command surfaces. | Any deployment where a wrong action would have real consequences and where approval prompts alone are not a sufficient backstop. The environment itself should enforce the boundary, not just the agent's judgment. |

### CSP delivery routes: where API traffic terminates

Once the entry point and build-time interface are picked, one more decision sits underneath: where does the API traffic terminate? The same Claude model is available through four delivery routes. What differs is which cloud account the spend lands in, which identity system handles authentication, which region the traffic terminates in, and which procurement contract the partner has already signed. The decision rule is not about technical capability, the model behaves the same way on each route. The rule is about what the partner has already committed to.

If the partner already has a long-term AWS contract, Bedrock is usually the easiest path, the AI spend falls under the same agreement they already have, and the identity system their team uses (IAM) works as-is. The same logic applies to Vertex AI on GCP and Foundry on Azure: if the partner lives in that cloud, use that route. The direct Anthropic API is the right call when the partner has no strong cloud preference, wants new features the moment they ship, or prefers to keep AI spend with Anthropic directly. One tradeoff: CSP-mediated routes (Bedrock, Vertex, Foundry) tend to lag the first-party API on new features by weeks, sometimes longer for major capabilities.

**▸ CSP delivery routes**

| Delivery route | What it is and how the partner reaches it | When to pick |
| --- | --- | --- |
| **Anthropic first-party** | The direct Anthropic API at api.anthropic.com, billed by Anthropic, and authenticated with an Anthropic API key. SDKs in Python, TypeScript, C#, Java, Go, PHP, and Ruby wrap this entry point. | Partner has no binding cloud commitment, wants newest features the day they ship, or prefers to consolidate AI spend directly with Anthropic. Default choice when no procurement constraint is pulling the other way. |
| **AWS Bedrock** | Claude served as a managed model on AWS. Called via the Messages API at /anthropic/v1/messages on AWS-managed infrastructure, billed on the partner's AWS account and authenticated through IAM. The previous Bedrock Runtime integration (InvokeModel/Converse via boto3 or the AWS SDK) remains available as the documented legacy path. Regional availability matters and inference profiles solve the cross-region routing problem. | Partner has a committed AWS enterprise agreement, runs the rest of their stack on AWS, and wants AI spend to draw down against that commitment. Identity, networking, and audit all inherit from the existing AWS account. |
| **GCP Vertex AI** | Claude served as a managed model in Google Cloud's Vertex AI Model Garden. Called via the Anthropic Vertex client or Google's SDK, billed on the partner's GCP project, authenticated with Google Cloud credentials. Models are enabled per project in the Model Garden console. | Partner runs on GCP, the rest of their ML stack lives in Vertex AI, and they want a single billing and audit entry point across foundation models. |
| **Microsoft Foundry (Azure)** | Claude served through Microsoft's Foundry catalog on Azure. Billed on the partner's Azure subscription, authenticated through Entra ID, deployed into the partner's Azure region. | Partner has a Microsoft enterprise agreement, runs identity through Entra ID, and the rest of their cloud footprint is on Azure. Foundry consolidates AI procurement on the same paper. Note: Foundry offers Claude models in two hosting forms: Hosted on Azure (generally available, inference runs in the partner's Azure environment; as of this writing Opus 4.8, Sonnet 5, and Haiku 4.5, verify the current list at publish time) and Hosted on Anthropic infrastructure (other models, inference routes to Anthropic-managed infrastructure). Partners with strict data residency or GDPR requirements should verify the hosting form and compliance posture of the specific models they deploy before committing to this route. |

**What does not change across routes.** The Claude model itself is the same regardless of route. Prompting, evaluation strategy, tool use, and context-window behavior all transfer. What changes is the wrapper: model identifiers and version strings differ across routes, regional availability differs, and CSP-side features that wrap inference (such as inference profiles on Bedrock, model deployments in Foundry, and Model Garden access controls in Vertex) all add concepts the Architect needs to know exist even if the partner's engineering team owns the implementation.

### Skills as an integration mechanism

Skills are an integration mechanism, not only a packaging one. A Skill can be attached to a request through the container.skills parameter, published and versioned through the /v1/skills endpoint, and managed under version control like any other deployed asset. Skills require the Code Execution Tool to run, which means the integration pattern carries a sandboxed execution environment dependency. When the integration decision is how a reusable procedure reaches Claude across entry points, a versioned Skill is one mechanism to weigh alongside MCP and direct tool use.

Cost · Complexity · Risk

**Cost:** Each entry point carries a non-trivial integration cost. Don't pick more than one unless the partner's use case spans them.

**Complexity:** The two most common mistakes are reaching for Claude Code on non-engineering work and treating MCP as the default integration layer regardless of whether the reusability it offers is needed. The entry point should follow the work, not precede it.

**Risk:** Outgrowing the wrong entry point is expensive, not just because of the code that has to be rewritten, but because of the conventions and user habits that built up around it. Starting over on a better entry point is cheaper than that and starting on the right one is cheaper.

### Security, governance, and regulated-industry constraints

Some entry point decisions are not at your own discretion. When a partner is subject to attorney-client privilege, HIPAA, GDPR, FedRAMP, or an internal data-residency policy, those constraints rule entry points in or out before cost, ergonomics, or build effort enter the conversation. Claude.ai is the entry point this hits most often. The consumer-grade product was not designed to satisfy every enterprise data-handling requirement out of the box. The API and SDK, routed through a partner-approved gateway with logging, retention, and identity controls in the partner's own infrastructure, are the entry points that survive most regulated reviews. Name the governing constraint when you recommend an entry point and let the constraint eliminate options before preferences do.

**▸ Regulated-industry constraints**

| Constraint | What it tends to rule out | What usually survives review |
| --- | --- | --- |
| **Attorney-client privilege** | Consumer tiers of Claude.ai for privileged document review, and anything that touches privileged material through a surface the firm cannot audit end to end. Claude for Work adds admin controls and audit logging, but a firm still has to confirm the configuration meets its own privilege-handling bar before privileged material flows through it. | API or SDK behind the firm's own application, authenticated via SSO, routed through a firm-approved LLM gateway that logs every request. The firm owns the audit trail end to end, which is what privilege review turns on. |
| **HIPAA (PHI handling)** | Any entry point where a Business Associate Agreement is not in place for the specific configuration the partner is using. A BAA that exists for one configuration does not extend to another, so an uncovered route is ruled out even when the partner holds a BAA elsewhere. | API or SDK on a BAA-covered configuration via the delivery route the partner is already using. BAA existence is not sufficient because feature eligibility matters. Beta features are generally excluded from BAA coverage unless explicitly listed as eligible. |
| **GDPR & data residency** | Delivery routes where the region of model execution cannot be pinned, and routes where data leaves the approved geographic boundary at any step. | A CSP-mediated delivery route (Bedrock or Vertex) with the region pinned to a covered jurisdiction and DPA terms inherited from the existing cloud contract. Foundry is the route to check here, because its residency guarantees are not something this course can confirm. Verify with the Foundry route's current documentation before relying on it for residency. |
| **FedRAMP / government** | Any path that is not on an authorized cloud environment at the required impact level. | Claude for Government (C4G) for FedRAMP High civilian workloads. Bedrock GovCloud for FedRAMP High and DoD IL4/5. Vertex Assured Workloads for FedRAMP High and IL2. Note: authorized government environments run on a model lag, so the newest Claude models reach GovCloud and Assured Workloads after the commercial release. Confirm which model the route offers before committing to it. |
| **Internal data-residency policy** | Routes outside the partner's approved cloud vendor list, regardless of the underlying technical capability. | The delivery route on the partner's approved CSP. This is procurement, not engineering: the right route is whichever one their CIO has already cleared. |

Note: Always verify current authorization scope for each of the constraints with Anthropic before committing.

> **Forward pointer**
> 
> Module 3 (Responsible AI, Safety and Risk for Architects) goes deep on guardrail design, data handling, and the full regulated-industry framework. The role of this section is to surface the constraint at the point in the design conversation where it eliminates options, which is right here at the entry point and delivery-route decision.

---

<!-- S29 -->

*Watch Out · 4 min · Entry Points & Governance*

### When Claude Code got picked outside engineering

> **Setup hook**
> 
> Claude Code makes a strong first impression. It can execute complex, multi-step engineering tasks in a fraction of the time a developer would spend manually, and that capability is hard to unsee. The risk is that this leads teams to reach for Claude Code by default, even when the work doesn't require it and a simpler integration or Claude alone would be sufficient. The diagram below was a real handoff from a partner asking us to validate their design.

### The proposed architecture: regional bank operations assistant

A regional bank wanted what they called an "operations assistant" for their branch staff. The work required looking up customer balances, scheduling appointments, and answering policy questions. The proposed architecture had three components:

- Claude Code running on branch laptops, with a CLAUDE.md file maintained per branch to encode local conventions.
- MCP servers for the customer database, the appointment system, and the policy corpus, each exposed via the standardized protocol.
- Subagents handling compliance checks on every interaction, with their own restricted tool entry point.

### The annotation across the diagram

- [ ] Claude Code on branch laptops (per-branch CLAUDE.md)

Engineering

entry point

for an operational workflow

Branch staff do not run terminals; the entry point is mismatched with the user

↓

- [ ] MCP servers: customer database, appointment system, policy corpus

MCP earns its place only when reused across clients

No other Claude clients existed in this bank

↓

- [ ] Subagents run compliance checks on every interaction

Compliance assigned to the weakest deterministic guarantee

High-consequence path should not run on subagents

The annotation in red across the whole diagram reads: this is an engineering entry point for an operational workflow. Branch staff do not run terminals, so the entry point itself is mismatched with the user. Compliance is a high-consequence path and should not run on subagents, which provide weaker deterministic guarantees than server-side code. The customer database does not need to be exposed over MCP just because MCP was on the menu for the entry point; MCP earns its place when the same tool entry point is reused across clients, and in this case there were no other clients in the bank.

The architecture that fits the work is a custom web application calling the API directly. Compliance lives in deterministic server-side code where the guarantees are explicit rather than emergent. The user interface is authenticated via the bank's SSO and fits a banking workflow rather than a developer workflow. Tool calls are audited at the server boundary. That architecture was the right answer from screen one.

### Three failure mechanisms, each visible in the original proposal

**The first: the entry point was chosen before the user was named.** Branch staff need an interface that fits a banking workflow, not a developer tool. That constraint should have determined the entry point before any other decision was made.

**The second: MCP was carried forward from a prior project as a default integration layer.** The reusability argument that justifies MCP didn't apply here. There were no other Claude clients in the bank that would consume the same tool entry point. The protocol layer was paying integration cost for a capability the partner didn't need.

**The third: compliance, the highest-consequence path in the system, was assigned to the entry point with the weakest deterministic guarantees.** The pattern was inverted. The work that most needed code-level certainty was running on the entry point furthest from it.

> **Why does this break?**
> 
> Entry point choice should follow the user and the work. Reaching for Claude Code or MCP just because the last project used them is paying for capabilities the partner does not need.

---

<!-- S30 -->

*Checkpoint · 7 min · Entry Points & Governance*

## Pick the entry point and name the deciding tradeoff

For each partner scenario, choose the option that names both the right entry point AND the tradeoff that drives the choice. A right entry point paired with the wrong reason is not correct, the reasoning is what's being tested. A worked example is shown for scenario 1; you complete scenarios 2 through 6.

> **Scenario 1, worked example**
> 
> A non-engineering operations team needs a chat assistant over approved internal docs.
>  **Correct choice: claude.ai with a Project**, because the deciding tradeoff is audience: a non-technical team needs a ready-made entry point, not a build-time interface.

**Scenario 2.** A regional bank wants to deploy a loan officer assistant that retrieves customer account data from a core banking system and generates draft loan summaries. The bank runs on AWS and has an existing enterprise agreement.

- ✅ **A.** AWS Bedrock, because the deciding tradeoff is integration depth: the assistant needs programmatic access to core banking data and must embed into the bank's existing AWS infrastructure.
- **B.** claude.ai Enterprise, because the deciding tradeoff is integration depth: the bank needs a governed product with SSO and audit controls.
- **C.** Direct API, because the deciding tradeoff is integration depth: the direct API gives the most control over how requests are built.

**Answer: A**

**Scenario 3.** A law firm wants to use Claude to assist attorneys reviewing privileged documents. The firm's general counsel has determined that all AI tooling touching privileged material must run behind the firm's own audit infrastructure.

- **A.** claude.ai Enterprise, because the deciding tradeoff is governance/control: Enterprise adds SSO, audit logging, and admin controls.
- ✅ **B.** Direct API or SDK behind the firm's own application and gateway, because the deciding tradeoff is governance/control: the firm must own the audit trail end to end, which requires routing through infrastructure the firm controls.
- **C.** AWS Bedrock, because the deciding tradeoff is regulatory residency: Bedrock provides regional data handling that satisfies privilege requirements.

**Answer: B**

**Scenario 4.** A global logistics company wants to give warehouse operations staff a Claude assistant for shift handoff notes and equipment checklist completion. The staff are non-technical and work from shared tablets on the floor.

- **A.** Direct API with a custom-built interface, because the deciding tradeoff is integration depth: a custom build gives full control over the experience.
- ✅ **B.** claude.ai with a Project, because the deciding tradeoff is audience: non-technical staff need a ready-made interface they can use without training, and Projects provide the shared context the team needs.
- **C.** Claude Code, because the deciding tradeoff is audience: Claude Code runs on tablets and gives staff direct access to Claude's capabilities.

**Answer: B**

**Scenario 5.** A healthcare network needs to deploy a clinical documentation assistant that processes patient records. The network holds a BAA with AWS and has confirmed Bedrock is covered under that agreement. A competing proposal suggests using the direct Anthropic API with a separately negotiated BAA.

- **A.** AWS Bedrock, because the deciding tradeoff is regulatory residency: Bedrock pins data to a US region which satisfies HIPAA.
- **B.** Direct Anthropic API with a separately negotiated BAA, because the deciding tradeoff is governance/control: the direct API gives more control over how PHI flows through the system.
- ✅ **C.** AWS Bedrock, because the deciding tradeoff is governance/control: the network's existing BAA covers this configuration, which eliminates the compliance risk before any other tradeoff applies.
- **D.** claude.ai Enterprise with a BAA, because the deciding tradeoff is governance/control: Enterprise adds HIPAA-ready configuration and audit controls.

**Answer: C**

**Scenario 6.** A financial services firm is building a high-frequency trade commentary system. The system must generate a short natural-language summary of each trade within 400 milliseconds of execution. The firm runs on GCP.

- ✅ **A.** Google Vertex AI, because the deciding tradeoff is latency: the 400ms requirement demands the lowest-latency path, and Vertex AI keeps the request path inside the firm's existing Google Cloud environment, minimizing network round-trip.
- **B.** Direct Anthropic API, because the deciding tradeoff is latency: the direct API has the fastest feature releases and lowest overhead.
- **C.** AWS Bedrock, because the deciding tradeoff is latency: Bedrock's managed infrastructure is optimized for low-latency inference.

**Answer: A**

---

<!-- S31 -->

*Checkpoint · 7 min · Assembly & Recap*

## A contract-review system for a mid-market law firm

Four complete architectures are described below. Each one commits to all five design decisions the module covered: the platform entry point, the pattern, how the work is split across Claude, existing systems, and humans, the model and context strategy, and the human-in-the-loop posture. Only one holds up against the brief. The other three each look reasonable but fail on a single decision. Pick the one you would put in front of a partner-side review committee.

> **The brief**
> 
> A 180-lawyer mid-market law firm wants to speed up contract review. Their senior associates currently spend an estimated 12 to 18 hours per week reading vendor and partnership contracts to flag clauses that conflict with the firm's standard playbook. Average contract length is 35 pages. The current output is a redlined PDF with margin comments. The firm uses iManage for document storage, has a private LLM gateway approved by their CIO, and is bound by attorney-client privilege requirements that exclude consumer-grade tools. The target is to cut associate time per contract by 60% while keeping the senior associate as the final reviewer.

### Step 1: draft your architecture

Before reading the four options, draft your own architecture for the law firm. In one paragraph, cover all five decisions: the platform entry point, the pattern, how the work is split across Claude and existing systems, the model and context strategy, and the human-in-the-loop posture.

Click-to-reveal an answer to compare with your response; feel free to ask Claude to compare what you've written with the provided answer.

*(Free-response exercise: Your architecture)*

**▸ Reveal the model answer**

Build on the direct API or SDK, embedded in a thin internal web app that authenticates via the firm's SSO and routes through the approved LLM gateway. A parallelized workflow reviews the contract section by section, with an evaluator pass enforcing a strict schema on the flagged-clauses output. Claude handles extraction, classification against the playbook, and draft redlines. The playbook stays in the firm's systems as a versioned source of truth, retrieved per clause at call time. iManage handles document fetch. Sonnet is the default with progressive context, extended thinking enabled per clause only where an eval set justifies it. The senior associate signs off on every output, and low-confidence clauses are flagged for attention.

### Step 2: which of the four options matches your design most closely?

- **Option A.** Build on Claude.ai, with associates uploading each contract into a Project that holds the playbook as reference files. A parallelized workflow reviews the contract section by section and aggregates the flagged clauses. Sonnet is the default model with progressive context. The senior associate reviews every output before anything goes to a client.
- **Option B.** Build on the direct API or the SDK, embedded in a thin internal web app that authenticates via the firm's SSO and routes through the approved LLM gateway. The playbook is loaded into the system prompt in full on every call so the model always has the firm's standard in context. A parallelized workflow reviews the contract by section and aggregates results. Sonnet is the default. The senior associate reviews every output.
- **Option C.** Build on the direct API or the SDK, embedded in a thin internal web app behind SSO and the approved gateway. An open-ended agent is given the contract and the iManage tools and left to decide for itself how to work through the document. The playbook is retrieved per clause at call time. Opus runs on every call for maximum accuracy. The senior associate reviews every output.
- ✅ **Option D.** Build on the direct API or the SDK, embedded in a thin internal web app that authenticates via SSO and routes through the approved gateway. A parallelized workflow reviews the contract section by section, with an evaluator pass enforcing a strict schema on the flagged-clauses output. Claude handles extraction, classification against the playbook, and draft redlines. The playbook stays in the firm's systems as a versioned source of truth, retrieved per clause at call time. iManage handles document fetch. Sonnet is the default with progressive context, extended thinking enabled per clause only where an eval set justifies it. The senior associate signs off on every output, and low-confidence clauses are flagged for attention.

**Answer: D**

> **A.** Claude.ai is the privilege failure. The firm is bound by attorney-client privilege requirements that exclude consumer-grade tools, so the entry point is wrong before any of the downstream choices matter. The pattern, model, and human gate in this option are all reasonable, which is what makes the entry point mistake easy to miss. Re-read the entry point-selection section, then choose again.
> **B.** This one gets the entry point, pattern, model, and human gate right, but it loads the entire playbook into the system prompt on every call. That is the knowledge-limitation failure: the playbook changes and a copy frozen in the prompt goes stale, and it pays to reprocess the whole playbook on every request. The fit move is to keep the playbook in the firm's systems as a versioned source of truth and retrieve the relevant sections per clause. Re-read the decomposition section, then choose again.
> **C.** The entry point and the human gate are right, but two decisions break it. An open-ended agent here is the "we want flexibility" failure: the work decomposes cleanly into independent sections, so a parallelized workflow fits and the agent's open-endedness is paid for and never used. Running Opus on every call is the bill-arrived failure: Sonnet is the default, and you move up only when an eval set says you have to. Re-read the pattern and model-selection sections, then choose again.
> **D.** This architecture would hold up to a partner-side review committee. The entry point respects privilege and fits the users, the parallelized workflow matches work that splits cleanly by section, the playbook stays where it can be versioned and is retrieved per clause, Sonnet with progressive context holds the cost line as document volume grows, and the senior associate stays the final reviewer with low-confidence clauses surfaced for attention. Every decision constrains the next, and this is the only option where all five hold together.

---

<!-- GLOSSARY -->

*Reference · Assembly & Recap*

## Glossary

The key terms used across this module, in alphabetical order. Click a term to expand its definition.

**▸ Adaptive thinking**

Extended thinking where the model itself, rather than you, decides whether to think and how much, based on the complexity of each request. It can reason at length on a hard problem and skip thinking entirely on a trivial one. You steer it with an effort level rather than configuring a token budget. On current Claude models it is the recommended control, and on the newest models it is the only one.

**▸ API**

Application Programming Interface. The direct way to send requests to Claude from your own code, with full control over the prompt, the model, the parameters, and how the response is handled. Using the API means you are building the surrounding application yourself: the user interface, the conversation history, the error handling, the logging. The tradeoff is maximum flexibility in exchange for owning the infrastructure around it.

**▸ Authoritative**

Authoritative means the source you have agreed to treat as correct: the partner's system of record, the live policy table, the current price list. When an answer is authoritative, it comes from that trusted source rather than from the model's recollection, so you can stand behind it.

**▸ Claude Agent SDK**

A managed agent runtime distributed as the @anthropic-ai/claude-agent-sdk package for TypeScript and Python. It gives a partner programmatic access to the same agent loop that powers Claude Code: iteration, tool execution, observation, termination, so the partner can embed an agent inside their own product instead of running Claude Code in a terminal. Distinct from the Anthropic SDK, which is a thin convenience wrapper over the API and does not run an agent loop.

**▸ Claude Code**

An agentic coding tool that reads files, edits code, runs commands, and executes multi-step engineering tasks under configurable permission boundaries. Distributed as a CLI, IDE plugins (VS Code, JetBrains, and others), a desktop application, and a web product at claude.ai/code. Claude Code is the entry point engineers use to do real development work, and it is customizable through CLAUDE.md, skills, subagents, hooks, MCP servers, and permission settings.

**▸ Claude.ai**

The end-user chat product hosted by Anthropic. Reached through the web, the mobile apps, and Claude Desktop. Users sign in, open conversations, upload files, share context through Projects, and connect external services through built-in connectors. No code is written. Claude.ai is the entry point for users, not builders, which is why a partner's engineering team usually does not consume Claude.ai when embedding Claude in their own product.

**▸ Corpus**

The body of documents a retrieval system searches over. A corpus might be a knowledge base, a set of policy documents, a product manual, or a collection of past tickets. The corpus is loaded and indexed ahead of time, which is why it works for stable reference material and not for live state.

**▸ CSP delivery route**

Cloud Service Provider delivery route: The path that API traffic takes to reach Claude. Anthropic offers a direct route at api.anthropic.com, and the same Claude models are also available through AWS Bedrock, GCP Vertex AI, and Microsoft Foundry on Azure. The route you choose determines where the spend is billed, how the call is authenticated, which region the traffic terminates in, and which contract covers it. It does not affect how the model behaves.

**▸ Deterministic rule**

A deterministic rule is a rule that always produces the same output for the same input. Same in, same out, every single time, with no variation.

**▸ Eval**

Eval short for evaluations is a structured test set used to measure whether a model is performing well enough on a defined task. An eval pairs inputs with expected outputs or quality criteria, runs them against the model, and produces a score you can compare across model versions, prompts, or configurations. Evals are how teams decide whether a change is an improvement or a regression before it reaches production.

**▸ Extended thinking**

The capability where the model works through a problem in a separate block of thinking tokens before it commits to a final answer, rather than responding in one pass. It helps on tasks where a one-shot answer would skip steps. Thinking tokens are billed as output tokens and add latency. How much thinking happens depends on the control mode: a thinking-token budget you configure yourself on older models, or adaptive thinking (see Adaptive thinking) on current ones.

**▸ IDE**

Integrated Development Environment. A software application that bundles a code editor, debugger, and other tools into one place for writing and running code (e.g., VS Code, PyCharm, Xcode).

**▸ Live state**

Data that changes during the lifetime of a conversation or process: an order status, an inventory count, a price, a calendar slot, a user's current session. Live state is distinct from static reference material because the correct answer at 10:00 a.m. may be wrong by 10:05. Systems that need live state require a direct lookup against the source of truth, not a stored snapshot.

**▸ MCP**

Model Context Protocol. An open standard that lets Claude connect to external tools and data sources through a dedicated server, instead of requiring you to write a custom integration for each one. An MCP server exposes tools, prompts, and resources that any MCP-compatible client can use, which means a single integration written once can be reused across applications. MCP shifts the work of building and maintaining tool definitions away from your application code and into reusable servers.

**▸ Monolithic**

The opposite of progressive: everything the model might need is loaded into context up front, in one block. Monolithic context is simpler to set up and fine for short, contained tasks, but it grows over time, pushes against the context window, and forces the model to attend to material that may not be relevant to the current step. Long-lived deployments built monolithically tend to degrade as the conversation accumulates.

**▸ Observability**

Ability to see what your system is doing, reconstruct why it behaved a certain way, and detect when something goes wrong.

**▸ Parametric knowledge**

Parametric knowledge means whatever the model learned during training and carries in its weights (its parameters). It is the model answering from memory, with no outside lookup. The opposite is knowledge the model pulls in at the moment of the request, like a document you hand it or a web search result.

**▸ Progressive**

An approach where context, instructions, or capabilities are loaded in stages as the work requires them, rather than all at once at the start. Progressive context gives the model only what it needs at each step, which keeps the working set focused and the cost of each call lower. The pattern shows up in skills that load reference files on demand and in agents that gather information through tool calls instead of receiving everything in the initial prompt.

**▸ Prompt caching**

Prompt caching is a feature that lets you store frequently used parts of a prompt, typically a long system prompt or a large document, so the model doesn't have to reprocess them from scratch on every request. The cached portion is computed once and reused across multiple calls.

**▸ Retrieval**

Fetching relevant information from an outside source at the moment of the request and handing it to the model along with the question. Instead of relying on what the model learned in training, you pull the current document, record, or passage and put it in front of the model so the answer is grounded in that source.

**▸ SDK**

Software Development Kit. A language-specific library (Python, TypeScript, and others) that wraps the API in idiomatic code for that language. The SDK handles the request formatting, authentication, retries, and response parsing so you can call Claude with a few lines of code instead of constructing HTTP requests by hand. The SDK is built on top of the API, so anything the API can do, the SDK can do, with less boilerplate. When an engineer says "SDK" they may mean this Anthropic SDK (a wrapper over the API) or the Claude Agent SDK (a managed agent runtime); however, these are two different things.

**▸ Shippable**

Ready for production use, not just a working demo. Shippable output meets the bar for accuracy, latency, cost, and reliability that the deployment actually requires, and it has passed the evals and review gates the team uses to release changes. The distinction matters because a prototype that handles the happy path is not the same as a system that handles the long tail of real user inputs.

**▸ Terminal**

A text-based interface for interacting with your computer's operating system by typing commands. Also called a command line or shell (e.g., Terminal on Mac, Command Prompt on Windows).

**▸ Tool use**

The capability that lets Claude call external functions, APIs, or services during a response instead of only generating text. The model decides when to invoke a tool, what arguments to pass, and how to use the result in its next step. Tool use is what turns Claude from a text generator into a system that can read files, query databases, search the web, or take action in other software.

**▸ Wrapper**

Code that surrounds or encapsulates another piece of code, library, or API to make it easier to use, add functionality, or translate between interfaces. For example, a Python wrapper around a C library lets you call C functions as if they were native Python.

---

<!-- S32 -->

*Recap · 3 min · Assembly & Recap*

## Key takeaways

- **01 Decomposition is the move that comes before architecture.** — Before you can choose a pattern, you have to split the work into three buckets: what Claude handles, what your existing systems handle, and what humans handle. The split is driven by how the model behaves on each piece of the work, which is what tells you whether a task belongs with Claude at all or somewhere else in the stack. Designs that skip this step end up forcing Claude into work that another system would do at lower cost or asking it to operate without the context a human would have given a colleague.

- **02 Choosing a pattern is choosing how much autonomy to grant.** — The augmented LLM, the workflow, and the agent are points on a spectrum from "Claude assists one step" to "Claude plans the whole sequence", with four workflow sub-patterns underneath. The decision depends on five factors: predictability (how predictable the task is), error cost (how expensive a wrong answer would be), observability (how visible the work is while it runs), latency (how long you can wait), and cost (how much you can spend per run). When error cost is the binding constraint, error cost picks the pattern. The tightest constraint is the factor that decides.

- **03 Reach for the tested reference architectures before inventing your own.** — The five reference architectures: Agent, RAG, Document processing pipeline (Evaluator-optimizer), Routing, and Coding agent are documented because other teams have already learned what breaks in each one. Combine them when different parts of your system break differently and pick one when you are still uncertain what the system will need to handle. The most common mistake is to use retrieval as a substitute for live state. Retrieval is built for static documents and stale snapshots, so don't use them during a conversation that needs live data.

- **04 Choosing a model: start with Sonnet and treat every swap as a release.** — Sonnet is the default tier because it balances intelligence, speed, and cost for most production workloads. Moving to Opus or Haiku is a deliberate decision that needs the same gate any other release gets: an eval set that defines what "better" means, and a rollback criterion set before the swap, not after. The same principle applies to context. Progressive context, where the model receives only what it needs at each step, holds up better over a long-lived deployment than monolithic context that loads everything up front and grows until it breaks.

- **05 Pick the entry point by the work it has to do, not by what is already on the shelf.** — Claude.ai, the direct API, the SDK, Claude Code, and MCP each carry a different core tradeoff: speed of setup versus depth of control, prebuilt UI versus custom integration, breadth of tools versus focus. The right recommendation is the one where you can name the tradeoff out loud at the time you make it. Naming the tradeoff out loud when you recommend the entry point is what tells you, later, when to switch.

#### Sources

- Anthropic Skilljar, Claude 101: model family (Opus, Sonnet, Haiku), Claude.ai and API entry points.
- Anthropic Skilljar, Claude Code 101 In Action: Claude Code customization stack, CLAUDE.md, subagents, MCP, Skills.
- Anthropic Skilljar, AI Fluency Foundations: the four-properties framework, next-token prediction, knowledge, working memory, steerability.
- Anthropic Skilljar, Building with the Claude API: RAG, chunking, hybrid retrieval, tool use, extended thinking, evaluation.

---

<!-- CERT -->

**

## Congratulations! You have successfully completed this module.

Module 1 establishes the platform decisions that every downstream Architect choice depends on. You have worked through model selection, prompt architecture, tool design, and the tradeoffs that connect each layer to the business case.

**The decisions you make at the platform layer set the ceiling for everything built above it.**

0
 of 0 checkpoints passed

M1

Claude Platform & Solution Design

Model selection, prompt architecture, tool design, and platform-layer tradeoffs.

You Are Here

M2

Enterprise Integration & Production

Deployment patterns, integration architecture, and production reliability.

Up Next

M3

Responsible AI, Safety & Risk

Safety frameworks, risk identification, and governance practices.

M4

Stakeholder Engagement, Lifecycle & Go-to-Market

Stakeholder communication, lifecycle management, and go-to-market strategy.

M5

Team Enablement and Operational Productivity

Team tooling configuration and operational support practices.

---
## Appendix: Inline term tooltips

- **entry points** — The interface through which end users or systems access Claude in production (e.g. claude.ai, a custom app, an API integration).
- **augmented call** — The simplest agentic pattern: a single Claude call enhanced with tools or retrieval, no multi-step orchestration.
- **Non-determinism** — The property that identical inputs to Claude can produce different outputs across calls, unlike traditional deterministic code.
- **multi-agent system** — An architecture where multiple Claude instances (agents) each handle a subtask, coordinated by an orchestrating layer.
- **fanned the work out** — Fan-out: splitting one task across multiple parallel agent calls; a common source of silently dropped units of work if not tracked.
- **multi-agent** — An architecture where multiple Claude instances (agents) each handle a subtask, coordinated by an orchestrating layer.
- **RAG** — A pattern where Claude retrieves relevant external content at request time and uses it to ground its response.
- **chunking** — Splitting source documents into smaller pieces before indexing, sized to balance retrieval precision against context cost.
- **system prompt** — Instructions set once per deployment to shape Claude's behavior across every request, distinct from the user's per-turn message.
- **guardrails** — A rule or check (in a prompt, code, or pipeline) that constrains Claude's output to stay within defined boundaries.
- **tokens** — The unit Claude uses to process text; roughly a word-fragment. Cost and context limits are measured in tokens.
- **caching** — Reuses a previously processed portion of a prompt to reduce cost and latency on repeated or templated requests.
- **Skill** — Reusable instruction packages that extend what Claude can do without rebuilding the prompt each time.
- **entry point** — The interface through which end users or systems access Claude in production (e.g. claude.ai, a custom app, an API integration).
- **delivery route** — The infrastructure path Claude is accessed through (e.g. direct Anthropic API, AWS Bedrock, Google Vertex AI), distinct from the entry point users see.
- **SSO** — Lets users authenticate once to access multiple connected systems, instead of logging into each separately.
- **BAA** — A contract required under HIPAA that governs how a vendor handles protected health information on a covered entity's behalf.
- **MCP** — An open protocol that lets Claude connect to external tools and data sources through a standard interface.
- **Bedrock** — AWS's managed service for accessing Claude inside a customer's existing AWS environment.
- **Vertex AI** — Google Cloud's managed service for accessing Claude inside a customer's existing GCP environment.
- **data residency** — Where data is physically stored or processed, relevant to regulatory requirements that restrict data to specific regions.
- **governance/control** — Refers to who owns audit trails, access policy, and compliance posture for a deployment, not just whether controls exist.
