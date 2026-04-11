I will implement the functionality to display the source code with line-by-line coverage visualization in the "Result View" page.

### 1. Backend: Enhance Coverage Data Retrieval
I will modify `app/services/runner_service.py` to:
-   Parse the LCOV info to extract execution counts for each line of the *target source file*.
-   Include this detailed line execution data (e.g., a dictionary mapping line number to execution count) in the `ExecuteTestResponse`.
-   Update `app/models/testcase.py` to include a `line_coverage` field in `FileCoverage` or a separate structure to hold this map.

### 2. Backend: Retrieve Source Code Content
I will modify `app/routers/testcase.py` or `app/services/runner_service.py` to:
-   Ensure the `ExecuteTestResponse` includes the full content of the source file being tested. Currently, it might not be returning the raw code.
-   Alternatively, I can fetch the file content using the existing `ProjectService` if the frontend requests it, but bundling it with the execution result is more efficient for this view.

### 3. Frontend: Visualize Coverage
I will modify `Frontend/src/views/ResultView.vue` to:
-   Add a new section (e.g., "Code Coverage Visualization") below the "Coverage Analysis" card.
-   This section will display the source code.
-   I will use the line execution data from the backend to apply CSS classes:
    -   Green background (`bg-green-100`) for lines with execution count > 0.
    -   Red background (`bg-red-100`) for executable lines with execution count == 0.
    -   Neutral/Transparent for non-executable lines (comments, empty lines).
-   I need to handle the mapping carefully, as LCOV only reports executable lines. Lines not in the LCOV report should be treated as non-executable (neutral), not necessarily uncovered (red), unless we know for sure they are executable. Typically, LCOV lists all instrumented lines. If a line is in the source but not in LCOV data, it's usually not executable code.

### Plan Breakdown
1.  **Backend Model Update**: Add `lines: Dict[int, int]` to `FileCoverage` model.
2.  **Backend Logic Update**: Update `_parse_lcov_info` in `runner_service.py` to populate this `lines` map.
3.  **Frontend Update**:
    -   Fetch source code (if not already available).
    -   Render code with line numbers.
    -   Apply coloring based on the `lines` map.

I will start by updating the backend models and parsing logic.