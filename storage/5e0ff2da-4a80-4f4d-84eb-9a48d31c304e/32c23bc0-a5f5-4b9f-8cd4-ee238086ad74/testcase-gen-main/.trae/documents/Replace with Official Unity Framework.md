I will replace the minimal mock Unity framework with the official **ThrowTheSwitch/Unity** framework to provide robust testing capabilities.

### 1. Download Official Framework Files

I will fetch the core files from the official repository and save them to `resources/unity/`:

* `unity.h`

* `unity.c`

* `unity_internals.h` (New dependency required by official Unity)

### 2. Update Runner Service (`app/services/runner_service.py`)

* **File Copying**: Update the logic to copy `unity_internals.h` along with `unity.c` and `unity.h` to the task workspace.

* **Result Parsing**: Update the output parsing logic. Official Unity typically outputs `PASS` instead of `PASSED`, and the format is `filename:line:test_name:PASS`. I will adjust the regex/string matching to robustly capture these standard outputs.

### 3. Verification

* Rerun the verification script to ensure the new framework compiles correctly and the results are parsed accurately.

