# Claude Certified Architect — Module 4: Stakeholder Engagement, Lifecycle & GTM

*Source: Anthropic Partners Skilljar (personal study notes)*

---

<!-- S01 -->

Module · Orientation

## Orientation: what you will be able to do by the end

The last three modules took you from a business problem to a designed, integrated, governed Claude deployment. You can break down a request, pick a pattern, size a use case, build evals as acceptance criteria, instrument observability, and stand up an auditable control set for a regulated workload. What none of that resolved is the part of the job that happens in rooms with stakeholders: the discovery conversation where the real requirements are set, the approval meeting where a tradeoff is won or lost, the handoff where your design either survives your absence or quietly degrades.

### This module covers that work. By the end you will be able to:

- 1Run a structured discovery conversation with a non-technical stakeholder and translate what you learn into architectural requirements and documented assumptions, so the design traces back to the business case rather than to your own technical preference.
- 2Present an architectural tradeoff in terms a business stakeholder can action on by pairing each choice with a cost, a risk, and what a reversal would take, so executive and procurement reviews reach a decision instead of stalling.
- 3Build and operate a stakeholder feedback loop across the deployment lifecycle naming what triggers review, what an SLA breach requires, and when to iterate versus re-architect, with governance checkpoints built into the same loop.
- 4Partner Track[Partner-Track Relevant, not tested by the Architect exam; retained for partner-track learners] Lead the Architect's role in a partner go-to-market motion through discovery, a scenario-based demo, technical objection handling, and joint scoping with the Anthropic Applied AI team, so an enterprise opportunity does not stall on questions only you can answer.
- 5Select the deployment entry point and cross-platform strategy for a multi-platform production system comparing the direct API, Bedrock, Vertex, and third-party routes on latency, compliance, and cost, and then produce an outcome document that makes the value legible to a non-technical sponsor and reusable as partner IP.

### The work maps onto the sections that follow:

**Discovery** is where you turn a stakeholder's preference into a documented constraint the architecture can be designed against. The move is translation: a preference signals that more questions are needed rather than functioning as a direct requirement. A useful requirement is testable and bounded. The costly failure is a discovery call that ends in a design sketch before the translation is done. The plausible sketch is what makes it dangerous: a stakeholder who sees a confident architecture assumes the questions have been answered.

**Tradeoff framing and go to market** is where you present an architectural decision in terms a stakeholder can act on, and where you design a demo against the buyer's real scenario rather than the team's own capabilities. Three elements belong in every tradeoff presentation: what the choice gains, what it gives up, and what reversal costs once the system is built around it. The third element is the one that changes the meeting, and it is the one most presentations are missing.

**The feedback loop** is where you build the decision layer that sits above the observability stack and determines which signals change behavior and whose. A feedback loop is a governance table that maps each signal to a trigger, an owner, and an action. In regulated deployments, some reviews fire on a schedule rather than at a threshold. Those governance rows need to be in place before launch. If there is no defined trigger, a compliance checkpoint will not surface until a reviewer comes looking for the record.

**Documentation for handoff and audit** is where you record not just the decisions that were made but the alternatives that were rejected and the tradeoff each resolved. The completeness test is whether a competent Architect who was not in the room can make a safe change to the system after reading the document. A diagram carries what the system is. Without the rationale for the decisions, the diagram cannot tell the successor which choices are load bearing and which are simply preferences. The moment you leave the engagement is the moment that reasoning is gone if it was never documented.

**Entry point selection and the outcome document** is where you confirm the right deployment route for a live production system and turn the deployment's results into an artifact that survives the engagement. The outcome document makes the business case for a reader who was not part of the build. Volume, latency, and error rate tell a sponsor that the system runs. A before-and-after on the business metric the use case targeted, backed by an auditable control, tells a CFO what it is worth expanding.

These five topics are not independent, in fact, each extends from the last. The constraint set from discovery is what the tradeoff presentation is defending. The feedback loop governance table keeps the compliance controls captured in the register captured current as the deployment runs. The documentation rationale keeps the decisions the register contains from being silently reversed by a successor. The outcome document draws on every layer above it to make the value understandable to a reader who never saw the work. The cumulative task at the end asks you to take a regulated multi-platform deployment from a stakeholder's first sentence to an outcome document that justifies expansion. In fact, this is exactly what this module equips you to do before you hand off.

Across these five topics runs the project lifecycle itself: discovery → design → handoff → monitoring → iteration. Discovery and tradeoff framing do the discovery-and-design work; the feedback loop is the monitoring-and-iteration phase; documentation is the handoff phase; and entry-point selection with the outcome document closes the loop. Identifying the phase a decision belongs to is what lets you judge when one phase is ready to move to the next.

> **Disclaimer / Notice for Educational Content**
> 
> We built this Architect course Module 4: Stakeholder Engagement, Lifecycle, and Go-to-Market to help you get real work done with Claude. Treat it as educational content. It doesn't constitute legal, financial, or other professional advice, so adapt what you learn to your own situation. Our products and services evolve quickly, so certain content may contain errors or be outdated; remember to verify on Anthropic's website or docs. Examples and scenarios used in the course are illustrative and often fictitious. If the course material mentions a company or product, it doesn't mean Anthropic endorses them, they endorse Anthropic, or that we're affiliated. Also note your use of Anthropic products and services is covered by our terms, policies and documentation; if anything in this course conflicts with them, they control.

---

<!-- S02 -->

Discovery

## A discovery call is a structured elicitation, not a conversation

You know how to evaluate the pattern, the deployment platform, and the control posture. Discovery reveals whether you are solving the right problem. A stakeholder will usually describe the problem in business terms. Your job is to listen to what the business is trying to achieve, identify the constraints hidden inside that description, and leave the call with a record the design can follow.

### Discovery establishes the artifacts the design depends on

A discovery conversation functions as a three-step filter: listen, translate, and write down.

1. 1First, listen to the business goal in plain language and pay attention to the meaning behind the word. Stakeholders usually describe the outcome they want but not the constraint you need to design for.
2. 2Second, translate that into requirements, assumptions, and unresolved constraints. This allows you to see what the design must support, what still needs confirmation, and what could block the solution later.
3. 3Third, write those items down before the conversation moves on. The design needs a clear record to follow. Without that filter, the design inherits your assumptions. The mismatch may not be revealed until much later, when changing trajectory is slower, harder, and more expensive.

### The core move is translation: a stated preference almost always hides a constraint

The most important skill in discovery is translation. Stakeholders usually speak in preferences, but design decisions are made against constraints. Imagine a stakeholder says, "We want this to feel seamless." If you write down "seamless" as the requirement, you have not learned enough to design anything yet. You only have the stakeholder's summary of the experience they want.

The real work starts with the next question: what would make it feel not seamless? That is where the hidden constraints begin to appear. Maybe the user should never wait more than a second or two for the next step. Maybe they should not have to re-enter information that already exists upstream. Maybe exceptions should move quietly to a human reviewer instead of exposing a technical error. Maybe the workflow must stay inside one application, so the user never has to jump between tools. Each answer sharpens the design.

That exchange transforms "seamless" into requirements the architecture must support: a latency target, an integration requirement, a handoff rule, and a safe failure path. The stakeholder names the outcome in business language. You turn it into something the system can build and be measured against.

The preference sits on the top level, and the constraint sits underneath it. When a stakeholder gives you an experience word like seamless, easy, fast, simple, or intuitive, treat it as a signal that more discovery is needed. Ask what would break that experience, what the user must never notice, what has to happen behind the scenes, and what must still be true when something goes wrong. Those answers are what belong in the design record.

