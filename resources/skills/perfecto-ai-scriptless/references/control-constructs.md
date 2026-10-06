# Conditions, loops, and logical steps

Source: [Work with conditions, loops, or logical steps](https://help.perfecto.io/perfecto-help/content/perfecto/ide/scriptless-mobile-execution-control-constructs.htm)

These constructs control test execution flow. In the UI they are added from the top toolbar. In MCP use `add_condition`, `add_loop`, and `add_logical_step`.

## Conditions

Toolbar **Condition** icon. Splits execution into:

- **On Success** (Then) — condition evaluated successfully
- **On Failure** (Else) — error or unsuccessful evaluation

Conditions evaluate the result of a statement function (including Wait). Typical pattern: put a validation (Find, Text checkpoint, AI validation, …) as the statement.

Rules:

- Every condition should have at most one command set as the statement.
- Commands with nested validations cannot be the statement.
- Without a statement, the condition will not behave as expected.
- Setting a statement updates that command's **On Error** policy.
- Either branch may be empty (continue after the condition).

Edit parameters via the parameters pane (double-click the command).

### MCP

- `add_condition` — creates IfStatement with Then/Else (`b0` / `b1` in `step_path`)
- `set_condition_expression` — set/update the expression
- Nest steps with `parent_path` pointing at a Branch path from `view_test_structure`

## Loops

Toolbar **Loop** icon. Repeat a set of commands:

- Fixed repetition count, or
- Iterate a DataTable (each iteration uses the active row; automated commands)

UI flow: select adjacent same-level commands → Loop → configure count, Number variable, or DataTable in the parameters pane.

Only **Number** variables can drive loop counts. DataTables are UI/API advanced features — **not yet supported by Perfecto MCP**; use the lab UI for DataTable-driven loops.

### MCP

- `add_loop` with `count` (default 1)
- Add child steps via `parent_path` = loop `step_path`

## Logical steps

Group commands into a labeled logical step (groups can nest).

UI: select commands → Logical step icon. Double-click to edit parameters.

### MCP

- `add_logical_step` with optional `label`
- Insert children with `parent_path`
