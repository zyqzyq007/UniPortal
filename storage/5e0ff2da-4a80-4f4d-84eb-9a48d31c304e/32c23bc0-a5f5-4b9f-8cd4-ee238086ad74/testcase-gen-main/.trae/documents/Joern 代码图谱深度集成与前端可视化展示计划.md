## 后端任务：集成 Joern 深度分析
1. **修改 Joern 服务路径**：
   - 更新 [joern_service.py](file:///root/test_case_generation/app/services/joern_service.py) 中的 `JOERN_PARSE` 为 `/opt/joern/joern-cli/joern-parse`。
   - 更新 `JOERN_QUERY` 为 `/opt/joern/joern-cli/joern`。
2. **优化查询脚本**：
   - 在 `get_function_cpg_depth` 中改进 Scala 脚本，确保其能准确提取 3 层深度的调用信息（包含文件名和行号）。
3. **完善数据结构**：
   - 确保 [parser_service.py](file:///root/test_case_generation/app/services/parser_service.py) 返回的 `code_graph` 包含 `rich_calls` 等详细信息。

## 前端任务：可视化代码图谱
1. **升级逻辑图谱组件**：
   - 修改 [GenerateView.vue](file:///root/test_case_generation/Frontend/src/views/GenerateView.vue)，将原本的字符串显示改为结构化的 UI。
   - 使用列表和标签展示变量、函数调用（带位置信息）和返回值。
2. **提升交互体验**：
   - 增加 Joern 分析时的加载状态。
   - 处理 Joern 数据与正则降级数据的兼容显示。

## 验证与测试
1. **端到端测试**：上传测试项目，触发 Joern 分析，验证后端 CPG 生成及前端图谱渲染。
2. **异常处理**：确保即使 Joern 环境出现问题，系统也能平滑切换到基础正则分析模式。