A testable, bounded constraint is what the design can be built against. A stakeholder preference tells you where to investigate, while the follow-up questions produce the constraint itself.

### Four questions turn discovery into requirements

Discovery works best when you force a vague stakeholder statement into the four buckets below. A statement like "we want this to feel seamless" is not yet something you can design against. It usually hides one or more specific answers. Investigate the following:

- 1**What the system must do.** These are the capabilities the deployment must deliver, expressed as business outcomes rather than features. This is where you separate the work Claude owns from the work that remains with an existing system or a human.
- 2**What the system must not do.** These are the boundaries, prohibited actions, and cases that must route to a human. Stakeholders rarely volunteer these, so you must ask for them explicitly.
- 3**What must the system cost.** This is the budget constraint, expressed in terms the stakeholder controls. A latency target, a per-interaction cost ceiling, or a volume forecast should all be taken into account here. These become crucial design constraints.
- 4**What the system must prove.** This is the evidence that the deployment must be able to produce something of value. In regulated workflows, proof obligations are part of the requirement set. Identifying them in discovery is far cheaper than during a legal review weeks later.

"Seamless" may really mean a latency budget the user should not notice, a handoff that should not interrupt the flow, or a failure state that must not expose system internals. Once you discover those answers, you have requirements the team can design for, test, and defend.

### The output of discovery is a translation table

Each item found in discovery becomes one row in a translation table. The row captures the stakeholder statement as it was said, the constraint it implies, the architectural decision that constraint forces, and any assumption you are documenting when the constraint has not yet been confirmed. One row per item keeps the reasoning intact as the work moves from discovery into design, and it keeps assumptions top of mind.

| Stakeholder statement | Implied constraint | Required architectural decision | Assumption of document |
| --- | --- | --- | --- |
| "We want this to feel seamless." | The experience must stay inside an agreed-upon latency budget. Failures must not expose system internals or break the flow. | Set a p95 latency target as a design constraint, then design a graceful, internal-safe failure state. | Assumes "seamless" refers to perceived responsiveness and continuity of flow. Confirm understanding. |
| "It just needs to read the form and route it." | Routing may be a deterministic business rule. | Keep the routing decision in the rule engine. Claude extracts, and the system routes. | Assumes the routing logic is owned and maintained outside the model. Confirm owner. |
| "Clinicians will review the output anyway." | A licensed human must authorize output before it becomes part of a record with legal, financial, or clinical consequence. | Build a human-in-the-loop authorization step as a mandatory checkpoint. | Assumes review is an architectural gate. Confirm authority and timing. |
| "We are in healthcare, so be careful with data." | The workflow likely carries a proof obligation under a health-privacy regime. | Treat audit-trail and data-handling evidence as a core requirement from day one. | Assumes a covered workflow with a formal obligation. Confirm scope with compliance. |

> **Cost · Complexity · Risk**
>  **Cost:** A discovery call that runs long enough to identify the real constraints is far cheaper than redesigning the solution after a hidden constraint emerges during legal or compliance review.
>  **Complexity:** Working through the four question categories adds necessary structure, and translating preferences into constraints in real time takes deliberate practice.
>  **Risk:** The expensive failure is the unstated constraint that survives the test and becomes a production review blocker, when the cost of changing the design is at its highest.

---

<!-- S03 -->

*Watch Out · Discovery · 5 min*

### The discovery call that turned into a design session

> **Setup**
> 
> Discovery is where the work starts. Design is where it accelerates. A good Architect begins forming a solution partway through the call. Sketching and visualizing it feels productive, and the stakeholder seems pleased to see progress. That is exactly the moment the questions stop.

### A reconstructed discovery call, where the questions stopped early

In the exchange below, the Architect hears two stakeholder statements and begins proposing a solution. The stakeholder confirms the initial proposal because it sounds competent. The constraints that would have ruled out that architecture are never identified. They emerge two weeks later during a compliance review. This section shows exactly where the question that would have caught each constraint belonged. Use this example to learn to recognize the pattern in your own calls.

> **Reconstructed exchange**
> 
> **Stakeholder:** "We run a regional hospital network. Nurses spend forever writing up patient interactions. We want Claude to draft the clinical note from their dictation."
>  **Architect:** "Got it, that's just a clean augmented pattern. Claude takes the dictation, drafts the structured note, then writes it back. We can have a prototype next week."
>  **Stakeholder:** "That sounds right. There's a review step in there somewhere, but it's just a quick check."
>  **Architect:** "Sure, we'll add a review step. Let me start with the design."

### Various constraints identified too late to be an easy fix

The "quick check" was not a convenience feature. The nursing workflow required a licensed clinician to authorize any model output before it reached the patient record. This made human authorization a required architectural gate as opposed to an optional addition. The dictation contained protected health information. Protected health information moved through the context window without the handling that the workflow required. The network spanned two states with different record-retention rules, and the single-region design never accounted for either. None of these requirements were unusual or hard to find. Each would have come out of a direct question in the must-prove and must-not-do categories, had the call not moved to sketching before those questions were asked.

> **Why this broke: a competent sketch proposal ended the questions a discovery call exists to ask**
> 
> The sketch was plausible, and plausibility is what makes this dangerous. A stakeholder who hears a confident architecture assumes the Architect has the information to build it. The move that protects you is boring: finish the four-category question set before proposing anything and treat every "it's just a review" as a constraint to chase down.

---

<!-- S04 -->

Discovery · Checkpoint

## Checkpoint: find the undocumented assumption

Try it now. Below is a discovery-call summary and the requirements document an Architect produced from it. Three items trace to something the stakeholder said; one is an assumption the Architect made without surfacing the constraint underneath it. Choose the item that is the undocumented assumption, then confirm that no stakeholder statement supports it.

Requirements document

- 1. Claude drafts the customer email, but a person actually sends it.

- 2. Responses must return within a two-second perceived budget.

- 3. Refunds above the threshold route to a human approver.

- 4. Conversation transcripts are retained for sixty days for analytics.

What the stakeholder said

- “Anything big requires a person’s sign off.”

- “Draft the reply, but we send it ourselves.”

- “It has to feel instant to the user.”

### Part 1: Which item is the undocumented assumption?

- **A.** Item 1, email drafting with human send
- **B.** Item 2, two-second latency budget
- **C.** Item 3, refund routing to human approver
- ✅ **D.** Item 4, sixty-day transcript retention

**Answer: D**

### Part 2: Which stakeholder statement should item 4 trace back to?

- **A.** "Draft the reply, but we send it ourselves."
- **B.** "It has to feel instant to the user."
- **C.** "Anything big requires a person's sign off."
- ✅ **D.** No stakeholder statement supports this item.

**Answer: D**

---

<!-- S05 -->

Tradeoffs & GTM

## Present a tradeoff so the stakeholder can act on it, and design a demo that advances the deal

Discovery told you what the buyer needs. Turning those requirements into a decision a stakeholder can make is the next work.

The Architect is now helping the stakeholder understand the tradeoff, see the business consequences, and approve a path forward with confidence.

### Your job is not to resolve the tradeoff before the meeting. Your job is to make decisions possible.

Your job is to describe the options clearly enough that the stakeholder can make an informed choice.

Every meaningful design decision has a tradeoff. One option may reduce cost or complexity but increase latency, risk, or compliance burden. Another may improve the user experience or scale better but require more effort upfront. If you present only the conclusion, the decision may look clear, but it is weak. When the downside appears later, the stakeholder may feel they approved of a recommendation without understanding what came with it. So, use a simple decision frame:

- 1What do we gain?
- 2What do we give up?
- 3What happens if we choose this now but have to reverse it later?
- 4In regulated environments, what does this do to our compliance posture?

