---
name: perfecto-ai-scriptless
description: Author, run, and troubleshoot Perfecto AI Scriptless (also called Scriptless Mobile) tests — workspace UI, DUT execution, loops/conditions, AI user actions, AI validations, visual comparisons, and Perfecto MCP perfecto_ai_scriptless workflows. Use this skill whenever the user mentions AI Scriptless, Scriptless Mobile, Perfecto scriptless, natural-language test steps, AI commands, AI validation, AI user action, visual comparison, DUT, scriptless lab, or wants to create/edit/run Perfecto scriptless tests via UI or MCP — even if they do not say the exact product name.
---

# Perfecto AI Scriptless

Teach agents how to help users with Perfecto AI Scriptless: product behavior, licenses,
lab UI, and MCP authoring/execution. Prefer this skill over guessing.

Official docs hub: [AI Scriptless interface](https://help.perfecto.io/perfecto-help/content/perfecto/ide/scriptless-mobile-interface.htm)

## When this skill loads

1. Read this `SKILL.md` first.
2. Load only the reference files needed for the user's question (see [Reference files](#reference-files)).
3. For live Perfecto Help pages not covered here, use `perfecto_help` with `category_id='perfecto'` and `subcategory_id='ide'`.
4. Explain **why** a step matters when the rule prevents broken tests (licenses, `step_path`, command policy).

## Licenses (check early)

AI Scriptless behavior depends on cloud licenses:

| Licenses present | UI label | Scope |
| --- | --- | --- |
| Perfecto AI + Desktop Web | **AI Scriptless** | Mobile + desktop web, natural-language commands |
| Missing one or both | **Scriptless Mobile** | Mobile only |

- AI commands need Perfecto AI **and** admin feature-toggle opt-in. Without them, AI steps stay inactive and dependent tests fail.
- Desktop web as DUT needs Perfecto AI **and** Desktop Web.
- If MCP AI Scriptless calls fail with license/feature errors, tell the user to contact their Perfecto admin — do not invent workarounds.

## Quick start (UI)

1. Open Perfecto → **Scriptless Automation** → **Build ai scriptless test** (optional: pick a real device).
2. Lab URL: `https://{cloud}.app.perfectomobile.com/lab/scriptless-mobile/` (also from `perfecto_user` → `read_user`).
3. Orient on the workspace — read [interface.md](references/interface.md) if the user asks about toolbar, sidebar, editor, devices, or widgets.
4. Create/open/save tests, add AI or classic commands, then run with a DUT and open the Single Test Report.

## Agent rules for MCP authoring

Follow these when using `perfecto_ai_scriptless` (why in parentheses):

1. **Consult skills/help before inventing product behavior** — Perfecto Scriptless rules are license- and UI-specific.
2. **Call `list_commands` before `add_command`** and follow the selection policy in the tool `info` field. Prefer primary AI commands: `ai_user-action`, `ai_validation`, `ai_visual-comparison` for natural-language steps.
3. **Call `get_command_definitions` before filling arguments** so parameter names/types match the repository.
4. **Treat `step_path` as ephemeral** (e.g. `0`, `2.0`, `5.b0.1`). Perfecto does not persist paths; they shift after insert/move/delete. Always `view_test_structure` before the next structure edit — never reuse a path from an older mutation response.
5. **Re-`view_test_structure` after every structure mutation** before the next edit.
6. **Validate the device before `execute_test`**: resolve DUT via `perfecto_devices`, check real-device availability, then execute; monitor with `perfecto_execution`.
7. **Do not invent per-test URLs.** Only lab entry exists; open tests in the UI by folder/name from `list_tests`.
8. **Capabilities not in MCP yet** (DataTables, Scheduler, Embedded tests, Object Spy, AI Assistant chat, restore snapshot, download as Appium, etc.): send the user to the lab UI and the matching help/reference — do not fake support.

Full action catalog: [mcp-tools.md](references/mcp-tools.md).

### Author + run workflow

```
1. list_commands (+ get_command_definitions as needed)
2. create_test OR list_tests → view_test_structure
3. add_command / add_logical_step / add_loop / add_condition …
4. view_test_structure again after each mutation
5. Validate device (real / virtual / desktop)
6. execute_test → list_live_executions / list_report_executions
```

## Phrase AI steps well

When helping write natural-language steps, load the matching reference:

- User actions → [ai-user-actions-best-practices.md](references/ai-user-actions-best-practices.md) — describe the **goal**, not locators; keep actions ≤ ~15 internal steps / 3 minutes.
- Validations → [ai-validations-best-practices.md](references/ai-validations-best-practices.md) — binary PASS/FAIL only, not open questions.
- Visual comparisons → [ai-visual-comparison-best-practices.md](references/ai-visual-comparison-best-practices.md) — avoid Device / Pixel Diff as failure categories unless intentional.
- FAQ / limits → [ai-commands.md](references/ai-commands.md)

## Reference files

Load on demand (one level deep):

| Need | File |
| --- | --- |
| What it is, licenses, access | [getting-started.md](references/getting-started.md) |
| Workspace UI layout | [interface.md](references/interface.md) |
| New/open/save/delete/versions | [handle-tests.md](references/handle-tests.md) |
| Run / stop / DUT / reports | [execute-tests.md](references/execute-tests.md) |
| Conditions, loops, logical steps | [control-constructs.md](references/control-constructs.md) |
| MCP action map | [mcp-tools.md](references/mcp-tools.md) |
| AI commands FAQ | [ai-commands.md](references/ai-commands.md) |
| AI user-action phrasing | [ai-user-actions-best-practices.md](references/ai-user-actions-best-practices.md) |
| AI validation phrasing | [ai-validations-best-practices.md](references/ai-validations-best-practices.md) |
| AI visual comparison | [ai-visual-comparison-best-practices.md](references/ai-visual-comparison-best-practices.md) |

## Official documentation

Live catalog: [AI Scriptless](https://help.perfecto.io/perfecto-help/content/perfecto/ide/get-started-with-scriptless-mobile.htm). Prefer `perfecto_help` for pages under subcategory `ide` when a reference is missing or may be outdated.
