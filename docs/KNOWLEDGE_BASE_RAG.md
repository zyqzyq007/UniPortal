# UniPortal 知识库 RAG 能力说明

本文档描述 UniPortal 知识库与 RAG 检索能力的完整实现状态，包括已封装的 API 接口、底层模型配置、检索策略、索引构建规范，以及尚未接入的 RAG 高级能力。

---

## 一、系统架构

```
子工具 / 前端
     │
     ▼
UniPortal Express BFF (端口 8080)
     ├── JWT 鉴权
     ├── 项目级文档隔离
     ├── 检索后处理（阈值过滤、归一化、排序、top_k 截取）
     ├── 文件预览（text / html / pdf / image）
     └── 代理转发
           │
           ▼
     RAG FastAPI 服务 (端口 8000)
           ├── 文档解析 → 分块 → 向量化 → Milvus Lite 存储
           ├── 混合检索引擎 (Dense + Sparse + RRF + Reranker)
           └── LangGraph Agent 编排（Chat 能力，尚未封装）
```

### Embedding 模型

| 模式 | 模型 | 维度 | 说明 |
|---|---|---|---|
| 本地模式 (Mac MPS / GPU) | BAAI/bge-m3 | 1024 | sentence-transformers + FlagEmbedding，支持 dense + sparse + ColBERT 三合一输出 |
| API 模式 (DashScope) | text-embedding-v3 | 512 | 阿里云百炼 API，零 GPU 依赖 |

模型通过 `EMBEDDING_PROVIDER` 环境变量切换：
- `EMBEDDING_PROVIDER=local` → 使用本地 BGE-M3
- `EMBEDDING_PROVIDER=api` → 使用 DashScope text-embedding-v3

### Reranker 模型

| 模型 | 说明 |
|---|---|
| BAAI/bge-reranker-v2-m3 | Cross-encoder 重排序模型，多语言支持 |

通过 `RERANKER_ENABLED=true` 启用。启用后，检索结果经 cross-encoder 二次排序，置信度（rerank_score）为真实的语义相关度。

---

## 二、检索策略

UniPortal 封装了 RAG 的三种检索模式，均支持项目级文档隔离、置信度阈值过滤、结果排序和 top_k 截取。

### 2.1 混合检索（Hybrid）

**端点**: `POST /api/knowledge/{projectId}/retrieval`

融合 Dense（语义向量）和 Sparse（BM25 关键词）两路召回结果：

1. Dense 路径：BGE-M3 将 query 编码为 1024 维向量，在 Milvus 中做 ANN 近似最近邻搜索
2. Sparse 路径：BM25 算法基于词频-逆文档频率做关键词匹配
3. RRF（Reciprocal Rank Fusion）融合两路排序
4. Reranker（如启用）对融合后的候选做 cross-encoder 精排
5. 返回 `rerank_score` 作为最终相关度

适用场景：通用检索，兼顾语义理解和关键词精确匹配。

### 2.2 语义检索（Dense）

**端点**: `POST /api/knowledge/{projectId}/retrieval/dense`

仅使用 BGE-M3 向量相似度检索，不经过 BM25 和 reranker。速度最快，适合对语义相关性要求高、对关键词匹配无需求的场景。

### 2.3 关键词检索（Sparse / BM25）

**端点**: `POST /api/knowledge/{projectId}/retrieval/sparse`

仅使用 BM25 算法做关键词匹配。BM25 分数为无界正值（非 [0,1] 范围），UniPortal BFF 自动按最大值归一化到 [0, 1]，使置信度阈值可生效。

归一化公式：`normalized_score = raw_score / max_score_in_batch`

适用场景：精确术语匹配、代码标识符搜索、编号查询。

### 2.4 检索后处理流程

所有三种检索模式统一经过以下后处理（在 UniPortal Express BFF 层完成）：

```
RAG 原始结果
  → 项目文档过滤（按 filename 匹配，确保跨项目隔离）
  → 目标文档过滤（用户可选指定文档子集）
  → 置信度阈值过滤（默认 0.3，用户可配置 0-1）
  → 按分数降序排序
  → Top K 截取（默认 5，范围 1-50）
```

