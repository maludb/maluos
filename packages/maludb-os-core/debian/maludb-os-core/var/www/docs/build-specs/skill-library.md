# The skill library — AI Ops → Skills, and agents reading it (2026-09-27)

**The owner's ask:** a Skills tab under AI Ops to create and maintain the skills available to agents, and a way
for agents to access the skills database.

Skill text lives in the tenant's MaluDB. The kernel keeps who holds which skill (`skill_assignments`) and what
agents proposed (`skill_proposals`). A skill is a **bundle**: SKILL.md plus up to 20 text reference files, at most
256 KB. A bundle is never edited. A change is ingested as a **new version** with lineage, and every earlier
version is kept. An agent gets the **newest enabled** version of each skill it holds, unless its assignment
pins one.

## Screens (super-admin; the tab in `AiOpsNav`)

| Screen | Route | Data |
|---|---|---|
| `skills-library` | `/ai/skills` | `GET /ai/skills/` — one card per skill: the version agents get, the number of versions, who holds it, and "disabled" when no version is enabled. |
| `skills-library-view` | `/ai/skills/<name>[?version=<id>]` | `GET /ai/skills/view.php?name=&version=` — the versions, each with Enable or Disable, the instructions, the reference files and who holds the skill. |
| `skills-library-form` | `/ai/skills/new`, `/ai/skills/<name>/edit` | New, or a new version prefilled from the current one. The fields are a name (fixed once made), a description, the instructions (SKILL.md after its frontmatter) and reference files as path + text rows. |

Who holds which skill, and agents' proposals, stay on `/skills` (linked from both screens).

## Actions (`docs/business-os-action-manifest.md`, Memory & skills)

- **`skill_save`** (`html/ai/skills/save.php`, super, never delegable to agents). `skill_library_save()`:
  - composes SKILL.md from the fields;
  - runs the **same scan** as an import or an agent's proposal;
  - ingests the bundle: a new version, or no change for an identical bundle.

  A new version is enabled at once. The log is `skill.save`, with the scan's findings.
- **`skill_set_enabled`** (`enabled.php`, super). Enables or disables one version. Disabling the newest
  version falls back to the one before it. When no version is left enabled, the answer says how many
  assignments now give nothing. The log is `skill.set_enabled`.

## Agents read the library (Records MCP, `mcp/business_skills.py`)

- **`skill_library`** `{q?}` lists the enabled skills: name, description, newest enabled version, the number of
  enabled versions, and the reference file paths.
- **`skill_read`** `{skill_name, path?, version?}` returns the full SKILL.md, or one reference file, of the newest
  enabled version (or the one named). A path not in the bundle is refused, with the list of files.

Both are read only. They answer people who work here and **agents granted them**, which are ordinary tool grants.
They exist because the Claude harness carries a skill only up to 6,000 characters of persona and gives no file
tool. Before them, a long skill's tail and every reference file were out of an agent's reach. The Hermes harness
reads its skills folder itself.

## Built and proven (2026-09-27)

- **Smoke 32 (9/9), over the agents' door as member 1:**
  - a bad name is refused;
  - a skill is created;
  - a change makes version 2;
  - an identical save changes nothing;
  - disabling version 2 falls back to version 1.
- **Checked directly:** reference files save and read back, and a `.sh` file is refused by the scan. The SMOKE
  skill's versions were then disabled.
- **The tools:** `skill_library` and `skill_read` were tested against the live library, and a path outside the
  bundle was refused. The JEV prompt writer read a reference page and TypeSafe's whole skill in run 373.
- **Typechecked.** The screens wait on the owner's web deploy.
