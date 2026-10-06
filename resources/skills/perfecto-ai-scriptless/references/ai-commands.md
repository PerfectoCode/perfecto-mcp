# AI commands overview and FAQ

Sources:
- [AI commands FAQ](https://help.perfecto.io/perfecto-help/content/perfecto/ide/sm-ai-commands-faq.htm)
- [AI commands](https://help.perfecto.io/perfecto-help/content/perfecto/sm-commands-and-checkpoints/ai-commands.htm)

## What AI commands do

AI commands (Scriptless) and AI functions (Appium) use natural language — in any language — like a conversation. Benefits:

- Complex validations that may combine multiple traditional steps into one
- Coverage beyond fragile locator-based scripting
- Platform-agnostic steps that adapt better to UI changes

In the Scriptless UI, AI commands live under the **AI** left-sidebar tab. Prefer Perfecto's AI Assistant in the lab when crafting prompts.

Primary MCP command IDs (confirm via `list_commands`):

- `ai_user-action` — perform actions on the DUT
- `ai_validation` — PASS/FAIL assertions
- `ai_visual-comparison` — screen comparison categories

## Licensing FAQ

- AI is **not** on by default for every Perfecto feature — only AI commands/functions.
- A **separate Perfecto AI license** and admin **feature-toggle opt-in** are required.
- If the org opts out later, AI-based commands cannot run and dependent tests fail.
- Data use: see Perforce [Generative AI Policy](https://www.perforce.com/generative-ai-policy).

## Limits and tips

- One AI command can contain up to **30** internal steps; execution limit is **3 minutes** per call. For best results, target **≤ 15** steps.
- Form fill / text extract with AI works on the **default tab** in web sessions (desktop browser, mobile web, WebView) — not native mobile/desktop apps, and not tabs opened mid-flow (Selenium stays on the default tab).
- If answers are inconsistent: refine with the AI Assistant suggestions, then review best-practice docs. Ambiguous prompts are the usual cause.

## Example validation conversation pattern

User: "Is there a sign-up here option for new user?"  
Assistant may suggest: "Is there a sign-up option for new users labeled 'Sign Up Here'?"

Use assistant suggestions as the final validation text when possible.

## Related best practices

- [AI user actions](ai-user-actions-best-practices.md)
- [AI validations](ai-validations-best-practices.md)
- [AI visual comparisons](ai-visual-comparison-best-practices.md)