---

## 三、索引构建

### 3.1 支持的文件类型

| 扩展名 | 解析方式 | 说明 |
|---|---|---|
| `.txt` | 直接读取 | 纯文本 |
| `.md` / `.markdown` | 直接读取 | Markdown |
| `.pdf` | pypdfium2 + pypdf | 含文字层的 PDF |
| `.docx` | python-docx | Word 2007+ XML 格式 |
| `.pptx` | python-pptx | PowerPoint 2007+ |
| `.html` / `.htm` | BeautifulSoup4 | 网页文件 |

以下格式**不支持**：
- `.doc`（Word 97-2003 二进制格式，需 LibreOffice 转换）
- 扫描件 / 纯图片 PDF（无文字层，需 OCR，当前未启用）
- 图片格式（`.png` `.jpg` 等，不参与文本索引）

### 3.2 分块策略（Chunking）

RAG 采用三阶段自适应分块：

| 文档大小 | 策略 | 参数 |
|---|---|---|
| 小文档（< ~1200 tokens / ~3840 字符） | 保持原样，整体作为一个 chunk | — |
| 大文档 | SemanticChunker（基于 embedding 的语义断点检测） | 自动确定分块位置 |
| 大文档（SemanticChunker 不可用时） | RecursiveCharacterTextSplitter | chunk_size=900, chunk_overlap=120, 分隔符含中文 `。！` |

此外启用 **Late Chunking**（最小 256 tokens）：先对整篇文档编码获取全局上下文，再按分块边界截取，保留跨段落语义关联。

### 3.3 上传流程

```
用户上传文件
  → Express 接收（multer）
  → 中文文件名编码修复（UTF-8 → Latin-1 → UTF-8 恢复）
  → 转发到 RAG /api/documents/upload
  → RAG 异步处理：解析 → 分块 → BGE-M3 向量化 → 写入 Milvus Lite
  → Express 在本地存储文件副本（用于预览/下载）
  → Prisma 记录文档元数据（project_id, rag_document_id, filename）
  → 前端轮询文档状态（processing → indexed / failed）
```

---

## 四、已封装的 API 接口

以下接口均已实现并通过测试，供前端和子工具调用。所有接口需 JWT 鉴权。

### 4.1 文档管理

#### 上传文档

```
POST /api/knowledge/{projectId}/documents
Content-Type: multipart/form-data
Authorization: Bearer {token}

Body: file=<二进制文件>

Response 201:
{
  "code": 201,
  "data": {
    "id": "uuid",              // UniPortal 本地文档 ID
    "rag_document_id": "hex",  // RAG 服务返回的文档 ID
    "filename": "需求文档.pdf",
    "status": "processing",
    "file_size": 289079,
    "created_at": "2026-08-01T..."
  }
}
```

#### 列出项目文档

```
GET /api/knowledge/{projectId}/documents
Authorization: Bearer {token}

Response 200:
{
  "code": 200,
  "data": {
    "documents": [
      {
        "id": "uuid",
        "rag_document_id": "hex",
        "filename": "需求文档.pdf",
        "file_size": "289079",
        "uploaded_by": "uuid",
        "created_at": "...",
        "status": "indexed",          // indexed | processing | failed
        "status_label": "已索引",     // 人类可读的状态描述
        "chunk_count": 5              // 分块数量
      }
    ],
    "total": 3
  }
}
```

`status_label` 字段说明：

| status | status_label | 含义 |
|---|---|---|
| `indexed` | 已索引 | 分块+向量化完成，可检索 |
| `processing` | 处理中 | 正在解析/分块/向量化 |
| `failed` (全部失败) | 嵌入服务未配置(DASHSCOPE_API_KEY)，无法生成向量索引 | RAG 的 embedding 服务不可用 |
| `failed` (PDF) | PDF解析失败：该文件可能是扫描件或纯图片... | PDF 无文字层 |
| `failed` (其他) | 文档处理失败，请查看RAG服务日志排查具体原因 | 其他错误 |

