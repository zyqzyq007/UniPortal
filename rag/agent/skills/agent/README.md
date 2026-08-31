# Agent Skill

决定是否调用检索工具或直接回复。

## 输入
- 用户消息列表
- 绑定的检索工具

## 输出
- AIMessage：包含 tool_calls（触发检索）或直接回复内容

## 配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_retries | 2 | 最大重试次数 |
| retry_delay | 1.0 | 重试间隔(秒) |
| message_window | 10 | 发送给 LLM 的最近消息数 |