That third question is the one most people skip, and it is often the one that changes the meeting. It turns the discussion from "what is the better technical answer?" into "what is the better business choice?"

Technical precision is necessary, but it is not sufficient. In architecture reviews, the recommendation is often technically correct but still not understandable to the person who must approve it. The Architect may explain the options in technical vocabulary (i.e. latency, logging depth, context size, retrieval pattern, deployment route) but the executive is asking a simpler question: "What happens to the business if we make the wrong choice?" At that point, the room does not need more detail, what it needs is translation into something a person can understand. When you do this well, the stakeholder is not just hearing your recommendation. They are making an informed decision they can defend later.

### Frame the decision as a package, rather than as a verdict

Present the decision as a package the stakeholder can act on: the options you considered, the criteria you weighed them against, your recommendation, and the risks that remain. The stakeholder is not adopting your architecture; they are accepting a decision they will have to defend to their own leadership.

### Description is the competency that makes the package land

Description is one of the four AI Fluency competencies: communicating effectively with AI. Extended to the stakeholder side of the work, the same discipline means telling the audience precisely what they need, in terms they can understand. Applied to stakeholder communication, Description means framing the system's behavior, its limits, and the oversight around it in the stakeholder's goal term. The framing should match their AI familiarity without sacrificing accuracy. Three rules apply in practice: lead with the business outcome rather than the architecture; frame limitations honestly, since a security stakeholder trusts a system whose limits are clearly stated; and anticipate the peer-proof demand, since the stakeholder will need to justify the choice to others and should leave the conversation with that justification in hand.

### Use the tradeoff translation map to shift from architecture framing to stakeholder decision language.

| Architectural decision | What you gain | What you give up | What a wrong, reversed choice costs |
| --- | --- | --- | --- |
| Larger context window per call versus retrieval over chunks | Simpler initial design, the full document in view, and fewer moving parts to manage early on. | Higher per-call cost and slower response times as production volume grows. Prompt caching can recover a significant portion of the input cost for static content like policy documents held in context across call, so evaluate caching before treating per-call cost as fixed. | Reworking the architecture after cost spikes in production, plus the credibility hit of explaining an avoidable expense surprise. |
| Trade logging details for lower latency | Faster perceived response and a smoother end-user experience. | Reduced visibility into what happened in each interaction. | In a regulated workload, a potential compliance gap requiring remediation. |
| Single delivery route versus multi-platform | Lower build complexity and one consistent authentication and logging profile. | Less flexibility to meet different regional, compliance, or procurement needs. | A delayed or blocked production cutover if the chosen route cannot satisfy a late-emerging data residency or deployment requirement. |

The map exists to help the stakeholder see the consequence of their choice clearly enough to decide.

### Demo design is a distinct skill, and a weak demo can undo what discovery earned

Picture the buyer meeting where discovery went well. The team aligned on the problem, the use case, and the value at stake. Then the demo begins. Instead of showing the buyer's world, it shows a polished but generic set of features. The reaction is usually polite, that the demo was interesting, but not quite what they envisioned.

A weak demo can make the buyer question whether the team understood the core problem. This happens when teams confuse two different jobs. A capabilities demo answers, "What can this system do?" A scenario-specific demo answers, "What does this system do with *my* problem, my workflow, and my constraints?"

The first creates interest; only the second creates confidence. Design proof that the solution fits the buyer's context is part of the demo's job. A well-designed demo advances the opportunity while a weak one can undo the trust discovery built.

> **Partner Track**
> 
> Not tested by the Architect exam

Before building any screens, make four design decisions. Those decisions determine whether the demo feels tailored and credible or generic and easy to dismiss.

| Design decision | What the Architect decides | Why it determines the outcome |
| --- | --- | --- |
| Scenario selection | Choose a workflow the buyer will immediately recognize from their own operations, including familiar data shapes, approval steps, and edge cases. Avoid a generic document task or abstract query flow. | Buyers trust what feels familiar. When they see their own vocabulary and failure points on the screen, the demo feels relevant and credible. Recognition is often more persuasive than a polished but generic feature tour. |
| Limit placement | Decide in advance which one or two limitations the demo will identify, and frame them as intentional scope boundaries. State what the system does not do and why. | If a buyer discovers a limitation halfway through the demo, confidence drops. If you name the limitation early, it reads as discipline and honesty. In regulated settings, upfront disclosure of boundaries is often a positive signal. |
| Sales team collaboration | Shape the demo narrative with the sales team before building anything. They know what the buyer raised in earlier conversations, and you know what the system can realistically show under production conditions. | A demo built without sales may answer questions the buyer never asked. A demo built without the Architect may overpromise. Either way, the demo loses credibility and slows the opportunity. |
| Data preparation | Use information that resembles the buyer's data in structure and volume. For regulated buyers, use anonymized data that still reflects the same structural constraints as the real environment. | Buyers judge the demo by the data in it. Realistic field names and data patterns make the scenario feel real. When the data looks like theirs, the demo argues for itself. |

### Limit placement deserves deliberate attention

Of the four demo-design decisions, limit placement is the one that most often runs against instinct. In practice, naming a weakness can feel risky, so the temptation is to hide it or soften it. This usually backfires.

Imagine the moment where the buyer asks, "What does this not handle well?" If the answer is vague, confidence drops. If the answer is clear and scoped, the buyer sees discipline instead of defensiveness.

That is why you should decide in advance which one or two constraints you will name and how you will frame them. Show that the boundary is deliberate, that this is what the solution is built to do, and this is what it is not built to do.

This matters even more in regulated industries such as healthcare, financial services, and the public sector. In those settings, a clear boundary often signals rigor, while a deflection signals risk.

A simple way to prepare is to ask:

- What is the limit?
- Why does it exist?
- What happens if the use case needs to go beyond it?

### Successful joint scoping starts before the session begins

> **Partner Track**
> 
> Not tested by the Architect exam

That same discipline carries directly into joint scoping with the Applied AI team. A good scoping session is not a place to figure out the basics for the first time. It is a place to refine choices, test assumptions, and resolve the questions that need specialist input.

If the demo proves you understand the buyer's problem, the scoping session proves you are ready to shape a credible solution around it. That only works if you arrive with three things prepared:

- A documented view of the customer's requirements and constraints. This captures what came out of discovery: the use case, workflow, stakeholders, data conditions, technical environment, compliance concerns, and success criteria. This gives the session a shared starting point.
- A proposed pattern or small set of candidate patterns, with tradeoffs already named. Walk in with a point of view. Show the likely options, what each gives you, what each gives up, and where the risks sit.
- A short list of open questions the Applied AI team is best positioned to answer. These are the questions worth spending the session on: model behavior, architecture implications, scaling constraints, evaluation approach, safety considerations, or pattern fit.

In the demo, you earn trust by identifying limitations clearly. In joint scoping, you keep that trust by bringing a structured view of the problem, the options, and the unanswered questions.

### Objections fall into different categories, and each requires a different response

Technical objections in a sales cycle usually fall into three categories. Capability objections ask whether the system can do the thing at all. Governance and compliance objections ask whether the deployment can be trusted, controlled, and evidenced in a way the buyer can defend. Design-choice objections ask why you made this choice instead of another. Those require more than just justification. You need to explain the tradeoff the choice makes and what the alternative would have cost, using the same translation structure you used when you presented the tradeoff in the first place.

> **Partner Track**
> 
> Not tested by the Architect exam

The go-to-market engagement map should treat demo design as a tracked workstream. That is why it includes a demo-design column with scenario, identified limitations, confirmed data source, and sales-team sign-off as explicit deliverables. This matters most when a partner is running parallel opportunities or when Architects hand off mid-cycle, because continuity depends crucially on what is documented.

