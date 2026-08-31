# Rewrite Skill

改写用户查询以获得更好的检索结果。

## 输入
- 原始用户问题（从 HumanMessage 提取）

## 输出
- HumanMessage：改写后的查询
- state_updates: rewrite_count +1

## 配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_retries | 2 | 最大重试次数 |
| retry_delay | 1.0 | 重试间隔(秒) |
| preserve_original_on_failure | true | 失败时保留原始问题 |
