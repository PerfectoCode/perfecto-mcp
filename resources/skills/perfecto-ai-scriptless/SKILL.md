---
name: perfecto-ai-scriptless
description: Getting started and authoring guidance for Perfecto AI Scriptless (Scriptless Mobile), including the workspace UI, test lifecycle, execution, control constructs, AI commands, and best practices. Use when working with AI Scriptless for (1) Understanding the interface and how to access it, (2) Creating, opening, saving, or deleting tests, (3) Adding commands, checkpoints, loops, conditions, or logical steps, (4) Executing tests on devices, (5) Writing AI user actions, validations, or visual comparisons, (6) Using Perfecto MCP perfecto_ai_scriptless tools, or any other AI Scriptless tasks.
---

# Perfecto AI Scriptless

Guides for building, running, and managing Perfecto AI Scriptless tests — with MCP tool workflows for the Perfecto MCP server.

Official docs hub: [AI Scriptless interface](https://help.perfecto.io/perfecto-help/content/perfecto/ide/scriptless-mobile-interface.htm)

## Overview

AI Scriptless lets you automate mobile (and, with the right licenses, desktop web) testing without writing traditional scripts. You design tests with a visual editor, predefined commands/checkpoints, and AI natural-language steps that work independently of object locators, UI language, or dynamic content.

**License labeling:**
- With Perfecto AI + Desktop Web licenses → interface labeled **AI Scriptless** (mobile + desktop web).
- Without those licenses → labeled **Scriptless Mobile** (mobile only).
- AI commands require a Perfecto AI license (admin feature-toggle opt-in). Without it, AI commands and related MCP operations will not work.

## Quick Start

1. **Access**: Perfecto landing page → Scriptless Automation → **Build ai scriptless test** (optional: select a real device).
2. **UI**: Learn the [workspace layout](references/interface.md) (toolbar, sidebar, editor, devices, widgets, action panel).
3. **Author**: Create/open/save tests, add AI or classic commands, use loops/conditions/logical steps.
4. **Run**: Execute with a DUT (device under test), then open the Single Test Report.
5. **MCP**: Prefer `perfecto_skills` + `perfecto_ai_scriptless` for programmatic authoring; use `perfecto_help` (category `perfecto` / subcategory `ide`) for live docs.

## MCP Tools Integration

### Skills and Help

- `perfecto_skills` — `list_skills`, `read_skill` (`perfecto-ai-scriptless`), then `list_skill_resources` / `read_skill_resource_uri` for reference files.
- `perfecto_help` — `list_help_category_content` / `read_help_info` with `category_id='perfecto'`, `subcategory_id='ide'` (or `subcategory_id_list=['ide']`).

### AI Scriptless tool (`perfecto_ai_scriptless`)

| Goal | Actions |
| --- | --- |
| Discover tests | `list_filter_values` → `list_tests` |
| Inspect / edit structure | `view_test_structure`, `list_commands`, `get_command_definitions`, `add_command`, `modify_command`, `delete_command`, `set_command_enabled`, `move_command` |
| Control flow | `add_logical_step`, `add_loop`, `add_condition`, `set_condition_expression` |
| Lifecycle | `create_test`, `save_test`, `save_test_as`, `delete_test`, `move_test` |
| Variables / history | `list_test_variables`, `add_test_variable`, `modify_test_variable`, `delete_test_variable`, `list_snapshots`, `view_snapshot` |
| Execute | `execute_test` (after validating device via `perfecto_devices`) |

### Critical MCP rules

- **Licenses**: AI Scriptless MCP actions need Perfecto AI license; desktop web authoring needs Desktop Web license.
- **step_path**: Dot-separated positional path (e.g. `0`, `2.0`, `5.b0.1`). Paths are not persisted and change after inserts/moves/deletes — always `view_test_structure` before the next structure edit.
- **Command policy**: Call `list_commands` first and follow the selection policy in `info` before `add_command`. Prefer primary AI commands (`ai_user-action`, `ai_validation`, `ai_visual-comparison`) when authoring natural-language steps.
- **UI access**: Lab entry is `{cloud_url}/lab/scriptless-mobile/` from `perfecto_user` `read_user`. There is no per-test URL; open tests in the UI by folder/name from `list_tests`.
- **Not in MCP yet**: DataTables, Scheduler, Embedded tests, Object Spy, AI Assistant chat, folder rename/restore snapshot, download as Appium, and similar advanced UI features — guide users to the lab UI / help docs.

### Example workflow (author + run)

1. `perfecto_skills` → `read_skill` → `perfecto-ai-scriptless`
2. `list_commands` (and `get_command_definitions` for argument shapes)
3. `create_test` or `list_tests` → `view_test_structure`
4. `add_command` / control-flow actions as needed; re-`view_test_structure` after each mutation
5. Validate device (`list_real_devices` / virtual / desktop + availability checks)
6. `execute_test` → monitor with `perfecto_execution` (`list_live_executions`, `list_report_executions`)

## Reference Files

### Getting started and UI
- **[getting-started.md](references/getting-started.md)**: What AI Scriptless is, licenses, how to access
- **[interface.md](references/interface.md)**: Top toolbar, left sidebar, test editor, devices pane, widgets, action panel

### Authoring and execution
- **[handle-tests.md](references/handle-tests.md)**: New, open, save, save as, delete, snapshots/versions
- **[execute-tests.md](references/execute-tests.md)**: Run, stop, re-run, DUT selection, reports
- **[control-constructs.md](references/control-constructs.md)**: Conditions, loops, logical steps

### AI commands
- **[ai-commands.md](references/ai-commands.md)**: AI commands overview and FAQ
- **[ai-user-actions-best-practices.md](references/ai-user-actions-best-practices.md)**: Phrasing user actions, forms, install apps
- **[ai-validations-best-practices.md](references/ai-validations-best-practices.md)**: PASS/FAIL validations, do's and don'ts
- **[ai-visual-comparison-best-practices.md](references/ai-visual-comparison-best-practices.md)**: Visual comparison failure categories

## When to Use Each Reference

- **Getting started / interface**: First-time users or UI orientation questions
- **Handle tests / execute / control constructs**: Classic Scriptless authoring and run flows
- **AI command references**: Natural-language steps, validations, visual comparisons, licensing FAQ
- **MCP section above**: When operating through Perfecto MCP tools instead of (or with) the lab UI

## Official documentation

For the full live catalog under Perfecto Help → IDE, start at [AI Scriptless](https://help.perfecto.io/perfecto-help/content/perfecto/ide/get-started-with-scriptless-mobile.htm) and use `perfecto_help` to pull any page under subcategory `ide`.