> **Cost · Complexity · Risk**
>  **Cost:** Preparing a tradeoff presentation and a scenario-specific demo takes real Architect time, but it is far less expensive than a stalled opportunity or an approval a stakeholder later withdraws.
>  **Complexity:** Three distinct skills sit underneath this work, and two of them often go against one's instinct: naming reversal cost and placing limits clearly. Both require deliberate practice to improve.
>  **Risk:** The expensive failure is false alignment. When a decision looks approved in the room, but the reversal cost was never made explicit, and the consequence arises later.

---

<!-- S06 -->

*Watch Out · Tradeoffs & GTM · 5 min*

### The approval that was not an informed choice

> **Setup**
> 
> A stakeholder who says yes at the end of a tradeoff presentation appears to have understood the tradeoff. The presentation was complete and technically accurate, and the room felt aligned. That feeling is the trap.

### A reconstructed pre-production review, from the CTO's perspective

The Architect presented a context-strategy tradeoff in technical terms. The CTO asked one question about cost, the Architect answered it accurately, and the CTO approved. Six weeks later the higher per-call cost appeared in the production invoice. This is the exchange, and then the note the CTO wrote when the bill was received. It shows where the presentation answered the wrong version of the question.

> **Reconstructed exchange + follow-up**
> 
> **Architect:** "We're recommending the larger context window, so the full policy document stays in view on every call. It keeps the design simpler and avoids a retrieval layer."
>  **CTO:** "What does the cost per call look like?"
>  **Architect:** "About four cents per interaction at the model tier we're using. If the policy document is static across calls, prompt caching could bring the input portion of that down significantly."
>  **CTO:** "Fine, approved. Let's keep it simple."
>  **[Six weeks later, on the production invoice] CTO's note to the account team:** "I approved a direction, not a number. Nobody told me four cents times our call volume was a five-figure monthly line. If the document was static, why weren't we caching it? And if we were going to build around full-context anyway, I needed to know what unwinding that would cost once the system depended on it."

### The issue: the reversal cost never entered the conversation

The presentation named what the design gained, simplicity, and it answered the per-call cost as asked. What it never identified was the third element: what happens to the business when this choice meets production volume and must be reversed after the system is built around it. The CTO approved a per-call number, not a monthly bill, and not the cost of unwinding a decision later. Two parts of the tradeoff were clearly communicated and understood. The third was not, and it turned out to be the load-bearing one.

> **Why this broke: an accurate presentation can still answer the wrong question**
> 
> A stakeholder who approved a recommendation without understanding the reversal cost has not made an informed choice. The CTO heard a per-call figure and a simplicity argument and reasonably said yes. The reversal-cost element was the one factor that would have changed the decision. Name all three elements every time and name the reversal cost especially when the design feels obviously simpler.

---

<!-- S07 -->

Tradeoffs & GTM · Checkpoint

## Checkpoint: recommend the option and name the missing element

Try it now. Read the one-paragraph stakeholder briefing and the three option presentations written in plain language. One option is technically accurate and presented comprehensively. One is technically accurate, but its presentation is missing an element. One is inappropriate for the stated constraints. Recommend the option to put forward, then name the single element missing from the second option's presentation.

> **Briefing**
> 
> A mid-sized insurer wants Claude to draft adjuster responses to policyholder queries. The workflow is covered by state insurance regulation with an audit-trail obligation. Volume is high and steady. The sponsor cares about response quality and about keeping a defensible record of every automated interaction.

| Option | Presentation as shown |
| --- | --- |
| **A** | Workflow pattern with per-interaction logging built in. Gains: full audit trail, quality gate before sending. Gives up: a small latency cost from the logging step. Reversal: minor, logging can be tuned without redesign. |
| **B** | Workflow pattern that trades the logging step for lower latency. Gains: faster responses. Gives up: per-interaction audit detail. |
| **C** | Single augmented call with no logging and no human gate, chosen for lowest build cost. |

### Part 1: Which option should you recommend?

- ✅ **A.** Option A, logging built in, full audit trail
- **B.** Option B, trades logging for lower latency
- **C.** Option C, no logging, no human gate

**Answer: A**

### Part 2: What single element is missing from Option B's presentation?

- **A.** What Option B gains (faster responses is not named clearly enough)
- **B.** What Option B gives up (audit detail loss is not explained)
- ✅ **C.** The reversal cost, what it costs to restore logging after the design depends on the latency gain
- **D.** The compliance posture this option creates

**Answer: C**

---

<!-- S08 -->

Feedback Loops

## The feedback loop decides which signals reach a stakeholder, and the SLA names what you owe when one breaks

Production observability and the audit trail record what a live deployment is doing. This topic covers filtering those signals, deciding when to escalate beyond the team, and defining what the SLA requires when performance falls below standard. The system is live; keeping it trustworthy over time what takes effort. In lifecycle terms, the feedback loop is the monitoring-and-iteration stage of the deployment lifecycle.

### A live deployment drifts without active monitoring

Imagine a customer support assistant that is launched in solid shape. It answers quickly, stays in a tone, and handles the most common questions well. First, everything looks stable. But over time, usage patterns change, new prompt styles appear, and customer issues become more complex. Some responses merely slow down, and some answers start missing the mark entirely.

Nothing breaks dramatically, which is what makes drift hard to catch. Quality erodes gradually rather than all at once. A team without a feedback loop may not see the decline until users already feel it.

### The feedback loop is a decision layer that sits above the observability stack

Observability gives you the raw material: latency, error rates, eval scores, usage patterns, and other signals from the system. But a signal by itself is not yet a decision. One spike may be noise. Another may point to a real problem. A third may be important only if it keeps happening.

The feedback loop sits on top of observability to answer five questions:

**Signals → Triage → Decide → Act → Review**

- 1**Signals:** What is the system showing us?
- 2**Triage:** What needs attention now, and what can wait?
- 3**Decide:** Does the issue need a team fix, a stakeholder review, or no action?
- 4**Act:** What correction, guardrail update, or escalation is required?
- 5**Review:** Did the response work and does the rule need to change?

Think of it like a control room in a train station. The sensors can tell you where the trains are late, but someone still must decide whether a delay is minor, whether passengers need to be informed, and whether the schedule needs to change. That judgment layer is what makes the system manageable instead of just measurable.

### An SLA names three things, and the thresholds come from somewhere tangible.

Once the feedback loop decides that something matters, the SLA defines what happens when it crosses the line. An SLA is a commitment that makes three things clear:

- 1What are we measuring?
- 2What counts as a breach?
- 3What happens when a breach occurs?

The threshold should never be arbitrary. It should trace back to something tangible:

- 1Latency should reflect the user experience expectation identified earlier
- 2Availability should reflect how critical the deployment is to the business
- 3Quality should reflect the eval results and acceptance criteria already established

That traceability matters because it keeps the SLA defensible. If the number cannot be tied to one of those sources, it is probably just a target someone chose because it sounded reasonable.

**Cost is the expectation that breaks most often after launch.** Production volume routinely runs one to two orders of magnitude above the pilot, so a cost that looked trivial in the proof of concept becomes a five-figure monthly line at scale. Pre-empt it: give the stakeholder a consumption forecast at expected production volume, name the spend-control posture (caching, model tiering, budget alerts), and frame the model-tiering narrative before the first invoice rather than after it.

### Regulated deployments add review checkpoints that run on a schedule

