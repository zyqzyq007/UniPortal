# C Unit Test Generator Frontend

A modern Vue 3 frontend for the C Unit Test Generator system.

## Features
- **Project Upload**: Upload .c or .zip projects.
- **Code Browser**: Left tree navigation with function-level exploration.
- **Test Generation**: LLM-powered test case generation based on function analysis.
- **Result Dashboard**: Real-time execution status and code coverage visualization.

## Tech Stack
- **Framework**: Vue 3 (Composition API)
- **State**: Pinia
- **Router**: Vue Router
- **Style**: Tailwind CSS (Dark Blue Theme)
- **Icons**: Lucide Vue
- **Code Highlighting**: Highlight.js

## Getting Started

1.  **Install Node.js** (v18+ recommended)
2.  **Install Dependencies**:
    ```bash
    npm install
    ```
3.  **Run Development Server**:
    ```bash
    npm run dev
    ```
4.  **Build for Production**:
    ```bash
    npm run build
    ```

## Project Structure
- `src/views/`: Contains the 4 main stage pages.
- `src/components/`: Reusable UI components like NavBar.
- `src/store/`: Global state management for navigation state machine.
- `src/router/`: Navigation guards based on project/function/task state.
