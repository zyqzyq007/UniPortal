## 目标：在获取函数详情接口中集成 Joern CPG 分析
为了响应用户关于“使用 Joern 构建层级为 3 的 CPG（代码属性图）图谱”的需求，我将按照以下步骤进行实现：

### 1. 核心逻辑实现
- **Joern 集成服务**：在 `app/services` 中引入对 Joern 命令行工具的调用逻辑。
- **CPG 生成与缓存**：
    - 实现 `joern-parse` 调用，对指定 `project_id` 的工作目录进行扫描，生成 `cpg.bin` 文件。
    - 增加缓存机制：如果 `cpg.bin` 已存在且项目文件未变更，则跳过解析。
- **层级 3 查询逻辑**：
    - 编写 Joern 查询脚本（Scala/ShiftLeft 查询语言），定位到特定函数名。
    - 使用 `callOut.depth(3)` 或 `reachableBy(depth=3)` 提取该函数向外延伸 3 层的调用关系或数据流向。
    - 将查询结果导出为 JSON 格式。

### 2. 接口适配与扩展
- **修改 `get_function_detail` 接口**：
    - 在 [project.py](file:///root/test_case_generation/app/routers/project.py) 中，将原有的基于正则的 `generate_code_graph` 替换为（或可选切换为）Joern 分析方法。
    - 接口将返回更丰富的 `code_graph`，包含 Joern 提取的深度调用关系。
- **扩展数据模型**：
    - 更新 `code_graph` 的返回结构，以支持层级化的调用关系展示（不仅仅是扁平的列表）。

### 3. 环境与验证
- **环境检查**：在执行前会确认系统环境中 Joern 的可用性。
- **自动化测试**：编写测试用例验证针对 `klib` 或 `sample.c` 项目，Joern 是否能正确生成包含 3 层深度的调用图谱。

## 关键技术点
- **Joern 查询示例**：`cpg.method.name("target_func").callOut.depth(3).name.l` 用于获取 3 层深度的调用函数名。
- **性能优化**：由于 Joern 解析较大项目较慢，将引入异步处理或预解析机制。

您是否同意按照此方案进行集成？
