# Grade Skill

评估检索文档与用户问题的相关性。

## 输入
- 用户问题（从 HumanMessage 提取）
- 检索到的文档（从 ToolMessage 提取）

## 输出
- next_action: "generate"（相关）或 "rewrite"（不相关）

## 配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_retries | 2 | 最大重试次数 |
| retry_delay | 1.0 | 重试间隔(秒) |