Observability records what happened; the feedback loop determines what to do about it. In regulated deployments, some reviews must happen even when nothing has gone wrong. A healthcare workflow with a documentation obligation may require periodic output audits on a defined schedule. A data-residency deployment may need scheduled confirmation that the environment still meets residency rules. These are design-time obligations rather than tasks to be added later. If they are not built early, they become far more expensive to establish when someone asks for proof.

Build a governance table that maps each signal to its trigger, the Architect's response, and any regulatory checkpoint. The table should exist before launch. It is the mechanism that turns policy into an operating routine.

**▸ Production-signal governance table**

| Signal type | Review trigger | Architect action | Regulated-industry checkpoint |
| --- | --- | --- | --- |
| Output quality (eval score) | Score crosses the threshold drawn from the eval suite. | Diagnose whether the cause is prompt, data, or model drift, then decide to iterate versus re-architect. | Periodic output audit against the documentation standard, on an established schedule, regardless of score. |
| Latency p95 | Crosses the budget set from user-experience requirements. | Investigate the bottleneck, then tune or escalate to a stakeholder review if the budget itself is wrong. | Usually none, unless latency is masking a logging or traceability gap. |
| Cost per interaction | Crosses the budget envelope agreed in discovery. | Identify the driver, then bring a tradeoff to the stakeholder if the budget needs revisiting. | Usually none, unless cost controls are part of a regulated operating constraint. |
| Data-residency configuration | Scheduled confirmation. | Confirm and record residency posture and flag any drift immediately. | Residency confirmation on the established schedule. |

> **Cost · Complexity · Risk**
>  **Cost:** The loop creates an ongoing architect effort. Note that this is cheaper than discovering decline in a quarterly review after every dashboard looked good.
>  **Complexity:** The hardest part is the deciding which signals deserve attention, and which are noise, because observability tooling cannot make that judgment for you.
>  **Risk:** The biggest failure mode is a compliance checkpoint that was never wired to a trigger, allowing a documented-standard violation to run for weeks before a routine review catches it.

---

<!-- S09 -->

*Watch Out · Feedback Loops · 5 min*

### The observability stack that replaced the feedback loop

> **Setup**
> 
> An Architect who has built a rigorous observability stack has done the harder technical work. The dashboards are live, the alerts are configured, and the data is flowing. It is easy, and reasonable, to conclude that stakeholder feedback is covered.

### A reconstructed trace: ninety days of alert log against the stakeholder review calendar

The excerpt below places a deployment alert log next to its stakeholder review calendar over a ninety-day window. The alert log shows a sustained drift in output quality across weeks four through seven. The review calendar shows no review that happened in that window. A single row in a feedback-loop governance table would have connected the two. This shows what the gap looks like in the record.

| Window | Observability stack recorded | Stakeholder review calendar | What the loop should have done |
| --- | --- | --- | --- |
| Weeks 1-3 | Eval score steady at baseline, with latency and cost nominal. | Launch review held in week 1. | Nominal. No escalation needed. |
| Weeks 4-7 | Eval score drifting down week over week, with error rate flat, so no hard alert is fired. | No review scheduled or held. | A quality-drift trigger should have escalated to an Architect review by week 5, and onward to a stakeholder review once diagnosis confirmed the drift. |
| Weeks 8-12 | Score is still declining, and the stakeholder reports the output is "less useful lately." | Quarterly review finally surfaces it in week 12. | By design, the loop would have caught this seven weeks earlier. |

### The issue: the signals existed, but nothing decided they mattered

Every metric the deployment needed was already being collected. The eval score was visibly drifting downward since week four. What was missing was the decision layer: no governance rule mapped a slow quality drift to a review trigger. The drift never crossed an error-rate threshold, so no alert fired. A drift with no trigger is invisible until a human happens to notice. The stack was measuring the right thing and telling no one it mattered.

> **Why this broke: monitoring is not a feedback loop**
> 
> A dashboard collects and displays signals. A feedback loop maps each signal to a trigger, an owner, and a required action. The observability stack collected the signals but had no governance rule mapping any signal to a trigger or owner. Build the governance table that maps each signal to a trigger, an action, and an owner. Include both the slow drifts and the hard failures.

---

<!-- S10 -->

Feedback Loops · Checkpoint

## Checkpoint: triage the production signals

Try it now. Here are nine signals from a production deployment. Drag each into the bucket where it belongs: Internal monitoring, Architect review, Stakeholder review, or Noise.

**Sorting exercise (answer key):**
- **Internal monitoring:**
  - 1 · Latency p99 ticked up 40ms, still inside budget.
  - 8 · Token usage rose with a known seasonal traffic bump.
- **Architect review:**
  - 2 · Eval score down three weeks running, trend is clear.
- **Stakeholder review:**
  - 3 · Scheduled data-residency confirmation is due.
  - 5 · Cost per interaction crossed the agreed budget threshold.
  - 7 · Quarterly output audit against the documentation standard is due.
- **Noise:**
  - 4 · One malformed request from a known bad client.
  - 6 · A 2 a.m. batch job logged a retry that then succeeded.
  - 9 · A new prompt template shipped, and error rate is flat.

---

<!-- S11 -->

Documentation

## Documentation that survives your absence serves the handoff recipient, the auditor, and the returning Architect

The feedback loop keeps the system healthy while you are running it. Documentation is what keeps it functioning after you are gone. This topic turns the full design into documentation that outlives a handoff and satisfies a compliance reviewer. Either the design carries its own reasoning into that handoff, or that reasoning disappears the moment you leave. In lifecycle terms, documentation is the handoff stage of the deployment lifecycle.

### One document serves three readers, and serving only one of them makes it incomplete

Architecture documentation serves three readers. The inheriting engineer takes over a deployment they had no part in building. The auditor arrives later, looking for evidence that a specific control is live and accounted for. The returning architect, often you, comes back months later with no memory of the design sessions. A document built for one of these readers and not the others is incomplete even when it is detailed.

### For the handoff recipient: the rejected alternatives matter just as much as the decisions made

For whoever inherits the system, the document must carry the decisions that were made, the alternatives that were rejected, and the reason each rejection happened. A design delivered without its rejected alternatives cannot be understood by someone who was not in the room. They will reverse the right decision for the wrong reason or defend the wrong decision because they cannot tell which tradeoff it was resolving. The rejected options explain why the design is shaped the way it is.

### For the compliance reviewer: evidence matters more than assertions

For the compliance reviewer, the document must carry each regulatory obligation, the technical control that satisfies it, the owner of that control, and the evidence artifact that demonstrates the control is operating. This is the regulated deployment control register, carried forward into the living document that governs the deployment's production life. The reviewer does not accept mere assertions. They require evidence, which means that a statement that control exists is not enough on its own.

### For the returning Architect: navigable without a briefing

For the Architect who returns months later, the document must stand on its own. Decisions are dated. Assumptions are explicitly labeled as assumptions rather than embedded as facts. Open items have owners and resolution criteria. The test is practical: after reading the document, can a competent Architect who was not present at the design sessions make a safe change to the system? If the answer is no, the document is not complete.

### The documentation completeness checklist:

**▸ Documentation completeness checklist**

| Field | What it captures | Reader it primarily serves |
| --- | --- | --- |
| Decision | The architectural choice that was made, including the date. | All three readers. |
| Rejected alternatives | The options that were considered but not chosen. | Handoff recipient. |
| Tradeoff named | The tradeoff the decision resolved, expressed in terms of gains, costs, and reversal implications | Handoff recipient and returning Architect. |
| Owner | The person or team responsible for the decision or the control going forward. | Compliance reviewer and handoff recipient. |
| Evidence artifact | The artifact that demonstrates a control is actually operating. | Compliance reviewer. |
| Audit-ready status | Whether the available evidence is current and sufficient for review. | Compliance reviewer. |

