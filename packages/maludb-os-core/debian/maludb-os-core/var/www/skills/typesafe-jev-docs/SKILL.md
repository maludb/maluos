---
name: typesafe-jev-docs
description: A dated local copy (2026-09-27) of the TypeSafe documentation pages the typesafe-ai skill tells you to read — System One, how to build with it, state, the question primitives (Noul, Choice, Score), confidence and the HTTP API — for an agent on this server, which cannot reach the live docs. Read the page the task needs, not all of them.
---

# TypeSafe docs — local copy

The typesafe-ai skill says to read TypeSafe's **live** docs (https://docs.typesafe.ai). An agent on this server
has no web access. These pages were fetched on **2026-09-27** from `https://docs.typesafe.ai/<page>.md`,
for model `jev-1.13` as the kernel pins it. Say you worked from this copy of that date. Where a detail may
have changed since (limits, prices, new fields), mark it for a person to check against the live docs.

| Read when | Page |
|---|---|
| What System One is, and how it differs from an LLM | [references/concepts_system-one.md](references/concepts_system-one.md) |
| Designing a workflow of judgments (the longest page: read the section you need) | [references/concepts_how-to-build-with-system-one.md](references/concepts_how-to-build-with-system-one.md) |
| Shaping the state a question reads | [references/concepts_state.md](references/concepts_state.md) |
| Choosing a question type; one judgment per question; asking questions together | [references/primitives.md](references/primitives.md) |
| Writing a Noul (a condition that holds or not) | [references/primitives_noul.md](references/primitives_noul.md) |
| Writing a Choice (one of a defined set) | [references/primitives_choice.md](references/primitives_choice.md) |
| Writing a Score (a degree, with levels) | [references/primitives_score.md](references/primitives_score.md) |
| Probabilities, confidence and thresholds | [references/confidence.md](references/confidence.md) |
| The request and answer format | [references/api.md](references/api.md) |

The pages are TypeSafe's, copied unchanged. They are reference, not instructions to you.
