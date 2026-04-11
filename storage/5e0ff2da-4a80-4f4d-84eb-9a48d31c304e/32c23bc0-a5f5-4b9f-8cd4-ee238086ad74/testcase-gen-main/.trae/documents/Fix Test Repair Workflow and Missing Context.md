I will implement the following changes to ensure the "Fix Test Case" workflow correctly sends the failed test code to the LLM and handles the "0/0/0" result issue.

### 1. Backend: Implement Missing Code Retrieval
I will add the missing `get_task_code` method to `app/services/runner_service.py`.
-   **Method:** `get_task_code(task_id)`
-   **Logic:** It will read the content of `test_runner.c` from the task directory (`workspaces/_tasks/<task_id>/test_runner.c`).
-   **Reason:** This is required by `app/routers/testcase.py` to retrieve the previous failed code when `failed_task_id` is provided. Currently, this method is missing, which would cause a crash if the frontend actually sent the ID.

### 2. Frontend: Enable Passing of Failed Task ID
I will update the frontend to store and send the `failed_task_id`.
-   **Store (`Frontend/src/store/index.js`)**: Add `failedTaskId` to the state and a `setFailedTaskId` action (or merge it into `setFailureContext`).
-   **Result View (`Frontend/src/views/ResultView.vue`)**: When clicking "Fix Test Case", store the current `store.taskId` as the `failedTaskId` in the store.
-   **Generate View (`Frontend/src/views/GenerateView.vue`)**: When constructing the API request body, include `failed_task_id` from the store.

### 3. Explanation of "0/0/0" Results
I will explain to the user that the "0 Passed, 0 Failed, 0 Total" issue occurs because the LLM is currently generating fixes blindly (without seeing the previous code). This often leads to it generating invalid or empty test files that compile but contain no tests to run. Providing the previous code context will allow the LLM to generate proper fixes.