# Best practices: AI visual comparisons

Source: [Best practices for working with AI visual comparisons](https://help.perfecto.io/perfecto-help/content/perfecto/ide/sm-ai-visual-comparison-best-practices.htm)

Related UI doc: [Compare screens with AI vision](https://help.perfecto.io/perfecto-help/content/perfecto/ide/sm-ai-visual-comparison-assistant.htm)

## What it is

AI visual comparison evaluates predefined change categories between screens. You do **not** write free-form descriptions of changes to detect — categories are fixed.

In Scriptless this maps to AI visual comparison commands; in Appium to AI functions.

## Limitations

Detectable categories are predefined for common cases. No free-form “detect this custom change” description.

## Do's and don'ts

**Do:** Review all detected categories in results. Select as **failure criteria** only the categories that should fail the test.

**Don't:** Generally choose **Device** or **Pixel Diff** as failure categories.

| Category | Why noisy |
| --- | --- |
| Device | Clock, battery, network status — almost always differ |
| Pixel Diff | Compression/scaling artifacts — almost always differ |

Those categories exist for rare cases where device chrome or pixel-level diffs are intentionally under test.

## MCP tip

When adding `ai_visual-comparison` via `add_command`, call `get_command_definitions` first and set failure categories intentionally — avoid Device/Pixel Diff unless required.