> **Cost · Complexity · Risk**
>  **Cost:** Writing the rationale and evidence at design takes time. Reconstructing it later from email threads, or failing to, costs a wrong reversal in production.
>  **Complexity:** The discipline is recording why, not just what, and labeling assumptions as assumptions, which is easy to skip when the reasoning feels obvious to the person who lived it.
>  **Risk:** The costly failure is a successor who reverses a load-bearing decision because the rationale was never documented, reintroducing a constraint violation the original design had solved.

---

<!-- S12 -->

*Watch Out · Documentation · 5 min*

### The design rationale that lived in the Architect's head

> **Setup**
> 
> An Architect who was present at every design decision holds the rationale for all of them. Writing it down feels redundant when you already know it, and there is always something more urgent than documentation. That is exactly how the rationale leaves with the person.

### A postmortem: a financial-services handoff where the rationale never made it to the page

In this case, the original Architect left a mid-sized financial-services engagement twelve weeks after launch. Their replacement inherited a thorough architecture diagram with no rationale attached. A performance issue prompted a proposal to switch context strategies, the replacement made the switch, and it reintroduced a data-handling pattern that violated the deployment's data-residency constraint. The postmortem traces the failure to the one row that was missing. This is what that looks like in the record.

| Stage | What happened | What the document carried |
| --- | --- | --- |
| Launch | Original Architect designs a context strategy specifically to keep regulated data in-region. | An architecture diagram showing the final design. |
| Handoff | Original Architect leaves in week twelve. No design sessions are recorded. | The diagram, with no rejected alternatives and no rationale. |
| Change | Replacement hits a performance issue and switches context strategies to fix it. | Nothing explains why the original strategy was chosen. |
| Failure | The switch reintroduces a data-handling pattern that breaks the data-residency rule. | The reason the original design avoided that pattern existed only in the departed Architect's head. |

### What broke: the diagram showed what and lost the why

The replacement was competent and acted reasonably on the information they had. The diagram told them what the system was, not why it was that way. The original context strategy was a deliberate choice to satisfy a residency constraint, and that reasoning was never written as a decision with a named tradeoff and a rejected alternative. With no rationale documented, the replacement could not tell that the strategy they were changing was load-bearing for compliance, so they reversed the right decision for an understandable wrong reason.

> **Why this broke: a design without its rationale is a design that cannot be safely changed**
> 
> The completeness test is whether a competent Architect who was not in the room can make a safe change after reading the document. Here the answer was no, and nobody knew it until production broke. Record the decision, the rejected alternatives, and the tradeoff each resolved. Remember if it is never written, then it leaves with you.

---

<!-- S13 -->

Documentation · Checkpoint

## Checkpoint: place the documentation artifacts

Try it now. The plane has two axes: one runs from "serves the handoff recipient" to "serves the compliance reviewer," the other from "documents intention" to "documents evidence." Drag each of the six artifact cards into the zone that best describes its primary function.

Architecture diagram

Decision log with rationale

Control register with evidence links

Deployment runbook

Test-result summary

Assumption register

← Handoff recipientCompliance reviewer →

↑ Documents intention / Documents evidence ↓

**Sorting exercise (answer key):**
- **Handoff · Intention:**
  - Architecture diagram
  - Decision log with rationale
  - Assumption register
- **Compliance · Evidence:**
  - Control register with evidence links
  - Test-result summary
- **Handoff · Evidence:**
  - Deployment runbook

---

<!-- S14 -->

Entry Point & Outcomes

## Entry point selection returns with the full production picture, and the outcome document turns the work into reusable IP

This topic covers how the deployment was routed and what it produced, turning the work into partner IP that survives the engagement. Entry point selection returns here with the full production picture in view.

### The entry point question changes once the deployment is live across more than one platform

The earlier module introduced route selection as an entry-point-and-compliance pre-filter: the direct Anthropic API, AWS Bedrock, GCP Vertex AI, and Microsoft Foundry each serve different partner procurement postures and regional compliance requirements. This topic returns to that decision with the full production context. The question is no longer which route survives the compliance pre-filter. It is which route performs best across the latency, cost, and compliance dimensions of a live multi-platform deployment. Because entry-point capabilities change, every specific claim in this section is re-verified against platform.claude.com/docs and anthropic.com at build time.

### Cross-platform deployments expose problems a single entry point never shows

A deployment that spans more than one entry point exposes a class of problems a single-entry-point system does not. Model identifier strings differ across routes. Feature availability can lag on a route mediated by a cloud service provider relative to the direct API. Regional availability on Bedrock and Vertex requires explicit configuration, and defaulting to a global endpoint is the common pattern that breaks a data-residency requirement. An Architect designing across entry points needs a documented entry-point-responsibility map before writing the first line of integration code.

### A multi-entry-point app has to say which entry-point owns which task, and why

An app that integrates multiple Claude entry-points in one workflow requires you to specify which entry-point handles which task and the reason. A workflow that uses the API for back-end inference, Claude Code for an engineering sub-task, and a Bedrock endpoint for a regulated data path is not unusual at enterprise scale. Each entry-point boundary is an integration point with its own authentication, logging, and failure-mode profile. The entry-point-responsibility map makes those boundaries explicit and prevents the most common multi-entry-point failure: an entry-point chosen for one task gradually taking on another because the routing logic was never documented.

### The outcome document makes the value legible beyond the team that built it

Customer outcome documentation is the artifact that makes the deployment's value understandable to people who were not on the build. A well-structured outcome document covers six fields: the use case and its scope boundary, the metric before deployment, the metric after deployment, the control that makes the result auditable, the owner responsible for ongoing measurement, and the potential to reuse the pattern for other customers or engagements. The technical metrics alone do not make this document. The before-and-after business outcomes and the reuse notes are what turn it into a reusable asset.

### The deployment-entry-point decision matrix:

**▸ Deployment entry-point decision matrix**

| Platform | Latency profile | Compliance posture | When to pick it |
| --- | --- | --- | --- |
| Direct Anthropic API | Newest features first, with the fewest additional hops. | Strong default but confirm coverage by configuration. | Use by default unless a procurement or residency rule points elsewhere. |
| AWS Bedrock | Region-configurable, with possible feature lag versus direct. | Fits AWS-centric procurement and region rules when configured explicitly. | Partner standardized on AWS and needs in-region execution. |
| GCP Vertex AI | Region-configurable, with possible feature lag versus direct. | Fits GCP-centric procurement and region rules when configured explicitly. | Partner standardized on GCP with a Vertex procurement path. |
| Microsoft Foundry (Azure) route | Varies by hosting form: Hosted-on-Azure models run inference in the partner's Azure environment (GA); hosted-on-Anthropic models route to Anthropic infrastructure. | Verify residency and coverage per route, and do not assume from the platform name. | Partner procurement or residency posture requires that specific route. |

> **Partner Track**
> 
> The "reuse the pattern for other customers or engagements" framing and the Reuse-potential field in the template below are Partner-Track relevant content; the rest of the outcome document is on-blueprint (6.4).

### The customer outcome documentation template:

**▸ Customer outcome documentation template**

| Field | What it records |
| --- | --- |
| Use case with scope boundary | What does the deployment do and what it does not. |
| Metric before | The business metric as it stood before deployment. |
| Metric after | The same metric after deployment, measured using the same definition. |
| Control in place | What makes the before-and-after comparison auditable rather than merely asserted. |
| Measurement owner | Who owns ongoing measurement after the engagement closes. |
| Reuse potential | How the pattern transfers to other customers or engagements as IP. |

