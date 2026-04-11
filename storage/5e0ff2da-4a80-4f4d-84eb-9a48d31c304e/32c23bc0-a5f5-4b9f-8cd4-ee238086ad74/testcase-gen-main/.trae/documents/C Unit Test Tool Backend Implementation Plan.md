Based on your requirements, I have designed a plan to implement the C Unit Test Generation Tool backend using FastAPI.

# Backend Implementation Plan for C Unit Test Tool

## 1. Project Initialization & Dependencies
- Create a modular project structure:
  - `app/`: Main application code
  - `app/routers/`: API endpoints
  - `app/services/`: Business logic (Parser, LLM, Runner)
  - `app/models/`: Pydantic data models
  - `resources/unity/`: Minimal Unity test framework files (`unity.h`, `unity.c`)
  - `workspaces/`: Directory to store uploaded projects
- Define `requirements.txt`: `fastapi`, `uvicorn`, `python-multipart`, `pycparser`, `httpx` (for API calls), `aiofiles`.

## 2. Core Service Implementation
### A. Project & File Management (`services/project_service.py`)
- **Upload**: Handle `.c` and `.zip` uploads.
- **Workspace**: Create unique directories per project (using UUID/Timestamp).
- **File Access**: helper methods to read file content safely.

### B. Code Analysis (`services/parser_service.py`)
- **Primary Strategy**: Attempt parsing with `pycparser` to build an AST.
- **Fallback Strategy**: Use Regular Expressions to extract function signatures if AST parsing fails (common with missing headers).
- **Code Graph**: Extract basic variable usage and function calls for the "Code Graph" requirement.

### C. LLM Integration (`services/llm_service.py`)
- **Client**: Implement an async client for DeepSeek API.
- **Prompt Engineering**: Construct the prompt using project context + function code + code graph.
- **Output Parsing**: Extract the C code block from the LLM response.

### D. Test Execution (`services/runner_service.py`)
- **Setup**: Copy `unity.h` and `unity.c` to the project workspace.
- **Compilation**: Use `gcc` to compile the generated test file + source file + unity framework.
- **Execution**: Run the binary and capture `stdout`/`stderr`.
- **Result Parsing**: Parse Unity's text output to structured JSON (Pass/Fail counts).

## 3. API Implementation (`routers/`)
Implement the following endpoints strictly according to your interface definition:
1.  `POST /api/project/upload`: Project creation.
2.  `GET /api/project/{id}/structure`: Return file tree and function list.
3.  `GET /api/project/{id}/file`: Get file content.
4.  `GET /api/project/{id}/function/{func_id}`: Get function detail & graph.
5.  `POST /api/testcase/generate`: Call LLM to create tests.
6.  `POST /api/testcase/execute`: Compile and run tests.
7.  `GET /api/testcase/{task_id}/result`: Return execution results.

## 4. Verification
- Create a sample `demo.c` file.
- Start the server.
- Verify the full flow: Upload -> Parse -> Generate (Mock/Real) -> Execute -> Result.
