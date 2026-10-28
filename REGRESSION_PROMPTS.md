# Perfecto MCP Server - Regression Test Prompts

A curated set of natural-language prompts designed to trigger **every action of every tool** exposed by the Perfecto MCP server. Copy-paste each prompt into your MCP-connected AI assistant to verify that the corresponding tool action is invoked and returns a valid response.

> **Prerequisites**: A valid Perfecto security token and `PERFECTO_CLOUD_NAME` must be configured. Replace placeholder IDs (`{device_id}`, `{test_id}`, `{execution_id}`, and so on) with real values from your cloud before running.
>
> **Writes persist immediately.** AI Scriptless create, edit, move, save, and delete actions change the repository as soon as they succeed. Run those prompts against a disposable test (the `create_test` prompt below), and run `delete_test` last. `execute_test` reserves a device. `stop_live_executions` stops a live run — use an execution you started.
>
> **AI Scriptless license.** Section 6 requires the Perfecto AI license (admin feature-toggle opt-in). Desktop web authoring also requires the Desktop Web license.

---

## 1. User (`perfecto_user`)

### 1.1 read_user

```
Show me my current Perfecto user and the cloud I am connected to, including the cloud name and cloud URL.
```

---

## 2. Devices (`perfecto_devices`)

### 2.1 read_selenium_grid_info

```
Show me the Perfecto Selenium Grid URL for Selenium and Appium.
```

### 2.2 list_real_devices

```
List all available real Perfecto devices (iOS and Android, phones and tablets).
```

### 2.3 read_real_device_info

```
Show me the detailed information for real device ID {device_id}, including whether it is available and not in use.
```

### 2.4 list_virtual_devices

```
List all available Perfecto virtual devices (iOS simulators and Android emulators).
```

### 2.5 list_desktop_devices

```
List all available Perfecto desktop browser devices.
```

---

## 3. Execution (`perfecto_execution`)

### 3.1 list_live_executions

```
List all live Perfecto executions, including mobile, tablet, and desktop browser.
```

### 3.2 stop_live_executions

```
Stop the live Perfecto execution with ID {execution_id}. Make sure it is that execution before stopping it.
```

### 3.3 list_report_names

```
List all Perfecto report names (test names).
```

### 3.4 list_filter_values

```
List the valid filter values for Perfecto execution reports: status, owner, platform, OS, browser, device, job name, trigger, tag, OS version, and failure reason.
```

### 3.5 list_report_executions

```
List finished Perfecto executions from the last 7 days. Use only filter values that exist in the execution reports. Stop after the first page.
```

### 3.6 read_report_execution

```
Read the command summary for Perfecto report execution ID {execution_id}, and render the execution URL as a markdown link.
```

---

## 4. Help (`perfecto_help`)

### 4.1 list_help_categories

```
List all Perfecto help categories and their subcategories.
```

### 4.2 list_help_category_content

```
List the Perfecto help articles in category "perfecto" and subcategory "ide".
```

### 4.3 read_help_info

```
Read the Perfecto help article "scriptless-mobile-interface" from category "perfecto" and subcategory "ide".
```

### 4.4 list_real_devices_extended_commands

```
List Perfecto's extended RemoteWebDriver commands (function references) for real devices.
```

### 4.5 read_real_devices_extended_command_info

```
Read the detailed help for Perfecto extended command ID {command_id}, and render its URL as a markdown link.
```

---

## 5. Skills (`perfecto_skills`)

### 5.1 list_skills

```
List all available Perfecto skills.
```

### 5.2 read_skill

```
Read the skill definition for "perfecto-ai-scriptless".
```

### 5.3 list_skill_resources

```
List all resources in the "perfecto-ai-scriptless" skill.
```

### 5.4 read_skill_resource_uri

```
Read the skill resource at URI "perfecto-skill-perfecto-ai-scriptless://references/getting-started.md".
```

### 5.5 read_skill_resource_uri_list

