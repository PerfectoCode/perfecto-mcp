# Getting started with AI Scriptless

Source: [AI Scriptless](https://help.perfecto.io/perfecto-help/content/perfecto/ide/get-started-with-scriptless-mobile.htm)

## What it is

AI Scriptless automates application testing without writing traditional test code. You design and execute tests using a visual interface, predefined actions, and AI-powered natural-language steps. That reduces scripting while keeping flexibility for complex scenarios.

Reusable components and AI-driven features help improve coverage, speed up automation, and simplify maintenance.

## Licenses and product name

| Cloud licenses | Interface label | Scope |
| --- | --- | --- |
| Perfecto AI + Desktop Web | **AI Scriptless** | Mobile and desktop web, natural-language commands |
| Missing one or both | **Scriptless Mobile** | Mobile testing only |

AI commands also require administrator opt-in (feature toggle). Without the AI license/toggle, AI commands stay inactive and tests that depend on them fail.

Desktop web devices as DUT require both Perfecto AI and Desktop Web licenses.

## How to access

1. On the Perfecto landing page, under **Scriptless Automation**, click **Build ai scriptless test**.
2. (Optional) In **Select device**, pick a real device and click **Select**.

Lab URL pattern (also returned by MCP user info): `https://{cloud}.app.perfectomobile.com/lab/scriptless-mobile/`

## CI/CD

When scripts are ready, invoke them from external tools (for example Jenkins) using Perfecto API script operations. See [Script operations](https://help.perfecto.io/perfecto-help/content/perfecto/automation-testing/script_operations.htm).

## Related help topics

- [AI Scriptless interface](https://help.perfecto.io/perfecto-help/content/perfecto/ide/scriptless-mobile-interface.htm)
- [Author and manage tests](https://help.perfecto.io/perfecto-help/content/perfecto/ide/scriptless-mobile-common-tasks.htm)
- [Use open-device actions while authoring](https://help.perfecto.io/perfecto-help/content/perfecto/ide/scriptless-work-with-open-device.htm)
- [Available commands](https://help.perfecto.io/perfecto-help/content/perfecto/ide/sm-commands.htm) / [Available checkpoints](https://help.perfecto.io/perfecto-help/content/perfecto/ide/sm-checkpoints.htm)
