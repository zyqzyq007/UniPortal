# Apifox 接口测试指南

本文档详细说明如何使用 Apifox 对 C 单元测试生成工具的后端接口进行全流程测试。

## 1. 准备工作

### 1.1 启动后端服务
确保后端服务已启动：
```bash
# 在项目根目录下执行
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
*   服务地址：`http://127.0.0.1:8000`

### 1.2 准备测试文件
准备一个简单的 C 语言文件（例如 `demo.c`），内容如下：
```c
int add(int a, int b) {
    return a + b;
}
```

### 1.3 导入接口定义到 Apifox
1.  打开 Apifox。
2.  新建项目或进入已有项目。
3.  点击 **“项目设置” -> “导入数据”**。
4.  选择 **“OpenAPI / Swagger”**。
5.  导入方式选择 **“文件”**，上传项目根目录下的 `openapi.json` 文件。
6.  点击 **“确定”**，完成接口导入。

### 1.4 设置环境变量
为了方便接口之间传递数据（如 `project_id`, `task_id`），建议在 Apifox 右上角设置“环境变量”：
*   **环境名称**：`Local`
*   **前置 URL**：`http://127.0.0.1:8000`
*   **全局变量**：
    *   `project_id`: (留空，后续自动填充)
    *   `function_id`: (留空)
    *   `task_id`: (留空)
    *   `file_id`: (留空)

---

## 2. 接口测试流程

测试将按照业务逻辑顺序进行：**上传 -> 查看结构 -> 生成测试 -> 执行测试 -> 查看结果**。

### 步骤 1：上传项目 (Upload Project)

**接口**：`POST /api/project/upload`

1.  **修改文档**：
    *   进入该接口的“修改文档”页面。
    *   在 **Body** 参数中，找到 `file` 参数，类型选择 `file`。
2.  **运行接口**：
    *   点击 **“运行”**。
    *   在 **Body** 的 `file` 字段中，点击上传按钮，选择准备好的 `demo.c` 文件。
    *   点击 **“发送”**。
3.  **提取变量（后置操作）**：
    *   在“后置操作”中添加一个 **“提取变量”** 步骤。
    *   变量名：`project_id`
    *   来源：`响应 JSON`
    *   JSON 路径：`$.project_id`
    *   *说明：这样操作后，后续接口可以直接使用 `{{project_id}}`。*

**预期结果**：状态码 `200`，返回包含 `project_id` 的 JSON。

---

### 步骤 2：获取项目结构 (Get Structure)

**接口**：`GET /api/project/{project_id}/structure`

1.  **运行接口**：
    *   路径参数 `project_id` 应自动填充为上一步提取的变量 `{{project_id}}`。
    *   点击 **“发送”**。
2.  **提取变量（人工或后置）**：
    *   观察响应 JSON，找到 `files` 列表。
    *   找到 `demo.c` 下的 `functions` 列表。
    *   复制其中一个函数的 `function_id`（例如 `demo.c_1`）。
    *   *可选：设置后置操作提取 `function_id` = `$.files[0].functions[0].function_id`*。

**预期结果**：返回项目的文件树和函数列表。

---

### 步骤 3：获取函数详情 (Get Function Detail)

**接口**：`GET /api/project/{project_id}/function/{function_id}`

1.  **运行接口**：
    *   `project_id`: `{{project_id}}`
    *   `function_id`: 手动填入上一步获取的 ID，或使用变量 `{{function_id}}`。
    *   点击 **“发送”**。

**预期结果**：返回函数的源代码和代码图谱（Code Graph）。

---

### 步骤 4：生成测试用例 (Generate Testcase)

**接口**：`POST /api/testcase/generate`

1.  **Body 参数**：
    ```json
    {
      "project_id": "{{project_id}}",
      "function_id": "{{function_id}}",
      "test_framework": "unity"
    }
    ```
2.  **运行接口**：
    *   点击 **“发送”**。
3.  **提取变量（后置操作）**：
    *   添加 **“提取变量”**。
    *   变量名：`task_id`
    *   来源：`响应 JSON`
    *   JSON 路径：`$.task_id`

**预期结果**：返回 `task_id` 和生成的测试代码预览。

---

### 步骤 5：执行测试用例 (Execute Testcase)

**接口**：`POST /api/testcase/execute`

1.  **Body 参数**：
    ```json
    {
      "task_id": "{{task_id}}"
    }
    ```
2.  **运行接口**：
    *   点击 **“发送”**。

**预期结果**：返回 `compile_success: true` 和 `execution_started: true`。

---

### 步骤 6：获取测试结果 (Get Test Result)

**接口**：`GET /api/testcase/{task_id}/result`

1.  **运行接口**：
    *   `task_id`: `{{task_id}}`
    *   点击 **“发送”**。

**预期结果**：
*   `test_result`: 显示通过（passed）和失败（failed）的数量。
*   `stdout`: 显示具体的测试输出日志。

---

## 3. 自动化测试（可选）

在 Apifox 左侧菜单的 **“自动化测试”** 中：

1.  新建一个测试用例。
2.  从接口列表中，依次将上述 **步骤 1 到 步骤 6** 的接口拖入测试流程中。
3.  确保每个接口的参数使用了 **环境变量**（如 `{{project_id}}`）。
4.  在关键步骤（如上传、生成）配置 **“后置操作” -> “提取变量”**，确保数据在步骤间自动流转。
5.  点击 **“运行”**，即可一键完成所有接口的集成测试。