> **Cost · Complexity · Risk**
>  **Cost:** Picking the wrong deployment platform or producing a thin outcome document is cheap to do and expensive to undo: residency mismatch can block cutover, and a metrics-only document cannot justify expansion.
>  **Complexity:** Multi-platform routing multiplies integration points, each with its own auth, logging, and failure profile. The entry-point-responsibility map is the only thing that keeps them understandable over time.
>  **Risk:** The expensive failure is a default configuration that quietly breaks data residency, or an outcome document a sponsor cannot take to a CFO because it never captured business value.

---

<!-- S15 -->

*Watch Out · Entry Point & Outcomes · 5 min*

### The outcome document that measured the wrong thing

> **Setup**
> 
> A deployment that performed well during a controlled rollout has data behind it. An Architect closing the engagement has everything they need to write the outcome document. Writing it quickly from the metrics already on hand feels like the right move, and the engagement is over before anyone notices what the document cannot answer.

> **An anecdote: the outcome document that could not survive a CFO's first question**
> 
> An Architect produced a customer outcome document using the metrics easiest to export from the observability stack: request volume, average latency, and error rate. The customer sponsor took it to their CFO to justify expanding the deployment. The CFO's first question was what the deployment had saved or produced in business terms, and the document could not answer it. The two fields that would have made it usable were never filled in. This is how that played out.
>  **The sponsor opened with the document as written:** "Here's the deployment. Forty thousand requests a month, sub-two-second average latency, error rate under half a percent."
>  **The CFO:** "That tells me it runs. What did it do for us? What were claim processing times before this, and what are they now? Because that's the number that justifies spending more."
>  The sponsor had no evidence to point to. The document measured that the system worked, but it didn't measure what it changed.

### What broke: the document captured technical metrics without business outcomes

Volume, latency, and error rate are real and worth tracking, but none of them are a business outcome. The fields that would have made the document usable for the CFO conversation were the before-and-after on the business metric the use case targeted, claims-processing time, and the control that made that comparison auditable. Without the before number, there is no story. Without control, the after number is an assertion. The document was complete as a technical record and useless as a case for expansion.

> **Why this broke: the easy-to-export metrics are rarely those that justify cost**
> 
> The observability stack collects your technical metrics for free but without anchoring them in data, you are left with dashboards that look informative and mean nothing. However, the outcome document exists for a different reader, the sponsor who must justify the deployment upward. Capture the before metric at the start, name the control that makes the comparison auditable, and add the reuse note, so the document can do the one job a technical dashboard cannot.

---

<!-- S16 -->

Entry Point & Outcomes · Checkpoint

## Checkpoint: pick the platform and the required outcome fields

Try it now. You are given a deployment scenario with three variables: the partner's primary cloud platform, the deployment's regulatory obligation level, and the primary performance constraint. Set the three variables. A decision model maps the combination to a recommended primary platform, a secondary platform where one applies, and the two outcome-document fields the combination needs to be reusable.

**Course answer data:**
- **RESULT_TEMPLATE:** Recommended primary platform: Secondary platform: Required outcome fields for reuse:

**Decision table (S16_TABLE):**
- **aws-strict-compliance** → primary: AWS Bedrock, configured for explicit in-region execution, because the partner is AWS-standardized and residency is the governing criterion under a strict obligation · secondary: Direct Anthropic API for non-regulated back-end tasks where the newest features matter and no residency rule apply · fields: Control in place (auditable) + Measurement owner · rationale: The control in place that makes the result auditable, and the measurement owner, because a strict-obligation deployment's outcome document is worthless to a reviewer without an auditable control and a named owner. Verify that the specific compliance requirement (e.g., HIPAA BAA, data sovereignty) is satisfied by the Bedrock configuration in use. · displayHtml: For the example combination above, the expected outputs are:Primary platform: Bedrock, configured for explicit in-region execution, because the partner is AWS-standardized and residency is the governing criterion under a strict obligation. Verify that the specific compliance requirement (e.g., HIPAA BAA, data sovereignty) is satisfied by the Bedrock configuration in use.Secondary platform: Direct API for non-regulated back-end tasks where the newest features matter and no residency rule apply.Required outcome fields: The control in place that makes the result auditable, and the measurement owner, because a strict-obligation deployment's outcome document is worthless to a reviewer without an auditable control and a named owner.
- **aws-strict-latency** → primary: AWS Bedrock, configured for explicit in-region execution · secondary: Direct Anthropic API where residency rule does not apply · fields: Control in place (auditable) + Measurement owner · rationale: Residency governs over latency under a strict obligation. Outcome fields remain control and owner, an auditor will ask for these first.
- **aws-moderate-latency** → primary: AWS Bedrock, region-configured to match procurement · secondary: Direct Anthropic API for lowest-latency non-regulated tasks · fields: Metric before + Metric after · rationale: Moderate obligation, latency-sensitive → use Bedrock for procurement fit, Direct API where speed matters. Outcome fields: before-and-after business metric is the expansion case.
- **gcp-strict-compliance** → primary: GCP Vertex AI, configured for explicit in-region execution · secondary: Direct Anthropic API for non-regulated tasks · fields: Control in place (auditable) + Measurement owner · rationale: GCP-standardized + strict obligation → Vertex in-region. Strict obligation requires auditable control and named owner in the outcome document.
- **direct-none-latency** → primary: Direct Anthropic API, newest features, fewest hops · secondary: None required · fields: Metric before + Metric after · rationale: No residency or procurement constraint → Direct API is the default. Outcome fields: before-and-after business metric tells the expansion story.
- **direct-none-cost** → primary: Direct Anthropic API with prompt caching and model tiering · secondary: None required · fields: Metric before + Metric after + Reuse potential · rationale: Cost-sensitive with no regulatory constraint → Direct API with aggressive caching. Document reuse potential so the cost-optimization pattern transfers to other engagements.

---

<!-- S17 -->

Module · Cumulative

## Cumulative: architect a regulated multi-platform deployment end to end

Here is a self-contained brief. A regional healthcare network with a health-privacy obligation is deploying a clinical documentation assistant across two cloud platforms. The original Architect is rotating off, and the customer's CFO is asking for evidence of business value. Work through the seven decisions in order. Each one builds on the last.

> **The brief**
> 
> The network runs across two states. Nurses dictate patient interactions, and the assistant drafts the structured clinical note. A licensed clinician must authorize every note before it reaches the patient record. The deployment carries a health-privacy obligation with an audit-trail requirement and a data-residency rule. The partner is standardized on AWS but runs some non-regulated back-end work on the direct API. You are four weeks into the deployment, and the CFO wants to know what the deployment is worth.

*(Free-response exercise: Decision 1 · Discovery: From the brief, name the must-prove constraint that most shapes the architecture, and write the one requirement row it forces. (Applies the discovery translation framework.))*

*(Free-response exercise: Decision 2 · Tradeoff framing: The network asks for the lowest-latency design. Frame the tradeoff between trimming logging for latency and keeping the audit trail, in three elements including the reversal cost. (Applies the tradeoff translation map.))*

*(Free-response exercise: Decision 3 · Feedback loop: Define one governance-table row that maps the required output audit to a stakeholder-review trigger on schedule, independent of any metric. (Applies the feedback-loop governance table.))*

*(Free-response exercise: Decision 4 · Documentation: Name the one decision-log row whose absence would let your successor reverse a compliance-load-bearing choice and state the rejected alternative it must carry. (Applies to the documentation completeness checklist.))*

*(Free-response exercise: Decision 5 · Entry point selection: Pick the primary and secondary entry points given AWS standardization, a strict obligation, and a residency rule, and name the configuration step that prevents the common residency failure. (Applies the Entry-point decision matrix.))*

