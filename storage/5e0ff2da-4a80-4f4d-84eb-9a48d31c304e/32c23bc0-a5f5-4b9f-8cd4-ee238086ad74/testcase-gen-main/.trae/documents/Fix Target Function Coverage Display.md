I will modify `app/routers/testcase.py` to ensure the streaming generation endpoint correctly records the target function's start and end lines.

### Backend Changes
1.  **Edit `app/routers/testcase.py`**:
    - Update `generate_testcase_stream` function.
    - Pass `start_line` and `end_line` from `target_func` to `RunnerService.create_task`.

This ensures that when the test is executed, the result metadata includes the function boundaries, allowing the frontend to filter the displayed source code to *only* the target function as requested.
