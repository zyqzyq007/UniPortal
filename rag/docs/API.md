# RAG 智能问答平台 — 接口文档

> Base URL: `http://{host}:8000`
>
> 本文档供外部系统集成使用，涵盖所有 HTTP 接口、请求/响应格式及 SSE 流式协议。
> 当前进程内 MCP 工具不是 HTTP 接口，其独立契约见 [MCP.md](MCP.md)。
> Windows 11 + WSL2 的逐步部署、localhost URL、全部 endpoint 清单与可复制调用示例见
> [WSL Complete Guide](deployment/WSL_DEPLOYMENT.md)。

---

## 目录

- [1. 通用约定](#1-通用约定)
- [2. 智能问答](#2-智能问答)
  - [2.1 发送消息（非流式）](#21-发送消息非流式)
  - [2.2 发送消息（SSE 流式）](#22-发送消息sse-流式)
  - [2.3 获取对话历史](#23-获取对话历史)
  - [2.4 清除会话](#24-清除会话)
  - [2.5 查询 Prompt 状态](#25-查询-prompt-状态)
- [3. 文档管理](#3-文档管理)
  - [3.1 上传文档](#31-上传文档)
  - [3.2 文档列表](#32-文档列表)
  - [3.3 文档详情](#33-文档详情)
  - [3.4 删除文档](#34-删除文档)
  - [3.5 重建索引](#35-重建索引)
- [4. 会话管理](#4-会话管理)
  - [4.1 创建会话](#41-创建会话)
  - [4.2 会话列表](#42-会话列表)
  - [4.3 会话详情](#43-会话详情)
  - [4.4 删除会话](#44-删除会话)
  - [4.5 延长会话有效期](#45-延长会话有效期)
- [5. 知识库检索](#5-知识库检索)
  - [5.1 混合检索](#51-混合检索)
  - [5.2 纯向量检索](#52-纯向量检索)
  - [5.3 纯关键词检索（BM25）](#53-纯关键词检索bm25)
- [6. 用户反馈](#6-用户反馈)
  - [6.1 提交反馈](#61-提交反馈)
  - [6.2 获取会话反馈](#62-获取会话反馈)
  - [6.3 反馈统计](#63-反馈统计)
  - [6.4 待处理升级列表](#64-待处理升级列表)
  - [6.5 解决升级](#65-解决升级)
- [7. 系统监控](#7-系统监控)
  - [7.1 基础健康检查](#71-基础健康检查)
  - [7.2 详细健康检查](#72-详细健康检查)
  - [7.3 系统指标](#73-系统指标)
  - [7.4 熔断器状态](#74-熔断器状态)
  - [7.5 重置熔断器](#75-重置熔断器)
  - [7.6 降级状态](#76-降级状态)
  - [7.7 设置降级模式](#77-设置降级模式)
  - [7.8 系统配置](#78-系统配置)

---

## 1. 通用约定

### 响应头

| Header | 说明 |
|--------|------|
| `X-Trace-ID` | 请求追踪 ID，全链路唯一 |
| `X-Response-Time-Ms` | 服务端处理耗时（毫秒） |

### 错误响应格式

所有接口在出错时返回统一格式：

```json
{
  "detail": "错误描述信息"
}
```

HTTP 状态码：`4xx` 客户端错误，`5xx` 服务端错误。

---

## 2. 智能问答

### 2.1 发送消息（非流式）

```
POST /api/chat
```

发送用户消息，同步返回完整回答。

#### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `message` | string | 是 | — | 用户消息，最少 1 字符 |
| `session_id` | string | 否 | `null` | 会话 ID，用于多轮对话。不传则新建会话 |
| `stream` | boolean | 否 | `false` | 是否启用流式输出（本接口始终为 false） |
| `include_sources` | boolean | 否 | `true` | 是否在响应中包含来源文档 |
| `mode` | string | 否 | `"thinking"` | 回答模式：`"thinking"` 或 `"fast"` |

**`mode` 说明：**

| 值 | 说明 | LLM 调用次数 | 适用场景 |
|----|------|--------------|----------|
| `thinking` | 深度思考模式，经过意图分析 → Agent → 共享检索工作流 → 文档评估 → 生成 | 4+ | 需要深度分析、改写和评估的场景 |
| `fast` | 跳过 Agent/Grade/Rewrite，但复用共享检索工作流后生成 | 1 | 需要快速响应的场景 |

共享检索工作流会进行问题类型规划、查询表示复用、混合召回、authority/证据选择和最多一次
改变检索策略的纠正重试。只有 `accept` 状态进入 LLM 生成；`weak`、`conflict`、`empty`
会直接返回安全的信息缺口、版本冲突或无证据提示。设置
`RETRIEVAL_WORKFLOW_ENABLED=false` 可回滚旧检索路径。

#### 响应体

```json
{
  "response": "git 合并冲突的解决要点...",
  "session_id": "session_abc123",
  "intent": "rag_query",
  "sources": [
    {
      "content": "相关文档片段...",
      "source": "git_guide.md",
      "title": "合并冲突排查",
      "score": 0.87
    }
  ],
  "processing_time_ms": 3520.5,
  "metadata": {
    "intent_confidence": 0.95,
    "intent_reasoning": "知识库检索类问题",
    "source_count": 3,
    "structured_answer": {
      "summary": "git 合并冲突需手动编辑...",
      "details": ["同一文件多分支改动", "冲突标记未清理"],
      "steps": ["打开带冲突标记的文件", "编辑后提交"],
      "notes": "解决后应运行测试确认无回归...",
      "sources": ["来源: git_guide.md"],
      "gaps": "缺少历史合并记录"
    },
    "section_labels": ["摘要", "要点", "步骤", "备注", "来源", "信息缺口"],
    "route": "rag",
    "prompt_profile": "general_v1",
    "force_rag": false,
    "reasoning": "...",
    "confidence": 0.86,
    "confidence_level": "high",
    "refused": false,
    "message_id": "msg_abc123",
    "trace_id": "trace_abc123"
  }
}
```

#### 响应字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `response` | string | AI 回答内容 |
| `session_id` | string | 会话 ID（首次请求会自动生成） |
| `intent` | string | 检测到的意图：`rag_query` / `general_chat` / `degraded` |
| `sources` | SourceDocument[] | 参考来源文档列表 |
| `processing_time_ms` | float | 总处理耗时（毫秒） |
| `metadata.route` | string | 路由类型：`rag` / `general_chat` / `fast` |
| `metadata.prompt_profile` | string | Prompt 配置标识 |
| `metadata.structured_answer` | StructuredAnswer \| null | 结构化回答数据（仅当 active profile 定义了 `section_template` 时返回；字段为通用位置槽位，展示标签见 `section_labels`） |
| `metadata.section_labels` | string[] | active profile 的 section_template 标签，按位置对应 `structured_answer` 字段（用于 UI 渲染领域相关标题） |
| `metadata.reasoning` | string | Thinking 模式捕获的 Qwen3 reasoning；其它路径通常为空字符串 |
| `metadata.confidence` | float \| null | 可用时的复合置信度；不可用保持 `null`，不会伪造为 0 |
| `metadata.confidence_level` | string | `high` / `medium` / `low` / `unknown` |
| `metadata.refused` | boolean | 是否因证据不足、冲突或安全边界拒绝正常生成 |
| `metadata.message_id` | string | 消息标识，用于反馈关联 |
| `metadata.trace_id` | string | 推理 trace 标识，用于评测飞轮和排障 |
| `metadata.retrieval_time_ms` | float | 仅 Fast 路径附带的检索耗时 |
| `metadata.generation_time_ms` | float | 仅 Fast 路径附带的生成耗时；安全终止时为 0 |

正常 `rag` / `general_chat` / `fast` 路径返回上述统一字段集合；极端异常进入 `degraded`
路径时，`metadata` 只保证 `route`，并尽量提供 `error`、`message_id`、`trace_id`。

**`metadata.route` 取值说明：**

| 值 | 说明 |
|----|------|
| `rag` | 深度思考模式，经过完整 RAG 流程 |
| `general_chat` | 通用闲聊，直接 LLM 回答 |
| `fast` | 共享检索工作流 + 单次生成；跳过 Agent/Grade/Rewrite |
| `degraded` | 降级模式，服务异常时的兜底回答 |

---

### 2.2 发送消息（SSE 流式）

```
POST /api/chat/stream
```

发送用户消息，通过 Server-Sent Events (SSE) 流式返回回答。请求体与非流式接口完全相同。

#### 请求体

与 [2.1 发送消息（非流式）](#21-发送消息非流式) 相同。

#### 响应

`Content-Type: text/event-stream`

每个事件格式为：

```
data: {JSON}\n\n
```

#### SSE 事件类型

##### session — 会话信息（首个事件）

```json
{
  "type": "session",
  "session_id": "session_abc123"
}
```

##### intent — 意图分类结果

```json
{
  "type": "intent",
  "intent": "rag_query",
  "confidence": 0.95,
  "route": "rag",
  "force_rag": false
}
```

快速模式下：`"intent": "rag_query", "confidence": 1.0, "route": "fast"`

##### status — 处理状态提示

```json
{
  "type": "status",
  "message": "正在检索知识库..."
}
```

| message 取值 | 说明 |
|-------------|------|
| `正在返回平台能力说明...` | 识别为能力咨询/身份类问题，直接返回平台说明 |
| `正在分析意图...` | 意图分类中（仅 thinking 模式） |
| `正在检索知识库...` | 向量检索中 |
| `正在评估文档相关性...` | 文档评估中（仅 thinking 模式） |
| `正在优化查询...` | 查询改写中（仅 thinking 模式） |
| `正在生成回答...` | LLM 生成中 |
| `检测为领域技术问题，已切换知识库检索模式...` | 意图覆盖提示 |

##### node — 当前执行节点

```json
{
  "type": "node",
  "name": "agent"
}
```

| name 取值 | 说明 |
|-----------|------|
| `agent` | Agent 节点（仅 thinking 模式） |
| `retrieve` | 检索节点 |
| `grade` | 文档评估节点（仅 thinking 模式） |
| `rewrite` | 查询改写节点（仅 thinking 模式） |
| `generate` | 生成节点（仅 thinking 模式） |
| `fast_generate` | 快速生成节点（仅 fast 模式） |

##### token — 流式内容片段

```json
{
  "type": "token",
  "content": "根据"
}
```

`content` 为增量文本片段，前端应追加显示。每个 token 事件只包含一小段文字。

##### done — 完成信号

```json
{
  "type": "done",
  "full_response": "完整回答内容...",
  "sources": [
    {
      "content": "文档片段...",
      "source": "guide.md",
      "title": "技术文档",
      "score": 0.85
    }
  ],
  "processing_time_ms": 3520.5,
  "metadata": {
    "intent_confidence": 0.95,
    "intent_reasoning": "...",
    "source_count": 3,
    "structured_answer": null,
    "section_labels": [],
    "route": "rag",
    "prompt_profile": "general_v1",
    "force_rag": false
  }
}
```

> 收到 `done` 事件后流结束。`full_response` 为完整回答，可用其替换之前累积的 token。

##### error — 错误

```json
{
  "type": "error",
  "message": "错误描述"
}
```

#### SSE 集成示例

**Python (httpx)：**

```python
import httpx
import json

def chat_stream(message: str, session_id: str = None, mode: str = "thinking"):
    url = "http://localhost:8000/api/chat/stream"
    payload = {"message": message, "mode": mode}
    if session_id:
        payload["session_id"] = session_id

    with httpx.stream("POST", url, json=payload, timeout=120) as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["type"] == "token":
                    print(event["content"], end="", flush=True)
                elif event["type"] == "done":
                    return event

result = chat_stream("git 合并冲突如何解决？")
```

**JavaScript (fetch)：**

```javascript
async function chatStream(message, sessionId = null, mode = 'thinking') {
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      stream: true,
      mode,
    }),
  });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6));
        if (event.type === 'token') {
          // 追加显示 event.content
        } else if (event.type === 'done') {
          // 完成，event.full_response 为完整回答
        }
      }
    }
  }
}
```

---

### 2.3 获取对话历史

```
GET /api/chat/history/{session_id}
```

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 会话 ID |

#### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | integer | 20 | 返回消息数量上限 |

#### 响应体

```json
{
  "session_id": "session_abc123",
  "messages": [
    { "role": "user", "content": "git 合并冲突如何解决？" },
    { "role": "assistant", "content": "根据知识库检索结果..." }
  ],
  "total_messages": 4
}
```

---

### 2.4 清除会话

```
DELETE /api/chat/session/{session_id}
```

#### 响应体

```json
{
  "status": "success",
  "message": "Session session_abc123 cleared"
}
```

---

### 2.5 查询 Prompt 状态

```
GET /api/chat/prompt-status
```

用于集成方验证当前加载的 Prompt 配置版本。`prompt_profile` 与 preview 内容随 active
profile 变化（默认 `general`；以下示例为 `DOMAIN_PROFILE=aviation_phm` 下的取值）。

#### 响应体

```json
{
  "loaded": true,
  "prompt_profile": "general_v1",
  "generate_prompt_signature": "0df94211b3ee",
  "generate_prompt_preview": "你是知识库问答助手..."
}
```

---

## 3. 文档管理

### 3.1 上传文档

```
POST /api/documents/upload
```

上传文档到知识库，后台自动进行分块、向量化并存入 Milvus。

#### 请求

`Content-Type: multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 文档文件，支持 `.md`、`.txt`、`.pdf`、`.docx`、`.pptx`、`.html`、`.htm` |

默认最大上传大小为 50 MB，可通过 `MAX_UPLOAD_BYTES` 调整。DOCX/PPTX/HTML 解析需要安装
`doc` extra 中的相应本地依赖。

PDF 上传支持带图片、表格、图表或扫描页的混合 PDF。系统会索引可抽取的文字层，
将明确保留列分隔的表格转换为 Markdown 表格 chunk，并在 metadata 中记录页码、
`content_type`、图片对象数量和表格 ID。若页面没有文字层，只有在
`PDF_OCR_ENABLED=true` 且本地 OCR 引擎可用时才会渲染页面图片并写入
`content_type=ocr_text` 的 OCR chunk；否则该图片页会被跳过，整份 PDF 都无
可索引文本时后台状态为 `failed`。

当前本地 OCR 引擎为 PaddleOCR（`paddlepaddle` + `paddleocr`）。首次 OCR 会
下载官方模型到 `~/.paddlex/official_models/`；CPU 环境默认禁用 PaddleX
MKLDNN 路径以提升兼容性。执行 `deploy.sh --with-ocr --build-offline-bundle` 时，已经预热的
模型缓存会被复制到离线部署包中的 `paddleocr/official_models/`；请求 OCR bundle 但缓存缺失
会 fail closed。

可选摄入通道均默认关闭：

- `CONTEXTUAL_INDEX_ENABLED=true`：为新 collection 写入 bounded `index_text`，同时保留原始
  `display_text`；禁止在现有 collection 上原地开启。
- `RAPTOR_ENABLED=true`：后台构建并原子发布 source generation；失败不影响 Milvus/BM25 主索引。
- `COLPALI_ENABLED=true`：为 PDF 每页维护 hash-addressed 视觉索引；本地模型缺失、OOM 或页面
  处理失败时回退 OCR/文本，运行时不会下载模型。

#### 响应体

```json
{
  "id": "988f849c",
  "filename": "engine_manual.md",
  "status": "processing",
  "message": "Document uploaded and processing started"
}
```

上传接口同步返回的 `status` 恒为 `processing`（后台异步处理）。`indexed` / `failed` 为后台处理完成后，经 [3.3 文档详情](#33-文档详情) 查询可见的终态。文档状态完整说明见 [3. 文档管理](#3-文档管理) 开篇。

> 若文件名或内容（SHA256）已存在，上传被拒绝并返回 **HTTP 409**，响应体为 `{"detail": "..."}`（不返回 `UploadResponse`）。

---

### 3.2 文档列表

```
GET /api/documents
```

#### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `skip` | integer | 0 | 跳过条数 |
| `limit` | integer | 20 | 返回条数 |

#### 响应体

```json
{
  "documents": [
    {
      "id": "988f849c",
      "filename": "engine_manual.md",
      "status": "indexed",
      "chunks": 12,
      "created_at": 1713696000.0,
      "size_bytes": 15360,
      "file_hash": "6a06a695c5d26b41..."
    }
  ],
  "total": 5
}
```

---

### 3.3 文档详情

```
GET /api/documents/{doc_id}
```

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `doc_id` | string | 文档 ID |

#### 响应体

与 [3.2 文档列表](#32-文档列表) 中单个文档对象格式相同。

---

### 3.4 删除文档

```
DELETE /api/documents/{doc_id}
```

从文档注册表、Milvus 向量库和 BM25 索引中同步删除。

#### 响应体

```json
{
  "status": "success",
  "message": "Document 988f849c deleted"
}
```

---

### 3.5 重建索引

```
POST /api/documents/reindex
```

重新扫描 `md/` 目录下所有 Markdown 文件并重建向量索引。后台异步执行。

#### 响应体

```json
{
  "status": "success",
  "message": "Reindexing started in background"
}
```

---

## 4. 会话管理

### 4.1 创建会话

```
POST /api/sessions
```

#### 响应体

```json
{
  "session_id": "session_abc123",
  "message": "Session created successfully"
}
```

---

### 4.2 会话列表

```
GET /api/sessions
```

#### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `skip` | integer | 0 | 跳过条数 |
| `limit` | integer | 20 | 返回条数 |

#### 响应体

```json
{
  "sessions": [
    {
      "session_id": "session_abc123",
      "message_count": 6,
      "title": "git 合并冲突排查",
      "created_at": 1713696000.0,
      "last_active": 1713699600.0
    }
  ],
  "total": 3
}
```

---

### 4.3 会话详情

```
GET /api/sessions/{session_id}
```

#### 响应体

与 [4.2 会话列表](#42-会话列表) 中单个会话对象格式相同。

---

### 4.4 删除会话

```
DELETE /api/sessions/{session_id}
```

#### 响应体

```json
{
  "status": "success",
  "message": "Session session_abc123 deleted"
}
```

---

### 4.5 延长会话有效期

```
POST /api/sessions/{session_id}/extend
```

#### 响应体

```json
{
  "status": "success",
  "message": "Session session_abc123 extended"
}
```

---

## 5. 知识库检索

> 所有检索端点**不调用 LLM**，仅做知识库匹配。延迟取决于语料、索引、设备和是否启用
> Cross-Encoder；公开 benchmark 只能作为参考，不构成固定 SLA。
>
> 这三个端点是显式低层检索 API，不返回 planner/corrective diagnostics，也不执行聊天入口的
> 完整 `RetrievalWorkflow`。Fast、Thinking 和 MCP `rag_retrieve` 才默认使用共享工作流。

### 三种检索策略对比

| 策略 | 端点 | 原理 | 适用场景 |
|------|------|------|----------|
| 混合检索 | `POST /api/retrieval` | dense + 当前 sparse backend（本地 BGE-M3 native sparse 或 BM25）+ RRF/可选重排 | 通用检索或 baseline 对照 |
| 纯向量检索 | `POST /api/retrieval/dense` | 仅 embedding 余弦相似度 | 意思相近但关键词不同的查询 |
| 纯关键词检索 | `POST /api/retrieval/sparse` | 仅 BM25 词频匹配 | 精确关键词（标识符、配置项、错误代码） |

---

### 5.1 混合检索

```
POST /api/retrieval
```

同时执行 dense 向量检索和当前 sparse backend。本地默认 BGE-M3 使用 Milvus native sparse；
API embedding、非 BGE-M3 或训练 sparse head 不可用时使用 BM25。结果经 Reciprocal Rank
Fusion (RRF) 融合，并在启用时经过 Cross-Encoder/MMR。该端点保持固定的低层检索契约。

#### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 是 | — | 检索查询文本 |
| `top_k` | integer | 否 | 5 | 返回结果数量（1~50） |

#### 响应体

```json
{
  "query": "git 合并冲突如何解决",
  "results": [
    {
      "content": "当 git 合并冲突出现时，应按以下步骤解决：1. 查看冲突文件...",
      "source": "git_guide.md",
      "title": "合并冲突排查",
      "score": 0.87,
      "retrieval_score": 0.032,
      "rerank_score": 0.87,
      "rerank_applied": true
    }
  ],
  "total": 3,
  "retrieval_time_ms": 245.8
}
```

#### cURL 示例

```bash
curl -X POST http://localhost:8000/api/retrieval \
  -H "Content-Type: application/json" \
  -d '{"query":"git 合并冲突如何解决","top_k":5}'
```

---

### 5.2 纯向量检索

```
POST /api/retrieval/dense
```

仅使用 embedding 向量相似度搜索（Milvus 配置的索引，默认 AUTOINDEX），不经过 BM25 和 RRF。

#### 请求体 / 响应体

与 [5.1 混合检索](#51-混合检索) 格式相同。

#### cURL 示例

```bash
curl -X POST http://localhost:8000/api/retrieval/dense \
  -H "Content-Type: application/json" \
  -d '{"query":"APU 启动故障","top_k":3}'
```

---

### 5.3 纯关键词检索（BM25）

```
POST /api/retrieval/sparse
```

仅使用 BM25 算法进行关键词匹配，基于词频和逆文档频率打分。支持中文分词（jieba）。

#### 请求体 / 响应体

与 [5.1 混合检索](#51-混合检索) 格式相同。

#### cURL 示例

```bash
# 标识符精确匹配
curl -X POST http://localhost:8000/api/retrieval/sparse \
  -H "Content-Type: application/json" \
  -d '{"query":"MERGE-CONFLICT-01 合并","top_k":5}'
```

---

## 6. 用户反馈

### 6.1 提交反馈

```
POST /api/feedback
```

用户对 AI 回答提交反馈（点赞/点踩/纠正/标记）。系统会自动触发升级判定，纠正类反馈还会提取知识存入记忆。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 是 | 关联的会话 ID |
| `message_id` | string | 否 | 被反馈的消息 ID |
| `feedback_type` | string | 是 | 反馈类型，见下表 |
| `content` | string | 否 | 反馈文字内容 |
| `original_answer` | string | 否 | 原始回答（纠正时使用） |
| `corrected_answer` | string | 否 | 纠正后的回答（纠正时使用） |

**`feedback_type` 取值：**

| 值 | 说明 |
|----|------|
| `THUMBS_UP` | 点赞 |
| `THUMBS_DOWN` | 点踩 |
| `CORRECTION` | 内容纠正（需同时提供 `original_answer` 和 `corrected_answer`） |
| `FLAG` | 标记问题 |

#### 响应体

```json
{
  "status": "ok",
  "id": "fb_abc123"
}
```

#### cURL 示例

```bash
# 点赞
curl -X POST http://localhost:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{"session_id":"session_abc","feedback_type":"THUMBS_UP"}'

# 内容纠正
curl -X POST http://localhost:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session_abc",
    "feedback_type": "CORRECTION",
    "original_answer": "git 默认分支名为 master",
    "corrected_answer": "git 默认分支名应为 main，参考官方文档"
  }'
```

---

### 6.2 获取会话反馈

```
GET /api/feedback/{session_id}
```

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 会话 ID |

#### 响应体

```json
{
  "session_id": "session_abc",
  "feedback": [
    {
      "id": "fb_001",
      "type": "thumbs_up",
      "content": "",
      "timestamp": 1713696000.0
    },
    {
      "id": "fb_002",
      "type": "correction",
      "content": "git 默认分支名应为 main",
      "timestamp": 1713696100.0
    }
  ]
}
```

---

### 6.3 反馈统计

```
GET /api/feedback/stats/summary
```

获取全平台反馈汇总统计。

#### 响应体

```json
{
  "total_feedback": 128,
  "by_type": {
    "thumbs_up": 85,
    "thumbs_down": 20,
    "correction": 15,
    "flag": 8
  },
  "escalation_count": 3
}
```

---

### 6.4 待处理升级列表

```
GET /api/feedback/escalations/pending
```

管理员接口。返回所有未解决的升级工单（由多次点踩或标记自动触发）。

#### 响应体

```json
{
  "pending": [
    {
      "id": "esc_001",
      "session_id": "session_abc",
      "level": "high",
      "reason": "连续 3 次负面反馈",
      "timestamp": 1713696000.0
    }
  ]
}
```

**`level` 取值：**

| 值 | 说明 |
|----|------|
| `low` | 低优先级（单次标记） |
| `medium` | 中优先级（2 次负面反馈） |
| `high` | 高优先级（3 次及以上负面反馈） |
| `critical` | 严重（涉及安全风险标记） |

---

### 6.5 解决升级

```
POST /api/feedback/escalations/{escalation_id}/resolve
```

管理员接口。标记升级工单为已解决。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `escalation_id` | string | 升级工单 ID |

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `resolution` | string | 是 | 解决说明 |

#### 响应体

```json
{
  "status": "resolved",
  "id": "esc_001"
}
```

---

## 7. 系统监控

### 7.0 进程存活检查

```
GET /live
```

返回 `{"status":"alive","timestamp":...}`。该端点只证明 ASGI 进程能响应，供容器或
systemd liveness 使用；它不探测向量库、模型或外部服务。流量就绪与安全降级必须读取
`GET /health`。

### 7.1 基础健康检查

```
GET /health
```

#### 响应体

```json
{
  "status": "healthy",
  "timestamp": 1713696000.0,
  "circuits": {
    "llm": "closed",
    "retriever": "closed"
  },
  "embedding_compatible": true,
  "runtime_config": { "...": "不含 secret 的配置指纹" }
}
```

`status=degraded` 仍是有效响应，表示系统保留较弱但安全的路径；不得把 unavailable 当作 0 分，
也不应把 degraded 用作 liveness 失败条件。

---

### 7.2 详细健康检查

```
GET /api/admin/health
```

包含各子服务的详细状态。

#### 响应体

```json
{
  "status": "healthy",
  "services": {
    "llm": {
      "status": "healthy",
      "circuit": "closed",
      "stats": {
        "success_count": 42,
        "failure_count": 0,
        "failure_rate": 0.0,
        "last_failure_time": 0.0
      }
    },
    "retriever": {
      "status": "healthy",
      "circuit": "closed",
      "stats": { "..." : "..." }
    },
    "milvus": {
      "status": "healthy",
      "details": { "..." : "..." }
    }
  }
}
```

---

### 7.3 系统指标

```
GET /api/admin/metrics
```

#### 响应体

```json
{
  "timestamp": 1713696000.0,
  "memory": {
    "rss_mb": 256.5,
    "vms_mb": 512.0
  },
  "gc": {
    "gen_0": { "collections": 120, "collected": 850, "uncollectable": 0 }
  },
  "python": { "version": "3.13.0" }
}
```

---

### 7.4 熔断器状态

```
GET /api/admin/circuit-breakers
```

#### 响应体

```json
{
  "llm": {
    "success_count": 42,
    "failure_count": 0,
    "failure_rate": 0.0,
    "last_failure_time": 0.0
  },
  "retriever": { "..." : "..." }
}
```

---

### 7.5 重置熔断器

```
POST /api/admin/circuit-breakers/{name}/reset
```

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | string | 熔断器名称：`llm` 或 `retriever` |

> 非法取值将返回 HTTP 422。

#### 响应体

```json
{
  "status": "success",
  "message": "LLM circuit breaker reset"
}
```

---

### 7.6 降级状态

```
GET /api/admin/degradation
```

#### 响应体

```json
{
  "mode": "normal",
  "fallback_mode": "static_response",
  "metrics": { "..." : "..." }
}
```

---

### 7.7 设置降级模式

```
POST /api/admin/degradation/mode/{mode}
```

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `mode` | string | 降级模式：`full` / `cached` / `simplified` / `offline` |

**`mode` 取值说明：**

| 值 | 说明 |
|----|------|
| `full` | 正常运行，使用完整 RAG 流程 |
| `cached` | 仅返回缓存响应 |
| `simplified` | 简化回答模式 |
| `offline` | 最小离线兜底模式 |

> 非法取值将返回 HTTP 422。

#### 响应体

```json
{
  "status": "success",
  "mode": "full"
}
```

---

### 7.8 系统配置

```
GET /api/admin/config
```

#### 响应体

```json
{
  "runtime_config": {
    "schema_version": 1,
    "fingerprint": "a1b2c3d4e5f6"
  },
  "llm": {
    "model": "qwen3:14b",
    "temperature": 0.0,
    "max_tokens": 4096,
    "timeout": 60.0,
    "max_retries": 1
  },
  "embedding": {
    "model": "BAAI/bge-m3",
    "model_source": "/path/to/models/local_models/bge-m3",
    "provider": "local",
    "local_path": "/path/to/models/local_models/bge-m3",
    "dimension": 1024,
    "device": "cuda",
    "normalize": true,
    "batch_size": 8,
    "api_base_url": null
  },
  "reranker": {
    "enabled": true,
    "model": "BAAI/bge-reranker-v2-m3",
    "local_path": "/path/to/models/local_models/reranker/bge-reranker-v2-m3",
    "device": "cuda",
    "warmup": false,
    "candidate_top_k": 10,
    "top_k": 5,
    "batch_size": 4
  },
  "opentelemetry": {
    "enabled": false,
    "service_name": "rag-platform",
    "endpoint": "",
    "sample_rate": 1.0,
    "console_exporter": false
  },
  "milvus": {
    "uri": "./milvus_data.db",
    "collection": "rag_knowledge_base"
  },
  "pdf_ingestion": {
    "extract_tables": true,
    "ocr_enabled": false,
    "ocr_engine": "paddleocr",
    "ocr_lang": "ch",
    "ocr_dpi": 220,
    "ocr_min_text_chars": 20,
    "asset_dir": "/path/to/data/document_assets"
  },
  "session": {
    "ttl": 3600,
    "max_messages": 50
  }
}
```

---

## 附录 A：数据结构

### ChatRequest

```typescript
interface ChatRequest {
  message: string              // 必填，用户消息
  session_id?: string          // 可选，会话 ID
  stream?: boolean             // 默认 false
  include_sources?: boolean    // 默认 true
  mode?: "thinking" | "fast"   // 默认 "thinking"
}
```

### ChatResponse

```typescript
interface ChatResponse {
  response: string
  session_id: string
  intent: string               // "rag_query" | "general_chat" | "degraded"
  sources: SourceDocument[]
  processing_time_ms: number
  metadata: {
    intent_confidence?: number
    intent_reasoning?: string
    source_count?: number
    structured_answer?: StructuredAnswer | null
    section_labels?: string[]
    route: "rag" | "general_chat" | "fast" | "degraded"
    prompt_profile?: string
    force_rag?: boolean
    reasoning?: string
    confidence?: number | null
    confidence_level?: "high" | "medium" | "low" | "unknown"
    refused?: boolean
    message_id?: string
    trace_id?: string
    retrieval_time_ms?: number
    generation_time_ms?: number
  }
}
```

### SourceDocument

```typescript
interface SourceDocument {
  content: string
  source?: string
  title?: string
  score?: number
  retrieval_score?: number      // RRF 融合分数
  rerank_score?: number         // Cross-Encoder 重排分数
  rerank_applied?: boolean      // 本次是否成功应用重排
}
```

### StructuredAnswer

结构化回答。字段为通用位置槽位；active profile 的 `section_template` 标签按位置填入
（随响应附带的 `section_labels` 提供，如可选示例 aviation_phm 下为「诊断结论/可能原因/...」）。
profile 无 section 模板时（如默认 general），后端返回 `structured_answer: null`，回答为自由文本。

```typescript
interface StructuredAnswer {
  summary: string
  details: string[]
  steps: string[]
  notes: string
  sources: string[]
  gaps: string
}
```

### DocumentInfo

```typescript
interface DocumentInfo {
  id: string
  filename: string
  status: string               // "processing" | "indexed" | "failed"
  chunks: number
  created_at: number           // Unix 时间戳
  size_bytes: number
  file_hash: string
}
```

### SessionInfo

```typescript
interface SessionInfo {
  session_id: string
  message_count: number
  title: string                 // 会话标题（可能为空）
  created_at: number | null     // Unix 时间戳
  last_active: number | null    // Unix 时间戳
}
```

### FeedbackRequest

```typescript
interface FeedbackRequest {
  session_id: string                          // 必填，关联会话 ID
  message_id?: string                         // 可选，被反馈的消息 ID
  feedback_type: "THUMBS_UP" | "THUMBS_DOWN" | "CORRECTION" | "FLAG"  // 必填
  content?: string                            // 可选，反馈文字
  original_answer?: string                    // 可选，原始回答（纠正时）
  corrected_answer?: string                   // 可选，纠正后回答（纠正时）
}
```

### FeedbackEntry

```typescript
interface FeedbackEntry {
  id: string
  type: string                  // "thumbs_up" | "thumbs_down" | "correction" | "flag"
  content: string
  timestamp: number             // Unix 时间戳
}
```

### EscalationRecord

```typescript
interface EscalationRecord {
  id: string
  session_id: string
  level: "low" | "medium" | "high" | "critical"
  reason: string
  timestamp: number             // Unix 时间戳
}
```

### RetrievalRequest

```typescript
interface RetrievalRequest {
  query: string                 // 必填，检索查询文本
  top_k?: number                // 可选，返回结果数量，默认 5，范围 1~50
}
```

### RetrievedDocument

```typescript
interface RetrievedDocument {
  content: string               // 匹配的文档片段
  source: string                // 来源文件名
  title: string                 // 文档标题
  score: number                 // 最终相关性分数（越高越相关）
  retrieval_score?: number      // RRF 融合分数
  rerank_score?: number         // Cross-Encoder 重排分数
  rerank_applied?: boolean      // 本次是否成功应用重排
}
```

### RetrievalResponse

```typescript
interface RetrievalResponse {
  query: string                 // 原始查询
  results: RetrievedDocument[]  // 检索结果列表
  total: number                 // 结果总数
  retrieval_time_ms: number     // 检索耗时（毫秒）
}
```

---

## 附录 B：快速上手

### 1. 健康检查

```bash
curl http://localhost:8000/live
curl http://localhost:8000/health
```

### 2. 发送消息（非流式）

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"git 合并冲突如何解决？","mode":"thinking"}'
```

### 3. 发送消息（SSE 流式）

```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"git 合并冲突如何解决？","stream":true,"mode":"thinking"}'
```

### 4. 知识库检索（不调用 LLM）

```bash
# 混合检索（推荐）
curl -X POST http://localhost:8000/api/retrieval \
  -H "Content-Type: application/json" \
  -d '{"query":"git 合并冲突","top_k":5}'

# 纯向量检索
curl -X POST http://localhost:8000/api/retrieval/dense \
  -H "Content-Type: application/json" \
  -d '{"query":"git 合并冲突","top_k":5}'

# 纯 BM25 关键词检索
curl -X POST http://localhost:8000/api/retrieval/sparse \
  -H "Content-Type: application/json" \
  -d '{"query":"MERGE-CONFLICT-01 合并","top_k":5}'
```

### 5. 上传文档到知识库

```bash
curl -X POST http://localhost:8000/api/documents/upload \
  -F "file=@engine_manual.md"
```

### 6. 多轮对话（使用 session_id）

```bash
# 第一轮 — 自动创建会话
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"APU 无法启动的原因有哪些？"}'
# 返回中包含 session_id

# 第二轮 — 传入 session_id 继续对话
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"如何进一步排查？","session_id":"session_abc123"}'
```

### 7. 提交用户反馈

```bash
curl -X POST http://localhost:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{"session_id":"session_abc123","feedback_type":"THUMBS_UP"}'
```

---

## 附录 C：快速模式 vs 深度模式流程对比

```
深度思考模式 (mode="thinking"):
  用户消息 → 意图分类 → Agent决策 → RetrievalWorkflow → 文档评估 → 生成回答
                                      │
                                      └─ weak/conflict/empty → 安全终止，不调用生成 LLM
             约 4+ 次 LLM 调用；延迟取决于模型、硬件、改写轮数和上下文

快速模式 (mode="fast"):
  用户消息 → RetrievalWorkflow → accept → 生成回答(LLM)
                              └→ weak/conflict/empty → 安全终止
             最多 1 次生成 LLM 调用；安全终止为 0 次，延迟取决于部署硬件
```

---

## 附录 D：部署模式与配置

平台支持两种部署 profile，由 `EMBEDDING_PROVIDER` + 依赖 extra 切换，**同一份代码**。

| 维度 | 本地推理（默认） | API-only |
|------|------------------|----------|
| 依赖安装 | `uv sync --frozen --extra local-models`（按需加 `--extra ocr`） | `uv sync --frozen --extra api-only` |
| torch / 本地权重 | ✅ 含（embedding + reranker 本地推理） | ❌ 不含（镜像 ~0.43 GB，无 GPU 友好） |
| LLM | 本地 Ollama（`OPENAI_BASE_URL=http://localhost:11434/v1`） | DashScope Qwen 或任意 OpenAI 兼容端点 |
| Embedding | 本地 BGE-M3 1024 维（`EMBEDDING_PROVIDER=local`） | DashScope `text-embedding-v3`（`EMBEDDING_PROVIDER=api`） |
| Reranker | 本地 bge-reranker-v2-m3（`RERANKER_ENABLED=true`） | 关闭，回退 RRF 顺序（`RERANKER_ENABLED=false`） |
| 发布入口 | systemd + stripping/根路径 Nginx | `deploy/compose.api-only.yaml` + Nginx |

### 关键环境变量

| 变量 | 本地推理 | API-only | 说明 |
|------|----------|----------|------|
| `DEPLOYMENT_ENV` | `production` | `production` | 生产必须显式声明，错误配置启动失败 |
| `LOCAL_ONLY_DEPLOYMENT` | WSL localhost 时 `true`，常规裸机 `false` | `false` | `true` 只允许全部 loopback origin，并启用 Trusted Host；不得用于 LAN/public |
| `ALLOWED_ORIGINS` | WSL 为 literal loopback；常规裸机为真实 HTTPS origin | 真实 HTTPS origin | 禁止 `*`；常规生产拒绝纯 loopback，显式 local-only 则拒绝任何 non-loopback |
| `ADMIN_API_KEY` | **必填** | **必填** | 生产禁用 Admin loopback 兜底 |
| `EMBEDDING_PROVIDER` | `local`（或 `auto`） | `api` | `auto` = torch 可导入则 `local` 否则 `api` |
| `DASHSCOPE_API_KEY` | — | **必填**（运行时注入） | DashScope embedding 鉴权；空值会 fail-fast |
| `DASHSCOPE_BASE_URL` | — | `https://dashscope.aliyuncs.com` | 可覆盖为内网网关 |
| `OPENAI_BASE_URL` | `http://localhost:11434/v1` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | LLM 端点 |
| `EMBEDDING_DIMENSION` | 1024（BGE-M3） | 512（v3 合法集合之一） | 必须 = Milvus collection 维度 |
| `RETRIEVAL_WORKFLOW_ENABLED` | `true` | `true` | Fast/Thinking/MCP 的共享 plan、纠正与终态；`false` 回滚 legacy |
| `RETRIEVAL_CANDIDATE_FUNNEL_ENABLED` | `false` | `false` | 控制实验未通过稳定收益门禁 |
| `CONTEXTUAL_INDEX_ENABLED` | `false` | `false` | 只能在新 collection 上实验 |
| `COLBERT_RERANK_ENABLED` / `RAPTOR_ENABLED` / `GRAPH_PPR_ENABLED` / `COLPALI_ENABLED` | `false` | `false` | 真实模型/私域 promotion 前保持关闭 |

> **安全**：`DASHSCOPE_API_KEY` / `OPENAI_API_KEY` / `ADMIN_API_KEY` 均为运行时 secret，
> 容器通过 `deploy/secrets/` 的文件型 secret 挂载注入，**绝不写入 Compose 插值、Git、
> 镜像或离线包**。`/api/admin/config` 响应中
> `embedding.api_base_url` 仅在 `provider=api` 时返回端点，永不返回 key。
>
> **PII 合规**：API-only 模式下，文档原文会发送到 DashScope 做 embedding；对话层的输入
> 脱敏不覆盖摄入路径，数据驻留要求由部署方负责。详见
> `docs/specs/api-only-deploy/design.md` §9 与 `docs/deployment/api-only-docker.md`。

完整开发、裸机、容器、气隙和运维命令以 [Deployment Guide](deployment/README.md) 为准；
`docs/specs/*` 保留历史设计与决策，不作为操作手册。