*(Free-response exercise: Decision 6 · Outcome document: Name the before-and-after business metric and the auditable control that make the document usable for the CFO's expansion case. (Applies the customer outcome documentation template.))*

*(Free-response exercise: Decision 7 · Phase transition: Name the artifact that gates the next phase transition for this brief and judge whether that gate is satisfied. (Applies lifecycle-phase gating.))*

---

<!-- GLOSSARY -->

Wrap-up · Reference

## Glossary

The key terms used across this module, in alphabetical order. Click a term to expand its definition.

**▸ Control register**

The table carried forward from the regulated-deployment work that maps each regulatory obligation to a technical control, an accountable owner, and an evidence artifact a reviewer can inspect. In documentation it becomes the living record that governs the deployment's production life.

**▸ Decision log (with rationale)**

A record of each architectural choice that captures not just the decision but the alternatives rejected and the tradeoff each resolved, so a successor does not reverse a load-bearing choice for an understandable wrong reason.

**▸ Deployment lifecycle**

The phases a deployment runs through: discovery → design → handoff → monitoring → iteration. Discovery and tradeoff framing do the discovery-and-design work, the feedback loop is monitoring-and-iteration, documentation is handoff, and entry-point selection with the outcome document closes the loop. Identifying the phase a decision belongs to is what lets you judge when one phase is ready to move to the next.

**▸ Discovery**

A structured elicitation, not a conversation: a three-step filter of listen, translate, and write down that turns a stakeholder's business goal into requirements, assumptions, and constraints the design can be built and measured against.

**▸ Documentation completeness**

The test of whether a competent Architect who was not in the room can make a safe change after reading the document. It requires the decision, the rejected alternatives, the tradeoff each resolved, the owner, and the evidence artifact, and assumptions labeled as assumptions.

**▸ Entry-point-responsibility map**

A documented record of which Claude entry point (direct API, Claude Code, Bedrock, Vertex, Microsoft Foundry) owns which task and why, written before integration begins. It prevents the common multi-platform failure of an entry point chosen for one task quietly taking on another because the routing was never documented.

**▸ Evidence artifact**

Concrete proof that a control is operating, a signed agreement, a configuration screen, an authorization record, or a returned log query. A control asserted in a design document with no artifact is a claim, not proof.

**▸ Feedback loop**

The decision layer that sits above the observability stack and answers Signals → Triage → Decide → Act → Review, mapping each signal to a trigger, an owner, and an action. Monitoring collects signals; the feedback loop decides which ones change behavior and whose.

**▸ Governance table**

The pre-launch table that maps each production signal to its review trigger, the Architect's action, and any scheduled regulated checkpoint. It is the mechanism that turns policy into an operating routine and must exist before launch.

**▸ Joint scoping**

A working session with the Anthropic Applied AI team to refine choices and resolve specialist questions. You arrive with a documented view of requirements and constraints, a proposed pattern or candidate set with tradeoffs named, and a short list of open questions only the Applied AI team can answer.

**▸ Limit placement**

Deciding in advance which one or two limitations a demo will name, and framing them as intentional scope boundaries. In regulated settings an upfront, clearly scoped boundary signals rigor, while a discovered or deflected limitation erodes confidence.

**▸ Outcome document**

The artifact that makes a deployment's value legible to a sponsor who was not on the build. Six fields: the use case with scope boundary, the metric before, the metric after, the auditable control, the measurement owner, and the reuse potential. The before-and-after business outcome and the reuse notes are what make it reusable IP rather than a technical record.

**▸ Requirement vs assumption**

A requirement traces to something the stakeholder actually said; an assumption is something the design takes for granted that was never stated. An unsourced assumption is the most dangerous kind, because nobody remembers deciding it.

**▸ Reversal cost**

What it costs to undo a decision after the system has been built around it, the third element of a tradeoff presentation. It is the element most presentations omit and the one that most often changes the meeting, turning "what is the better technical answer?" into "what is the better business choice?"

**▸ Scenario-specific demo**

A demo built against the buyer's own workflow, data shapes, and constraints, it answers "what does this do with my problem?" rather than a capabilities demo's "what can this system do?" Only the scenario-specific demo creates confidence rather than mere interest.

**▸ SLA (Service Level Agreement)**

A commitment that names what is measured, what counts as a breach, and what happens when a breach occurs. The thresholds trace to a tangible source, the user-experience expectation, the deployment's business criticality, or the eval acceptance criteria, rather than an arbitrary target.

**▸ Tradeoff framing**

Presenting an architectural decision in terms a stakeholder can act on: what the choice gains, what it gives up, and what a reversal costs once the system is built around it (plus, in regulated settings, what it does to the compliance posture). The goal is to make an informed decision possible, not to deliver a verdict.

**▸ Translation (discovery)**

The core discovery move: converting a stakeholder preference ("seamless," "fast," "simple") into a testable, bounded constraint by asking what would break the experience, what the user must never notice, and what must still be true when something goes wrong.

**▸ Translation table**

The output of discovery: one row per item capturing the stakeholder statement as said, the implied constraint, the required architectural decision, and any assumption being documented until it is confirmed. One row per item keeps the reasoning intact as work moves from discovery into design.

---

<!-- S18 -->

Module · Recap · 3 min

## Recap: five things that hold across everything here

### Key takeaways

- **01 Structured discovery** — Run discovery as a four-category process, translate every preference into a constraint, and write each item as a requirement row with its assumption labeled, so the design traces to the business case.

- **02 Communicating tradeoffs and GTM** — Present every tradeoff in three elements including the reversal cost. Partner Track[Partner-Track Relevant, not tested by the Architect exam] Design the demo against the buyer's real scenario with limitations identified first, and walk into joint scoping with requirements, candidate patterns, and open questions in hand.

- **03 Feedback loops and SLA management** — Build the decision layer that maps signals to trigger actions to owners, set SLA thresholds from their real sources, and wire regulated checkpoints to run on a schedule.

- **04 Documentation for handoff and audit** — Write the decision, the rejected alternatives, and the tradeoff each resolved while you still hold the reasoning, and carry the control register forward as evidence a reviewer will accept.

- **05 Entry point selection and outcomes** — Choose the route on latency, compliance, and cost with an entry-point-responsibility map for multi-entry-point designs, and capture the before metric, the auditable control, and the reuse note so the outcome document justifies expansion.

#### Sources

- Building with the Claude API (Skilljar): stateless request lifecycle, system prompts, evals and graders, tool use, RAG, prompt caching, code execution.
- Claude 101 (Skilljar): general Claude capabilities and everyday-use framing. (Claude 101 does not carry model-family or context-window teaching per the live catalog; those concepts trace to platform documentation; verify the current model lineup at publish time.)
- AI Capabilities and Limitations (Skilljar): the four-properties decision lens carried forward from earlier modules.
- platform.claude.com/docs: model names, platform capabilities, route availability, residency configuration. Re-verify at build.
- anthropic.com partner program documentation: partner GTM stage definitions, IP-contribution protocols.
- Anthropic Applied AI team documentation: joint-scoping engagement structure and preparation inputs.

---

<!-- CERT -->

**

## Congratulations! You have successfully completed this module.

Module 4 covers the stakeholder communication, lifecycle governance, and go-to-market decisions that turn a working AI deployment into a defensible, scalable business asset.

**The deployment is only as durable as the documentation, governance, and outcome evidence that surrounds it.**

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

M4

Stakeholder Engagement, Lifecycle & Go-to-Market

Stakeholder communication, lifecycle management, and go-to-market strategy.

You Are Here

M5

Team Enablement and Operational Productivity

Team tooling configuration and operational support practices.

Up Next
