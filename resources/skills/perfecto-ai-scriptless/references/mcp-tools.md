# Perfecto MCP tools for AI Scriptless

Use with `perfecto_skills` (this skill) and `perfecto_ai_scriptless`. For live docs, `perfecto_help` with `category_id='perfecto'`, `subcategory_id='ide'`.

## Skills and Help

| Tool | Typical actions |
| --- | --- |
| `perfecto_skills` | `list_skills`, `read_skill` (`perfecto-ai-scriptless`), `list_skill_resources`, `read_skill_resource_uri` / `_list`, `batch` |
| `perfecto_help` | `list_help_category_content`, `read_help_info` |

## `perfecto_ai_scriptless` actions by goal

| Goal | Actions |
| --- | --- |
| Discover tests | `list_filter_values` → `list_tests` |
| Inspect / edit structure | `view_test_structure`, `list_commands`, `get_command_definitions`, `add_command`, `modify_command`, `delete_command`, `set_command_enabled`, `move_command` |
| Control flow | `add_logical_step`, `add_loop`, `add_condition`, `set_condition_expression` |
| Lifecycle | `create_test`, `save_test`, `save_test_as`, `delete_test`, `move_test` |
| Variables / history | `list_test_variables`, `add_test_variable`, `modify_test_variable`, `delete_test_variable`, `list_snapshots`, `view_snapshot` |
| Execute | `execute_test` (after validating device via `perfecto_devices`) |

## Related tools

| Tool | Use for |
| --- | --- |
| `perfecto_user` | Cloud URL / lab base (`…/lab/scriptless-mobile/`) |
| `perfecto_devices` | Real / virtual / desktop DUT discovery and availability |
| `perfecto_execution` | Live executions and reports after `execute_test` |

## Not supported by MCP yet

DataTables, Scheduler, Embedded tests, Object Spy, AI Assistant chat, folder rename, restore snapshot, download as Appium, and similar advanced UI features. Guide users to the lab UI and Perfecto Help instead of inventing API support.
