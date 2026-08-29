# Best practices: AI validations

Source: [Best practices for working with AI validations](https://help.perfecto.io/perfecto-help/content/perfecto/ide/sm-ai-validations-best-practices.htm)

Validations should be logical, business-oriented, and answerable from the screen (or factual public knowledge / variables).

## Question vs validation

| Type | Nature | Examples |
| --- | --- | --- |
| **Question/query** | Open-ended (what/who/where…) — **not** a validation | How much is the balance? What color is the button? |
| **Validation** | Binary PASS/FAIL | Is the balance equal to $22? Verify the login button is green. Does user Joe appear in the header? |

## Limitations

- Models can err — test prompts with the AI Assistant before baking into Scriptless.
- Not connected to your backend or “the world” beyond the screen + public facts. Time reference is environment **UTC**.
- Enable **Reasoning** for counting/sorting/ordering.

## Semantic approach

AI matches meaning to what is visible (like a human tester), not DOM locators. Prefer validations that state the business meaning clearly (“available balance equals …”) rather than fragile positional guesses.

## Conversation-driven assistant

Use the lab AI Validation Assistant to turn ambiguous asks into objective PASS/FAIL text. Example flow:

1. User: “Does the pizza costs $80?”
2. Assistant may interpret “any pizza” and suggest a clearer sentence.
3. User adds context (“Capsicum one?”).
4. Assistant returns FAIL plus a precise suggestion: “Is the Capsicum pizza price equal to $80?”

The assistant also fixes grammar/typos and works in many languages (best results when matching the app language).

## Wait, time, variables, knowledge

- Loading screens: AI validation can retry until loaded; or add a User Action “Wait for … then continue.”
- Time: ask relative to UTC / timezone conversions.
- Variables and factual checks are allowed if the answer is binary (`Is ${x} between 1 and 10?`).
- Subjective questions (“tasty?”, “beautiful?”) are invalid.
- Missing variables: Assistant may prompt and add a test variable.

## Specialized knowledge

Same `ai.txt` repository pattern as user actions (≤ 2,000 characters). See [ai-user-actions-best-practices.md](ai-user-actions-best-practices.md).

## Do's

- Be specific and objective
- Ask about elements clearly shown on screen
- Examples: “Do the triple black sneakers cost $601?”, “Is Nike the first in the filter list options?”

## Don'ts

- Subjective words (nice, clear, understood)
- Ambiguous counts when items are partially visible or ads confuse counts
- Vague comparatives (“much more expensive”)
- External knowledge you cannot see (“cheaper than at Amazon”)
