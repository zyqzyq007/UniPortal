# Generate Skill

基于检索文档生成最终答案，支持 Qwen3 reasoning 捕获。

## 输入
- 用户问题（从 HumanMessage 提取）
- 检索文档上下文（从 ToolMessage 提取）

## 输出
- AIMessage：包含答案和可选的 reasoning

## 配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_retries | 2 | 最大重试次数 |
| retry_delay | 1.0 | 重试间隔(秒) |
| max_context_length | 2500 | 最大上下文长度 |
