# Handle tests

Source: [Handle tests](https://help.perfecto.io/perfecto-help/content/perfecto/ide/scriptless-mobile-handle-tests.htm)

A test is a set of commands and checkpoints. You can create, open, save, save as, edit, and delete tests.

Each save creates a new **snapshot** (version). See [Work with test versions](https://help.perfecto.io/perfecto-help/content/perfecto/ide/sm-work-with-test-versions.htm).

Nested constructs (loops, conditions, logical steps) appear indented with expand/collapse controls. Shortcuts (Windows and macOS): **Ctrl+]** expand all, **Ctrl+[** collapse all.

## Create a new test

1. Top toolbar → **Tests** → **New**
2. Add commands and checkpoints
3. **Tests** → **Save As**

## Open an existing test

1. **Tests** → **Open**
2. Expand folders (defaults: location of open test, else Public)
3. Optional: search by name; sort by name, dates, owner, modified by, parameters
4. Select test → **Open**

Folders: **Public Tests**, **My Tests**, and **Group Tests** (if the user belongs to a group).

## Save / Save As

1. **Tests** → **Save** or **Save As**
2. For Save As: pick folder (create folders via hover + folder button; names cannot contain `\ / : * ? " < > |`)
3. Enter name; optional comments; **Save**

Every save of an existing test creates a new snapshot.

## Edit steps

Toolbar → **Editor Actions**: cut, copy, paste, delete, edit, or exclude lines — then save.

## Delete a test

1. **Tests** → **Open**
2. Hover the test → **Delete test** → confirm **Yes**

## MCP mapping

| UI action | `perfecto_ai_scriptless` action |
| --- | --- |
| New | `create_test` |
| Open / browse | `list_tests` (+ `list_filter_values`) |
| Save | `save_test` (optional `comment` labels `<current>` snapshot) |
| Save As | `save_test_as` |
| Delete | `delete_test` |
| Move folder | `move_test` |
| Versions | `list_snapshots`, `view_snapshot` |