```
Read these two skill resources at once: "perfecto-skill-perfecto-ai-scriptless://references/getting-started.md" and "perfecto-skill-perfecto-ai-scriptless://references/execute-tests.md".
```

### 5.6 batch

```
In a single perfecto_skills batch call, list all skills and read the "perfecto-ai-scriptless" skill definition.
```

---

## 6. AI Scriptless (`perfecto_ai_scriptless`)

Run the write prompts against the test created in 6.8. `{test_id}` is an item key such as `PRIVATE:MCP Regression/MCP Regression Test.xml`. `{step_path}` comes from `view_test_structure` (for example `0`, `2.0`, `5.b0.1`) and is only valid until the next insert, move, or delete.

### 6.1 list_filter_values

```
List the valid AI Scriptless test filter values for test name and owner.
```

### 6.2 list_tests

```
List my private AI Scriptless tests. Use a test name and owner that list_filter_values says exist. Stop after the first page.
```

### 6.3 view_test_structure

```
Show the hierarchical structure of AI Scriptless test {test_id}, including each step_path.
```

### 6.4 view_test_step

```
Show the full configuration of step {step_path} in AI Scriptless test {test_id}, including current argument values, data sources, and parameters that are not set yet.
```

### 6.5 list_commands

```
List the AI Scriptless command catalog and the command selection policy. Then list checkpoint commands only.
```

### 6.6 get_command_definitions

```
Get the parameter definitions for AI Scriptless commands "ai_user-action" and "ai_validation", including mandatory and optional parameter names.
```

### 6.7 list_test_variables

```
List every variable and runtime parameter declared by AI Scriptless test {test_id}, including the DUT device parameter.
```

### 6.8 create_test

```
Create a new empty private AI Scriptless test named "MCP Regression Test" in folder "MCP Regression".
```

### 6.9 add_test_variable

```
On AI Scriptless test {test_id}, add a string variable named "username" with value "regression".
```

### 6.10 modify_test_variable

```
On AI Scriptless test {test_id}, change the variable "username" to "regression-updated".
```

### 6.11 delete_test_variable

```
On AI Scriptless test {test_id}, delete the variable "username". Do not delete DUT.
```

### 6.12 add_command

```
On AI Scriptless test {test_id}, add an AI user action whose action text is "Tap on the Login button". Keep the action text inside the command arguments, not as the tool action.
```

### 6.13 modify_command

```
On AI Scriptless test {test_id}, change step {step_path} so its action text is "Tap on the Sign in button". Leave every other argument as it is. Read the step first so the argument names match the command definition.
```

### 6.14 set_command_enabled

```
On AI Scriptless test {test_id}, disable step {step_path}, then enable it again.
```

### 6.15 set_command_error_policy

```
On AI Scriptless test {test_id}, set the on-fail result of command step {step_path} to CATCH.
```

### 6.16 add_logical_step

```
On AI Scriptless test {test_id}, add a group labeled "Login".
```

### 6.17 add_loop

```
On AI Scriptless test {test_id}, add a loop that repeats 2 times.
```

### 6.18 add_condition

```
On AI Scriptless test {test_id}, the step immediately before the insertion point must already be a command with on-fail CATCH. Add a condition labeled "Home visible" right after that step. Do not set an expression on the condition.
```

### 6.19 set_condition_expression

This action is retired. A successful regression returns the explanation that a condition follows a CATCH step, not a saved expression.

```
On AI Scriptless test {test_id}, set the condition expression at step {step_path} to "home screen is visible" using set_condition_expression.
```

### 6.20 move_command

```
On AI Scriptless test {test_id}, move step {step_path} into the group at parent step {parent_path}. Read the structure again first and use the current paths.
```

### 6.21 delete_command

```
On AI Scriptless test {test_id}, delete step {step_path}. Read the structure again first and use the current path.
```

### 6.22 save_test

```
Save AI Scriptless test {test_id} with the comment "MCP regression".
```

