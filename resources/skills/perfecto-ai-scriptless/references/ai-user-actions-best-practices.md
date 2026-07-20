# Best practices: AI user actions

Source: [Best practices for working with AI user actions](https://help.perfecto.io/perfecto-help/content/perfecto/ide/sm-ai-user-action-best-practices.htm)

Write the action once; run across devices/OS. Describe the **logical goal**, not locators.

In Scriptless, use AI commands ([AI commands](https://help.perfecto.io/perfecto-help/content/perfecto/sm-commands-and-checkpoints/ai-commands.htm)). For Appium, see [AI functions](https://help.perfecto.io/perfecto-help/content/perfecto/automation-testing/ai-functions.htm).

## Performance

- Phrase each User Action so it resolves to **≤ 15** steps and finishes in **under 3 minutes**.
- Enable **Reasoning** when counting, sorting, or ordering needs extra reasoning resources.

## What works well

- Common UI: hamburger, help, notifications
- Click buttons, links, icons, FABs
- Type into empty fields or replace text
- Radio buttons, checkboxes, sliders
- Tabs, lists, navbars
- Dismiss interrupting popups/notifications
- Browser navigation (go to, back, forward, refresh, clean)
- Install mobile apps (see install section)

Still evolving / may be unreliable: inline labels relative to fields, table cell/row actions, color pickers. Not yet fully tested: append text to existing field content. LLMs can make mistakes.

## Why AI user actions help

- **Write once, run everywhere** — no device-specific locators
- **Survive UI renames/moves** — goal-based instructions
- **Wait instead of fail** — instruct wait/retry/dismiss modals/progress
- **Focus** — “focus on / zoom into …” for dense UIs

## Do's and don'ts

| Don't | Do | Why |
| --- | --- | --- |
| Move mouse to Cart button bottom-right | On the profile page, open the shopping cart | Logical goal, not coordinates/labels |
| Register a new account | Fill the form: Enter "Jill A. Smith" in the name fields… | Enough concrete detail |
| Click the red shoes | From search results, select the red sneakers that cost $30 | Disambiguate similar items |
| Pay by card | Fill the form: In the drop down, select credit card… | Triggers form-fill tooling for dropdowns |

## Specialized knowledge (`ai.txt`)

For domain UIs (seat maps, dashboards, canvases):

1. Write instructions in plain text (max **2,000** characters; larger files are ignored).
2. Save as `ai.txt`.
3. Upload to the **root** of the Perfecto Repository.
4. Reloads on login; applied as general user instructions for AI assistants/commands.

## Install mobile apps via User Action

Example prompts: `Install public:/path/myapp.ipa`, `Install ${myApp} on the device, open it and log in`.

Configure instrumentation in the UI widget (Sensor, WebView, Secured Screen, Resign). iOS notes:

- Virtual iOS: use `appname.zip`
- Real iOS: Resign Application on by default (mandatory unless WebView changes rules)

See [Install a mobile app using AI User Actions](https://help.perfecto.io/perfecto-help/content/perfecto/ide/sm-ai-user-action-install-app.htm).

## Fill forms

Prefer **one** prompt that fills many fields, then a separate submit action.

Supported: text/textarea, native `<select>`, `date` (YYYY-MM-DD), checkbox/radio, common combobox libraries.

Not supported: masked inputs, custom date pickers, sliders, file upload, rich-text editors, chip/tag inputs, cross-origin iframes, closed Shadow DOM, canvas inputs.
