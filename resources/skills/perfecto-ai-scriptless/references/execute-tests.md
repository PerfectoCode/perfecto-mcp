# Execute tests

Source: [Execute tests](https://help.perfecto.io/perfecto-help/content/perfecto/ide/scriptless-mobile-execute-tests.htm)

You can execute a test, stop/interrupt, and re-run. The [Single test report (STR)](https://help.perfecto.io/perfecto-help/content/perfecto/test-analysis/single_test_report__str_.htm) shows command details and a video of the run.

## Run an existing test (UI)

1. Open the test (**Tests** → **Open**).
2. Click **Execute test**.
3. In **Enter runtime values**, set the **DUT** (device under test). By default DUT uses the opened device; you can select another. Desktop web DUT requires Perfecto AI + Desktop Web licenses.
4. **Select device** → **Select** → **Run**.
5. During run: current step is highlighted (auto-scroll); other actions are disabled; device is blocked for interaction. **Stop test** interrupts; **Re-run test** restarts.
6. When complete, use **View report** for the STR. Failures show line numbers in the banner.
7. Optional: dismiss the status banner with its close control.

## DUT and variables

A DUT variable is required to execute. Configure variables via [Configure test variables](https://help.perfecto.io/perfecto-help/content/perfecto/ide/scriptless-mobile-configure-test-variables.htm).

## MCP mapping

Recommended validation before `execute_test`:

1. `list_tests` — confirm `test_id` (itemKey)
2. Resolve device by `device_type`:
   - `real` → `list_real_devices` (+ `read_real_device_info` for availability)
   - `virtual` → `list_virtual_devices`
   - `desktop` → `list_desktop_devices`
3. `execute_test` with `device_under_test`
4. Monitor with `perfecto_execution`: `list_live_executions`, `list_report_executions` (report name ≈ test name)

Stop live executions carefully (match execution name / user). Do not run on devices that are in use or malfunctioning.