### 6.23 list_snapshots

```
List the snapshot history for AI Scriptless test {test_id}, including the current marker and the UUID history entries.
```

### 6.24 view_snapshot

```
Show the structure of historical snapshot {snapshot_id} for an AI Scriptless test. Use a UUID from list_snapshots, not the current marker.
```

### 6.25 save_test_as

```
Save a copy of AI Scriptless test {test_id} as "MCP Regression Test Copy" in folder "MCP Regression", with the comment "MCP regression copy".
```

### 6.26 move_test

```
Move AI Scriptless test {test_id} into folder "MCP Regression/Archive", keeping its visibility. Tell me the new item key.
```

### 6.27 execute_test

```
Run AI Scriptless test {test_id} on a real device that is available and not in use. Pass that device in devices_under_test under the DUT parameter name from the test's variables, using device_type "real" and the device_id from the real-device list. Do not use device_type, device_under_test, or devices as top-level arguments. After it starts, show which device each parameter resolved to.
```

### 6.28 delete_test

```
Delete AI Scriptless test {test_id}. This must be the disposable MCP Regression test (or its copy), not a shared test.
```

---

## 7. Tools (`perfecto_tools`)

### 7.1 version

```
What Perfecto MCP version am I running, and on which platform?
```

### 7.2 check_updates

```
Is there a newer Perfecto MCP release than the one I am running? If so, show the release notes and download links. If the update check cannot reach GitHub, still tell me the current version.
```

---

## Full Workflow Regression

The following prompt chains an end-to-end workflow across every tool. Run it as a single conversation. It creates a disposable test, edits it, and deletes it. It reserves a device only if you leave the optional execution steps in.

```
Using Perfecto MCP, do the following in order. Work only on a disposable private test named "MCP Regression Test" in folder "MCP Regression". Do not open, edit, or delete any other test. After every structure edit, read the test structure again and use the new step_path; never reuse a path from an earlier response.

1. Show my Perfecto user and cloud URL.
2. Show the MCP version and whether a newer release exists.
3. Show the Selenium Grid URL, then list real, virtual, and desktop devices. Read the details of the first real device that is available and not in use.
4. List live executions. Do not stop any.
5. List execution-report filter values, list report names, list finished executions from the last 7 days (first page only), and read the first report if one exists.
6. List help categories, list articles under category "perfecto" and subcategory "ide", and read help id "scriptless-mobile-interface". Then list extended real-device commands and read the first command.
7. In one skills batch, list all skills and read "perfecto-ai-scriptless". Then list that skill's resources and read "perfecto-skill-perfecto-ai-scriptless://references/getting-started.md" and "perfecto-skill-perfecto-ai-scriptless://references/execute-tests.md" together.
8. List AI Scriptless filter values, then list my private tests (first page only).
9. Create "MCP Regression Test". List its variables. Add string variable "username" = "regression", change it to "regression-updated", then delete it. Do not delete DUT.
10. List commands (catalog and checkpoint-only) and get definitions for "ai_user-action" and "ai_validation".
11. Add an AI user action "Tap on the Login button", read that step, then change the text to "Tap on the Sign in button". Disable the step, then enable it again.
12. Add an AI validation "The home screen is visible", set its on-fail result to CATCH, then add a condition labeled "Home visible" immediately after it. Do not set a condition expression. If you try set_condition_expression, report the error and continue.
13. Add a group labeled "Login" and a loop that repeats 2 times. Move the user-action step into the group. Delete the loop. Read the structure before each of these edits.
14. Save the test with comment "MCP regression". List snapshots and view the latest UUID snapshot (not the current marker).
15. Save a copy as "MCP Regression Test Copy" in the same folder. Move the copy to "MCP Regression/Archive". Delete the copy, then delete the original.
16. Optional, only if a free real device exists and I confirm: run the original test before deleting it, passing the device on DUT inside devices_under_test, then watch it with live executions and the report list. Do not stop anyone else's execution.
```
