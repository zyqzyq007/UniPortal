# C Unit Test Generator Backend

This is a FastAPI-based backend for generating and executing C unit tests using the Unity framework and DeepSeek LLM.

## Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Environment Variables:**
    Set the `DEEPSEEK_API_KEY` to enable real test generation.
    ```bash
    export DEEPSEEK_API_KEY="your_api_key_here"
    ```
    If not set, the system runs in "Mock Mode", generating placeholder tests.

3.  **Run Server:**
    ```bash
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    ```

## API Endpoints

-   `POST /api/project/upload`: Upload .c or .zip files.
-   `GET /api/project/{id}/structure`: Get file tree and functions.
-   `GET /api/project/{id}/function/{func_id}`: Get function details and code graph.
-   `POST /api/testcase/generate`: Generate Unity tests using LLM.
-   `POST /api/testcase/execute`: Compile and run the generated tests.
-   `GET /api/testcase/{task_id}/result`: Get test execution results.

## Project Structure

-   `app/`: Application code.
    -   `routers/`: API route definitions.
    -   `services/`: Business logic (Project, Parser, LLM, Runner).
    -   `models/`: Pydantic data models.
-   `resources/unity/`: Minimal Unity framework files.
-   `workspaces/`: Stores uploaded projects and execution tasks.

## Testing

### Automated Verification
A verification script `verify_system.py` is included to test the full flow with a sample file.
```bash
python3 verify_system.py
```

### Manual Testing with Apifox
For detailed instructions on how to import APIs and perform manual testing using Apifox, please refer to the [Apifox Testing Guide](APIFOX_GUIDE.md).