#### 删除文档

```
DELETE /api/knowledge/{projectId}/documents/{documentId}
Authorization: Bearer {token}

Response 200: { "code": 200, "message": "Document deleted" }
```

同时删除 RAG 中的向量索引和 UniPortal 的本地文件副本及 Prisma 记录。

#### 预览文档

```
GET /api/knowledge/{projectId}/documents/{documentId}/preview
Authorization: Bearer {token}

Response 200 (文本类 .txt .md .json .py 等):
{
  "code": 200,
  "data": { "filename": "...", "type": "text", "content": "...", "size": 1234 }
}

Response 200 (.docx，保留格式):
{
  "code": 200,
  "data": { "filename": "...", "type": "html", "content": "<h1>...</h1><p>...</p>" }
}

Response 200 (.pdf):
{
  "code": 200,
  "data": { "filename": "...", "type": "pdf", "ext": "pdf",
            "download_url": "/api/knowledge/{pid}/documents/{did}/download" }
}

Response 200 (图片 .png .jpg 等):
{
  "code": 200,
  "data": { "filename": "...", "type": "image",
            "src": "data:image/png;base64,..." }
}
```

#### 下载文档

```
GET /api/knowledge/{projectId}/documents/{documentId}/download?mode={inline|attachment}
Authorization: Bearer {token}

mode=inline:    Content-Disposition: inline（浏览器内嵌显示）
mode=attachment: Content-Disposition: attachment（强制下载）
```

#### 重建索引

```
POST /api/knowledge/{projectId}/documents/{documentId}/reindex
Authorization: Bearer {token}

Response 200:
{
  "code": 200,
  "data": { "document_id": "...", "rag_document_id": "新ID", "status": "processing" }
}
```

实现方式：删除 RAG 旧文档 → 等待去重缓存清除 → 用本地文件副本重新上传 → 更新 Prisma 记录。

### 4.2 检索接口

#### 混合检索

```
POST /api/knowledge/{projectId}/retrieval
Content-Type: application/json
Authorization: Bearer {token}

Body:
{
  "query": "用户登录功能需求",    // 必填，检索查询文本
  "top_k": 5,                   // 可选，返回结果数，默认 5，范围 1-50
  "threshold": 0.3,             // 可选，置信度阈值，默认 0.3，范围 0-1
  "documents": ["文件A.txt"]     // 可选，限定检索的文档文件名列表，留空则搜索全部
}

Response 200:
{
  "code": 200,
  "data": {
    "query": "用户登录功能需求",
    "results": [
      {
        "content": "## 登录功能\n用户可通过用户名和密码登录系统...",
        "source": "需求文档.txt",
        "score": 0.016,           // 原始检索分数
        "retrieval_score": 0.016, // RAG 检索分数
        "rerank_score": 0.9999,   // Reranker 精排分数（如启用）
        "rerank_applied": true     // 是否经过了 reranker
      }
    ],
    "matched_count": 3,   // 过阈值的结果总数
    "returned_count": 3,  // 实际返回数（≤ top_k）
    "threshold": 0.3,
    "retrieval_time_ms": 581.2
  }
}
```

#### 语义检索（Dense-only）

```
POST /api/knowledge/{projectId}/retrieval/dense
Body: 同混合检索
```

不经过 BM25 和 RRF 融合，仅返回 Dense 向量相似度结果。

#### 关键词检索（BM25）

```
POST /api/knowledge/{projectId}/retrieval/sparse
Body: 同混合检索
```

BM25 原始分数经归一化处理（除以本批次最大分数），使 threshold 参数可生效。

### 4.3 检索参数校验规则

| 参数 | 校验 | 非法值处理 |
|---|---|---|
| `top_k` | 必须为 1-50 的正整数 | 非数字/0/负数/小数 → 重置为 5 |
| `threshold` | 必须为 0-1 的浮点数 | 非法值 → 重置为 0.3 |
| `query` | 必须为非空字符串 | 返回 400 |
| `documents` | 可选，字符串数组 | 非数组 → 忽略（搜索全部） |

