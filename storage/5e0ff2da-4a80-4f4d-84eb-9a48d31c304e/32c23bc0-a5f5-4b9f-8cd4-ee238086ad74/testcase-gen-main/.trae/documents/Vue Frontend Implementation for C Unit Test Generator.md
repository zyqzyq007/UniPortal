# 基于 Vue 3 的单元测试生成系统前端实现方案

我们将为单元测试生成系统构建一个现代化的、响应式的 Vue 3 前端页面，采用深蓝色主题，并严格遵循“状态机”驱动的导航逻辑。

## 1. 后端接口补充
由于前端需要展示“已有项目列表”，而当前 `openapi.json` 中缺失此接口，我们将首先增强后端：
- **`app/services/project_service.py`**: 添加 `list_projects` 方法，扫描 `workspaces` 目录。
- **`app/routers/project.py`**: 添加 `GET /api/project/list` 路由。

## 2. 前端架构设计
- **核心框架**: Vue 3 (Composition API) + Vite
- **状态管理**: Pinia (存储 `project_id`, `function_id`, `task_id` 等全局状态)
- **路由**: Vue Router (管理 4 个核心页面)
- **样式方案**: Tailwind CSS (深蓝色系主题：`bg-slate-950`, `bg-slate-900`)
- **图标**: Lucide Vue Next
- **代码高亮**: Highlight.js

## 3. 核心页面实现

### 3.1 导航栏 (NavBar.vue)
- 实现顶部轻量化进度条：项目上传 > 项目浏览 > 测试生成 > 执行结果。
- 状态机逻辑：
  - **Project Upload**: 始终可选。
  - **Project Browse**: 仅在选中 `project_id` 后激活。
  - **Test Generation**: 仅在选中 `function_id` 后激活。
  - **Execution Results**: 仅在生成 `task_id` 后激活。

### 3.2 项目上传/列表页 (UploadView.vue)
- **上传区**: 支持 `.c` 或 `.zip` 文件上传。
- **列表区**: 展示已有项目的 ID、名称、状态，点击可快速进入“项目浏览”。
- **API**: `POST /api/project/upload`, `GET /api/project/list`。

### 3.3 项目代码浏览页 (BrowseView.vue)
- **左侧树形区**: 递归展示文件结构，点击文件展开其内部函数列表。
- **右侧代码区**: 集成代码查看器，支持行号和函数定位。
- **操作**: 选中函数后，提供“去生成测试用例”的跳转按钮。
- **API**: `GET /api/project/{id}/structure`, `GET /api/project/{id}/file`。

### 3.4 函数分析 & 测试生成页 (GenerateView.vue)
- **分析展示**: 展示函数签名、起止行、调用关系图谱（简化版）。
- **生成配置**: 选择测试框架（默认 Unity）。
- **实时生成**: 点击生成后展示流式或加载中的测试代码。
- **API**: `GET /api/project/{id}/function/{fid}`, `POST /api/testcase/generate`。

### 3.5 测试执行 & 结果展示页 (ResultView.vue)
- **执行状态**: 实时反馈编译、执行进度。
- **结果统计**: Passed / Failed / Total 仪表盘。
- **覆盖率报告**: 文件/函数/行级覆盖率表格展示。
- **API**: `POST /api/testcase/execute`, `GET /api/testcase/{tid}/result`。

## 4. 实施步骤
1.  **环境初始化**: 创建 `Frontend` 目录及基础配置文件（`package.json`, `tailwind.config.js` 等）。
2.  **后端补全**: 修改 `app/routers/project.py` 和 `app/services/project_service.py`。
3.  **核心组件开发**: 编写 `NavBar.vue` 和全局 Store。
4.  **各页面开发**: 按照业务流依次实现 4 个主页面。
5.  **联调与优化**: 确保 API 调用正确，深蓝色主题视觉一致。

请确认此方案，我将开始为您生成完整的代码实现。