### 4.4 鉴权方式

所有接口需要 JWT 鉴权，支持两种方式：

```http
# 方式一：Cookie（浏览器自动携带）
Cookie: token=eyJhbGciOiJIUzI1NiIs...

# 方式二：Authorization Header
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

子工具在 iframe 内调用时，使用 Authorization Header（`fetch` 请求手动添加）：

```javascript
const res = await fetch('/api/knowledge/{projectId}/retrieval', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  },
  body: JSON.stringify({ query: '登录功能', top_k: 5 }),
})
```

---

## 五、项目级模型配置

UniPortal 支持为每个项目独立配置 Embedding 和 Reranker 模型。

### 5.1 配置存储

```
PUT /api/projects/{projectId}/model-config
Authorization: Bearer {token}

Body:
{
  "embeddingModel": "DashScope/text-embedding-v3",  // 格式: {Provider名}/{模型ID}
  "rerankerModel": null                              // null 表示禁用 reranker
}
```

### 5.2 应用配置（重启 RAG + 重建索引）

```
POST /api/projects/{projectId}/model-config/apply
Authorization: Bearer {token}
```

执行流程：
1. 根据模型配置查找对应的 Provider（Base URL + API Key）
2. 生成 RAG 环境变量（`EMBEDDING_MODEL`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `RERANKER_MODEL`）
3. 写入共享卷的 `rag_override.env` 文件
4. 通过 Docker socket 重启 RAG 容器
5. 等待 RAG 健康（最多 60 秒轮询）
6. 对项目所有文档逐个触发重新索引

返回每步执行状态：
```json
{
  "code": 200,
  "data": {
    "steps": [
      { "step": "generate_env", "status": "done" },
      { "step": "write_env", "status": "done" },
      { "step": "restart_rag", "status": "done", "detail": "Healthy" },
      { "step": "reindex", "status": "done", "detail": "5/5 succeeded" }
    ],
    "reindexed": 5,
    "failed": 0,
    "total": 5
  }
}
```

---

## 六、全局模型 API 资产管理

UniPortal 提供全局的模型服务商配置，用户注册 API 端点和密钥后，知识库检索配置自动列出可用模型。

### 6.1 服务商管理

| 端点 | 方法 | 功能 |
|---|---|---|
| `/api/model-providers` | GET | 列出当前用户的所有服务商配置 |
| `/api/model-providers` | POST | 添加服务商（name, type, base_url, api_key） |
| `/api/model-providers/:id` | PUT | 更新服务商配置 |
| `/api/model-providers/:id` | DELETE | 删除服务商 |
| `/api/model-providers/:id/test` | POST | 测试连接，自动发现并分类可用模型 |
| `/api/model-providers/available-models` | GET | 聚合所有活跃服务商的可用模型列表 |

### 6.2 支持的服务商类型

| 类型 | 默认 Base URL | 说明 |
|---|---|---|
| `dashscope` | https://dashscope.aliyuncs.com/compatible-mode/v1 | 阿里云百炼 |
| `openai` | https://api.openai.com/v1 | OpenAI 官方 |
| `vllm` | http://localhost:8000/v1 | vLLM 本地推理 |
| `ollama` | http://localhost:11434/v1 | Ollama 本地 |
| `custom` | 用户填写 | 任意 OpenAI 兼容 API |

### 6.3 模型自动分类

测试连接时，UniPortal 调用服务商的 `/models` 端点获取模型列表，按名称启发式分类：

- 包含 `rerank` / `bge-reranker` / `cohere-rerank` → Reranker
- 包含 `embed` / `bge-m3` / `text-embedding` / `e5-` / `gte-` → Embedding
- 其他 → LLM

---

## 七、尚未接入的 RAG 能力

以下能力在 RAG 服务中已实现，但 UniPortal 尚未封装为 BFF 接口。

### 7.1 智能问答（Chat）

RAG 的核心 LLM 能力，基于 LangGraph 有向图编排：

| RAG 端点 | 功能 |
|---|---|
| `POST /api/chat` | 完整问答：意图识别 → 自适应检索 → 证据评级 → 查询重写 → LLM 生成 |
| `POST /api/chat/stream` | 流式问答（SSE 实时输出 token） |
| `GET /api/chat/history/{session_id}` | 获取对话历史 |
| `DELETE /api/chat/session/{session_id}` | 删除对话 |
| `GET /api/chat/prompt-status` | 查看当前 prompt 状态 |

当前状态：UniPortal 只暴露了检索接口（返回 raw chunks），未接入 Chat 问答（返回 LLM 生成的结构化答案）。

### 7.2 会话管理（Sessions）

| RAG 端点 | 功能 |
|---|---|
| `POST /api/sessions` | 创建会话 |
| `GET /api/sessions` | 列出所有会话（分页） |
| `GET /api/sessions/{session_id}` | 查看会话详情 |
| `POST /api/sessions/{session_id}/extend` | 续期会话 |
| `DELETE /api/sessions/{session_id}` | 删除会话 |

### 7.3 反馈系统（Feedback）

| RAG 端点 | 功能 |
|---|---|
| `POST /api/feedback` | 提交反馈（赞/踩/纠正/标记） |
| `GET /api/feedback/stats/summary` | 反馈统计汇总 |
| `GET /api/feedback/{session_id}` | 按会话查反馈 |
| `GET /api/feedback/escalations/pending` | 待处理升级列表 |
| `POST /api/feedback/escalations/{id}/resolve` | 解决升级工单 |

### 7.4 运维管理（Admin）

| RAG 端点 | 功能 |
|---|---|
| `GET /api/admin/metrics` | 系统指标（RSS 内存、GC 统计） |
| `GET /api/admin/circuit-breakers` | LLM / 检索器断路器状态 |
| `POST /api/admin/circuit-breakers/{name}/reset` | 重置断路器 |
| `GET /api/admin/degradation` | 降级模式状态 |
| `POST /api/admin/degradation/mode/{mode}` | 设置降级模式（full/cached/simplified/offline） |
| `GET /api/admin/config` | 运行时完整配置 |
| `GET /api/admin/eval/runs` | 评估运行列表 |
| `GET /api/admin/eval/runs/{run_id}` | 评估运行详情 |
| `GET /api/admin/eval/candidates` | 候选晋升列表 |
| `GET /api/admin/inferences` | 生产推理采样浏览 |
| `GET /api/admin/inferences/{trace_id}` | 推理详情 |
| `GET /api/admin/retrieval-misses` | 检索未命中信号 |

### 7.5 MCP 工具协议

RAG 内置 MCP（Model Context Protocol）兼容的工具接口：

| 工具名 | 功能 |
|---|---|
| `rag_retrieve` | 混合检索 |
| `rag_search_dense` | 语义检索 |
| `rag_search_sparse` | 关键词检索 |

当前状态：UniPortal 通过 REST API 封装了等价的检索能力，未直接暴露 MCP 协议。

### 7.6 高级检索特性

| 特性 | RAG 环境变量 | 说明 |
|---|---|---|
| Contextual Index | `CONTEXTUAL_INDEX_ENABLED` | 存储 bounded index_text + 原始 display_text，支持父文档上下文展开 |
| RAPTOR | `RAPTOR_ENABLED` | 全局摘要层级检索，摘要命中后回溯至原始 chunk |
| Graph PPR | `GRAPH_PPR_ENABLED` | 基于 Personal PageRank 的多跳问题检索 |
| ColPali | `COLPALI_ENABLED` | PDF 页面的视觉索引（视觉嵌入） |
| OCR | `PDF_OCR_ENABLED` | PaddleOCR 识别扫描件/图片 PDF 中的文字 |
| Adaptive Retrieval | `RETRIEVAL_WORKFLOW_ENABLED` | 按问题类型动态规划检索通道和预算 |

以上特性均通过 RAG 环境变量控制，默认关闭。启用需在 RAG 服务的 `.env` 或 docker-compose 中配置对应变量。

---

## 八、部署配置

### 8.1 环境变量

| 变量 | 作用 | 默认值 |
|---|---|---|
| `RAG_SERVICE_URL` | RAG 服务地址 | `http://rag:8000`（Docker 内）/ `http://host.docker.internal:8002`（Mac 本地） |
| `EMBEDDING_PROVIDER` | 嵌入模型提供方 | `api`（DashScope）/ `local`（BGE-M3） |
| `EMBEDDING_MODEL` | 嵌入模型名 | `text-embedding-v3` / `BAAI/bge-m3` |
| `EMBEDDING_DIMENSION` | 向量维度 | `512` / `1024` |
| `EMBEDDING_DEVICE` | 推理设备 | `cpu` / `mps` / `cuda` |
| `RERANKER_ENABLED` | 是否启用 Reranker | `false` / `true` |
| `RERANKER_MODEL` | Reranker 模型 | `BAAI/bge-reranker-v2-m3` |
| `DASHSCOPE_API_KEY` | DashScope API 密钥 | （运行时注入） |
| `ADMIN_API_KEY` | RAG Admin 端点保护密钥 | （运行时注入） |

### 8.2 Docker 部署模式

| 模式 | 构建参数 | 适用环境 |
|---|---|---|
| api-doc（默认） | `INSTALL_EXTRAS=api-doc` | 无 GPU，DashScope API 做 embedding+LLM |
| local-models | `INSTALL_EXTRAS=local-models` | GPU 服务器，本地 BGE-M3 + Reranker |

```bash
# 标准部署（API 模式）
DASHSCOPE_API_KEY=sk-xxx docker compose up -d --build

# 3090 GPU 服务器部署
docker compose -f docker-compose.yml -f docker-compose.3090.yml up -d --build
```

### 8.3 共享卷

| 卷名 | 挂载点 | 用途 |
|---|---|---|
| `uniportal_storage` | `/app/server/storage` | 软件上传文件 + 文档预览副本 |
| `uniportal_db` | `/app/server/data` | SQLite 数据库 |
| `uniportal_rag_data` | `/app/data` | RAG 向量数据（Milvus Lite） |
| Docker socket | `/var/run/docker.sock` | UniPortal 重启 RAG 容器（模型配置应用） |

---

## 九、接口汇总表

| # | 方法 | 端点 | 功能 |
|---|---|---|---|
| 1 | POST | `/api/knowledge/{pid}/documents` | 上传文档 |
| 2 | GET | `/api/knowledge/{pid}/documents` | 列出文档 |
| 3 | DELETE | `/api/knowledge/{pid}/documents/{did}` | 删除文档 |
| 4 | GET | `/api/knowledge/{pid}/documents/{did}/preview` | 预览文档 |
| 5 | GET | `/api/knowledge/{pid}/documents/{did}/download` | 下载文档 |
| 6 | POST | `/api/knowledge/{pid}/documents/{did}/reindex` | 重建索引 |
| 7 | POST | `/api/knowledge/{pid}/retrieval` | 混合检索 |
| 8 | POST | `/api/knowledge/{pid}/retrieval/dense` | 语义检索 |
| 9 | POST | `/api/knowledge/{pid}/retrieval/sparse` | 关键词检索 |
| 10 | PUT | `/api/projects/{pid}/model-config` | 保存模型配置 |
| 11 | GET | `/api/projects/{pid}/model-config` | 获取模型配置 |
| 12 | POST | `/api/projects/{pid}/model-config/apply` | 应用配置并重建索引 |
| 13 | GET | `/api/model-providers` | 列出服务商 |
| 14 | POST | `/api/model-providers` | 添加服务商 |
| 15 | PUT | `/api/model-providers/{id}` | 更新服务商 |
| 16 | DELETE | `/api/model-providers/{id}` | 删除服务商 |
| 17 | POST | `/api/model-providers/{id}/test` | 测试连接 |
| 18 | GET | `/api/model-providers/available-models` | 可用模型列表 |
