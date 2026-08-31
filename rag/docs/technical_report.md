# 领域自适应 RAG 智能问答平台技术报告

> 测试环境：WSL2 Ubuntu / NVIDIA RTX 5070 Ti 16GB / Ollama 0.24.0
> 文档同步日期：2026-07-17；LLM 延迟表为 2026-05-27 历史基线，检索 benchmark 为 2026-07-16/17 隔离复测
> 领域 profile：本报告的实测数据在可选示例 aviation_phm profile（`DOMAIN_PROFILE=aviation_phm`）下采集；平台本身领域无关，默认 `general`，可按 `DOMAIN_PROFILE` + `data/profiles/*.yaml` 切换/新增领域。

---

## 1. 系统概述

本项目是一个**领域自适应**的企业级 RAG 平台，默认领域无关，基于检索增强生成技术提供知识库问答、检索引导与决策支持；仓库自带可选示例 aviation_phm profile，用于演示如何把平台嵌入航空航天领域的故障诊断场景，切换/新增领域 profile 即可服务对应垂直知识库。系统采用前后端分离架构：

- **后端**：FastAPI + LangGraph + Milvus Lite
- **前端**：Vue 3 + Vite + TypeScript
- **LLM**：Qwen3-14B（本地 Ollama 部署，Q4_K_M 量化）
- **Embedding**：本地默认 BGE-M3（1024 维、dense + native sparse，可替换）；API-only 默认 DashScope
- **检索编排**：Fast、Thinking、MCP 共用 adaptive/corrective `RetrievalWorkflow`

---

## 2. 大语言模型：Qwen3-14B

### 2.1 模型规格

| 参数 | 数值 |
|------|------|
| 模型家族 | Qwen3（阿里通义千问第三代） |
| 总参数量 | **14.8B**（148 亿） |
| 非嵌入层参数量 | 12.6B |
| 架构类型 | Decoder-only Transformer（Dense） |
| 层数 | **40** |
| 注意力头（GQA） | Q: 40 heads / KV: 8 heads |
| 原生上下文长度 | **32,768 tokens**（32K） |
| 扩展上下文长度（YaRN） | **131,072 tokens**（128K） |
| 量化格式 | **GGUF Q4_K_M** |
| 模型文件大小 | **9.3 GB** |
| 显存占用 | **~12 GB**（RTX 5070 Ti 16GB，含 KV Cache） |
| 最大输出长度 | 32,768 tokens |
| 多语言支持 | 100+ 语言和方言 |
| 工具调用能力 | 支持（Agent/Function Calling） |
| Ollama 模型 ID | `qwen3:14b` |

### 2.2 双模式推理机制

Qwen3 的核心特性是**在同一模型权重内无缝切换思考模式与非思考模式**：

#### 思考模式（Thinking Mode）

- 默认启用，模型会生成 `<think...>` 包裹的推理链后再输出最终回答
- 适用于复杂逻辑推理、数学计算、编程、深度分析
- **推荐采样参数**：Temperature=0.6, TopP=0.95, TopK=20（禁止贪心解码）
- 开关方式：`enable_thinking=True` 或用户输入 `/think`

#### 非思考模式（Non-Thinking Mode）

- 快速响应模式，跳过推理链直接输出答案
- 适用于简单对话、格式化输出、高频调用场景
- **推荐采样参数**：Temperature=0.7, TopP=0.8, TopK=20
- 开关方式：`enable_thinking=False` 或用户输入 `/no_think`

> **本项目集成方案**：
> - **Thinking 模式（RAG 深度诊断）**：保留 Qwen3 默认 thinking 行为，通过 OpenAI SDK 直接调用 Ollama 捕获 `reasoning` 字段，推理过程（约 800-1600 字符）随响应返回给前端，供用户查看模型的推理逻辑
> - **Fast 模式（快速问答）**：在 Prompt 末尾追加 `/no_think` 关闭推理，跳过 thinking token 生成，降低延迟
> - Temperature=0.0, MaxTokens=4096，`strip_think_tags()` 兜底过滤泄漏的 `<think...>` 标签

### 2.3 本项目 LLM 配置

```dotenv
# .env
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=qwen3:14b
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=60
LLM_MAX_RETRIES=1
```

模型配置统一从环境变量读取，进程环境变量优先于项目根目录 `.env`。
Embedding 模型 ID、本地路径、向量维度、设备和批大小同样可通过
`EMBEDDING_*` 环境变量配置。

### 2.4 离线资产预热与打包

`deploy.sh` 支持在与目标机 OS/版本、架构、Python patch/ABI 完全一致的联网主机上生成离线包：

```bash
./deploy.sh --build-offline-bundle
```

预热阶段会下载或验证以下资产：

1. Ollama LLM 模型，存放于 `models/local_models/ollama`。
2. BGE-M3 Embedding 模型，存放于 `models/local_models/bge-m3`；下载器校验训练好的
   `sparse_linear.pt` 与 `colbert_linear.pt`，不允许随机初始化 head 进入索引。
3. Reranker 模型，存放于 `models/local_models/reranker/...`，避免依赖用户级 Hugging Face cache。
4. frozen Python dependency closure 的专用 uv cache，以及固定 uv 0.11.8。
5. 前端 `web/dist` 构建产物；OCR/Office extra 只在显式 `--with-ocr`/`--with-doc` 时加入。

ColPali 是默认关闭的实验通道，不属于标准运行资产。需要时由操作员显式执行
`uv run --frozen python scripts/download_colpali.py`；运行时不会联网下载。

离线包包含 Git allowlist 项目代码、`uv.lock`、专用 uv cache、`models/local_models/`、
固定 uv、平台 metadata、全文件 `SHA256SUMS` 与 `install_offline.sh`；真实 `.env` 和 secret
目录不会进入制品。目标机解压后运行：

```bash
./install_offline.sh /opt/rag-platform
```

安装器在写目标前校验 hash 与平台/ABI，再执行 `uv sync --frozen --offline`。目标机仍需预装
匹配 Python、系统共享库、驱动与 Ollama；升级必须停服、显式 `--upgrade`，并先生成完整备份。
操作细节见 `docs/deployment/offline.md`。Windows 11 WSL2 的非 Docker 本地模型路径使用
`deploy_wsl.sh` + versioned inactive release + systemd，完整步骤和全部接口见
`docs/deployment/WSL_DEPLOYMENT.md`。

### 2.5 推理性能实测

测试硬件：NVIDIA RTX 5070 Ti 16GB（GPU 占用约 12GB，14B Q4_K_M 量化）

本节保留 2026-05-27 的 LLM/端到端历史基线，用于说明生成开销；当前检索性能与 promotion
结论以第 13 节的 2026-07-16/17 隔离 benchmark 为准，两类数字不可直接混用。

#### 基础 LLM 调用

| 测试场景 | 输入长度 | 输出长度 | 首 Token 延迟 (TTFT) | 总延迟 |
|----------|----------|----------|---------------------|--------|
| 短提示（"你好"） | ~5 tokens | 15 chars | — | **5,449 ms** |
| RAG 问答（含上下文） | ~200 tokens | 755 chars | — | **6,420 ms** |
| 流式生成 | ~20 tokens | 171 chars | **4,003 ms** | 4,661 ms |

#### RAG 系统端到端对比（Fast vs Thinking）

| 查询 | 模式 | 总耗时 | 回答长度 | 推理过程 | 路由 |
|------|------|--------|---------|---------|------|
| 发动机振动偏高 | Fast（/no_think） | **10,941 ms** | 1,249 chars | 无 | fast |
| 发动机振动偏高 | Thinking | **14,750 ms** | 1,076 chars | **837 chars** | rag |
| 液压系统压力低 | Fast（/no_think） | **11,225 ms** | 1,012 chars | 无 | fast |
| 液压系统压力低 | Thinking | **17,503 ms** | 910 chars | **1,632 chars** | rag |
| 起落架收放超时 | Fast（/no_think） | **9,277 ms** | 944 chars | 无 | fast |
| 起落架收放超时 | Thinking | **9,915 ms** | 917 chars | **926 chars** | rag |

**性能分析**：
- Fast 模式（/no_think）比 Thinking 模式平均快 **15-40%**，省去了推理 token 生成开销
- Thinking 模式额外产生 800-1,600 字符的推理过程，可帮助用户理解模型的分析逻辑
- TTFT 约 4-5.5 秒，主要耗时在 GPU 加载和 KV Cache 初始化
- GPU 显存占用 12GB/16GB（75%），14B 参数模型充分利用 GPU 资源

---

## 3. RAG 系统架构

### 3.1 整体架构图

```
用户请求
   │
   ▼
FastAPI（Chat / Documents / Sessions / Admin / Retrieval）
   │
   ├─ General Chat ───────────────────────────────► LLM
   │
   ├─ Thinking ─► Agent ─► RetrieveSkill ─► Grade/Rewrite/Generate
   │                         │
   ├─ Fast ──────────────────┤
   │                         ▼
   └─ MCP rag_retrieve ─► Shared RetrievalWorkflow
                             │
                             ├─ typed plan + bounded budgets
                             ├─ request-local query representation
                             ├─ Dense + native sparse/BM25 + optional healthy channels
                             ├─ RRF + Cross-Encoder + authority + selector
                             └─ accept | weak | conflict | empty
                                      │
                                      ├─ accept ─► generation
                                      └─ others ─► safe terminal response

Documents ingestion ─► Milvus/BM25 main index
                    └► optional contextual/RAPTOR/visual generations（default off）
```

### 3.2 双流水线设计

系统提供两种推理模式，满足不同延迟和深度需求：

| 维度 | Thinking 模式 | Fast 模式 |
|------|-------------|-----------|
| 外层流水线 | 意图→Agent→RetrieveSkill→评分→重写/生成 | RetrievalWorkflow→生成 |
| LLM 调用次数 | 4-6 次 | 1 次 |
| Qwen3 Thinking | **开启**（捕获推理过程） | **关闭**（/no_think） |
| 推理过程 | 返回 800-1,600 字符推理内容 | 无推理内容 |
| 典型延迟 | 受多轮本地 LLM 调用影响 | 主要由单次生成决定 |
| 适用场景 | 复杂结构化分析、深度回答 | 高频查询、快速响应 |
| 检索内核 | 共享 planner/corrective workflow，外层仍可追加 Grade/Rewrite | 同一 workflow，无外层 Grade/Rewrite |
| 安全终态 | weak/conflict/empty 不进入正常生成 | 同左 |
| Reasoning 传递 | `metadata.reasoning` 返回前端 | 无 |

---

## 4. 检索系统

### 4.1 Embedding 模型

| 参数 | 数值 |
|------|------|
| 本地默认模型 | `BAAI/bge-m3` |
| 向量维度 | **1024** |
| 表示 | dense + lexical sparse + 可选 ColBERT token vectors |
| 最大输入 | 8,192 tokens；FlashAttention 不可用时安全下调 |
| 运行设备 | `auto`：CUDA wheel 含本机 `sm_xx` 时用 GPU，否则 CPU |
| 批处理大小 | 8 |
| 归一化 | True |
| 资产完整性 | native sparse/ColBERT 必须存在训练好的 `sparse_linear.pt` / `colbert_linear.pt` |

`EMBEDDING_PROVIDER=auto` 在 torch 与 `langchain-huggingface` 可导入时选择本地 BGE-M3；
torch-less API-only profile 自动选择 DashScope `text-embedding-v3`。缺少训练 head 时不会使用
随机初始化权重：dense 保留，sparse 回退 BM25，ColBERT 关闭。

### 4.2 向量数据库（Milvus Lite）

| 参数 | 数值 |
|------|------|
| 存储后端 | SQLite（本地文件 `milvus_data.db`） |
| Collection | `rag_knowledge_base` |
| 索引类型 | AUTOINDEX |
| Dense | `FLOAT_VECTOR(1024)`，IP（归一化后等价 cosine 排序） |
| Native sparse | BGE-M3 时增加 `SPARSE_FLOAT_VECTOR` + `SPARSE_INVERTED_INDEX` |
| 最大文本长度 | 4,000 字符 |
| 最大元数据长度 | 500 字符 |
| 批处理大小 | 20 |
| 一致性级别 | Bounded |

### 4.3 自适应检索与排序策略

默认 plan 仍以 Dense/Sparse 各 0.5 为安全基础，但 `RetrievalPlanner` 会根据 exact、procedure、
comparison、multi-hop、global-summary、visual 等问题类型调整权重、候选预算、facet 与健康通道。

```text
plan
  -> Dense + native sparse（或 BM25 fallback）
  -> optional Graph/ColBERT/RAPTOR/ColPali（默认关闭且需能力/过滤匹配）
  -> RRF(k=60)
  -> bge-reranker-v2-m3（默认开启）
  -> authority/version ordering
  -> facet/parent-aware evidence selection
  -> accept | weak | conflict | empty
```

静态 enlarged candidate funnel 与 contextual index 在控制实验中没有稳定收益，因此默认关闭。
ColBERT、RAPTOR、Graph PPR 与 ColPali 只完成 deterministic/synthetic 算法闭环，尚未获得
真实模型和私域语料的 promotion 资格。

### 4.4 检索性能实测

2026-07-16/17 的独立进程 AB/BA 结果如下；每个 dataset×variant 使用独立 Milvus、collection、
registry、cache namespace 和可选 store，排除顺序与热缓存串扰：

| 数据集 | Recall control→workflow | nDCG control→workflow | Warm P95 ms control→workflow | Query forwards control→workflow |
|---|---:|---:|---:|---:|
| builtin general | 1.000→1.000 | 1.000→1.000 | 104.1→66.1 | 56→24 |
| CMRC2018 | 1.000→1.000 | 0.934→0.971 | 177.5→146.2 | 210→90 |
| HotpotQA | 0.917→0.917 | 0.915→0.919 | 169.5→141.8 | 210→90 |
| MS MARCO judged | 0.900→0.900 | 0.773→0.795 | 135.6→105.5 | 140→60 |

四个数据集 Recall 无损，MRR/nDCG 持平或提升，query embedding forwards 下降约 57%。
完整证据、限制和复现命令见第 13 节。

### 4.5 文档分块策略

上传路由支持 `.md`、`.txt`、`.pdf`、`.docx`、`.pptx`、`.html`、`.htm`；Office/HTML
格式依赖 `doc` extra。主摄入始终先保证 Milvus 与 BM25/native sparse 可用，contextual、
RAPTOR 与 visual generation 均为可选旁路，失败不阻断主索引。

#### PDF 结构化解析与 OCR

PDF 上传按页面级 ingestion pipeline 处理：

1. 优先使用 `pypdfium2` 抽取文字层；单页失败或文字不足时使用 `pypdf` 逐页兜底。
2. 明确保留列分隔符（`|`、Tab、多空格）的表格转换为 Markdown 表格 chunk，metadata 标记 `content_type=table` 与 `table_id`。
3. 带图片对象的页面记录 `pdf_image_count`、`pdf_has_images` 等 metadata，便于来源审计和后续多模态扩展。
4. 当 `PDF_OCR_ENABLED=true` 时，图片页/扫描页会由 `pypdfium2` 渲染为页面图片，并调用 PaddleOCR 生成 `content_type=ocr_text` chunk。

当前 OCR 引擎为 PaddleOCR（`paddlepaddle` + `paddleocr`）。首次运行会下载官方模型到
`~/.paddlex/official_models/`。在 CPU 环境中，项目默认设置
`PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0`，以规避 PaddlePaddle 3.x 在部分主机上
触发 oneDNN/PIR `ConvertPirAttribute2RuntimeAttribute` 推理错误。

OCR 结果适合进入 RAG 检索，但不是强一致结构化抽取；故障码中的 `0/O`、`1/I` 等字符
可能出现混淆，关键业务字段仍建议在上游 PDF 生成阶段保留文字层或经过人工校验。

| 参数 | 数值 |
|------|------|
| 语义分块阈值 | 1,200 tokens |
| 字符回退阈值 | 5,000 chars |
| 回退分块大小 | 900 tokens |
| 分块重叠 | 120 tokens |
| 小文档保留阈值 | < 3,840 chars 不分块 |
| 分块方式 | 语义分块（优先）→ RecursiveCharacterTextSplitter（回退） |

---

## 5. LangGraph 工作流

### 5.1 Thinking 模式完整流水线

```
START
  │
  ▼
┌──────────┐  意图分类（LLM/关键词）
│  Agent   │──────────────────────┐
│  Node    │  判断是否需要检索      │
└────┬─────┘                      │
     │ tools_condition             │
     ├─ 需要检索 ──→ Retrieve      │ END（直接回答）
     │          (RetrievalWorkflow)│
     │                 │           │
     │                 ▼           │
     │           Grade Documents   │
     │           (LLM 评分)        │
     │                 │           │
     │          ┌──────┴──────┐    │
     │          │             │    │
     │     相关 ▼          不相关▼  │
     │    ┌─────────┐   ┌────────┐ │
     │    │ Generate │   │ Rewrite│ │
     │    │  Node    │   │  Node  │ │
     │    └────┬────┘   └───┬────┘ │
     │         │            │      │
     │         ▼            │      │
     │        END    回到 Agent ────┘
     │               (最多重写3次)
```

`Retrieve` 内部先产生 typed plan，执行混合/可选通道、authority/selector 和最多一次 changed
retry，并把 `retrieval_diagnostics` 写入 `shared_state`。Generate Skill 在调用 LLM 前检查
`should_generate`；`weak`、`conflict`、`empty` 使用统一终止语义，不把不可用相关性写成 0。

### 5.2 各节点配置

| 节点 | 超时 | 重试 | 说明 |
|------|------|------|------|
| Agent Node | 60s | 2次 | 决定是否调用检索工具 |
| Retrieve Node | — | 最多 1 次 changed retry | 执行共享 planner/corrective workflow |
| Grade Node | — | — | LLM 结构化输出判断文档相关性 |
| Rewrite Node | — | — | 优化查询以提升检索质量（最多3轮） |
| Generate Node | 120s | 2次 | 基于上下文生成结构化回答 |
| Intent Classifier | 10s | 2次 | 意图分类：rag_query / general_chat |

### 5.3 快速模式性能实测

Fast 模式仍只调用一次生成 LLM。2026-05-27 历史基线中，单次本地 Qwen3-14B 生成约
6-8.5 秒，是端到端延迟的主要部分；当前检索 workflow 的隔离 warm P95 为
66-146 ms（按数据集不同，见 §4.4）。两者测量协议不同，不能把旧的单 query 热启动数字
当作当前四数据集 benchmark。

---

## 6. Prompt 工程

### 6.1 生成节点 Prompt

系统 Prompt 的结构化输出模板由 active profile 的 `section_template` 决定（领域自适应）。
在可选示例 aviation_phm profile 下，要求模型严格按以下格式输出：

```
【诊断结论】...
【可能原因】1. ...
【排查步骤】1. ...
【风险与安全提示】...
【依据来源】1. 来源:... | 标题:... | 证据:...
【信息缺口】...
```

核心规则：
1. 仅使用上下文信息，不编造
2. 优先引用关键标识符、章节、参数阈值、操作步骤
3. 每条依据标注来源
4. 存在风险时给出风险提示
5. 信息不足时列出缺失数据

### 6.2 查询重写 Prompt

当文档评分不通过时，Rewrite 节点优化用户查询，补全可检索要素（实体、现象、标识符、章节、场景）。

### 6.3 文档评分 Prompt

二元评分（相关/不相关），基于文档是否包含相关实体、现象、标识符、章节、流程等要素。

---

## 7. 容错与降级机制

### 7.1 断路器（Circuit Breaker）

| 参数 | LLM 服务 | 检索服务 |
|------|---------|---------|
| 失败阈值 | 3 次 | 5 次 |
| 恢复超时 | 60s | 30s |
| 半开最大调用 | 3 次 | 3 次 |
| 成功恢复阈值 | 2 次 | 2 次 |

### 7.2 重试策略

| 参数 | 数值 |
|------|------|
| 最大重试次数 | 3 |
| 基础延迟 | 1.0s |
| 最大延迟 | 60s |
| 指数基数 | 2.0 |
| 抖动 | 启用 |
| 可重试异常 | ConnectionError, TimeoutError |

### 7.3 降级模式

| 模式 | 说明 |
|------|------|
| FULL | 正常运行 |
| CACHED_ONLY | 仅返回缓存响应 |
| SIMPLIFIED | 简化响应 |
| OFFLINE | 最小离线模式 |

降级缓存 TTL：3600 秒（1 小时）

### 7.4 检索热路径降级

| 组件 | 不可用时的行为 |
|---|---|
| planner / filter | planner 回到 bounded dense+sparse safe plan；非法/不支持 filter 绝不无过滤重试 |
| BGE-M3 query representation | 丢弃不完整原子表示，保留可用 dense/BM25；缺失值为 `None` |
| dense/sparse/graph 任一腿 | 仅移除失败腿，RRF 使用其余健康通道；总失败返回安全空结果 |
| reranker / ColBERT / selector | 保持 RRF/authority 顺序并 bounded backfill，不伪造分数 |
| RAPTOR / Graph PPR / ColPali | 不贡献可选结果；回到 ordinary hybrid/OCR/text |
| corrective score | 全部评分不可用时为 `weak + degraded=True`，而不是 0 分或错误 accept |

完整强制矩阵见 `core/AGENTS.md`。所有新增持久化路径均暴露模块级属性，测试可重定向到
`tmp_path`；应用关闭时 reset 对应 workflow/store 单例。

---

## 8. 会话管理

| 参数 | 数值 |
|------|------|
| 主存储 | Redis（`redis://localhost:6379/0`） |
| 备用存储 | SQLite（`./data/sessions.db`） |
| 每会话最大消息数 | 50 |
| 连接池大小 | 5 |
| Key 前缀 | `rag:session:` |

---

## 9. API 接口

下表是代表性 HTTP 接口；完整请求/响应见 `docs/API.md`，进程内 MCP 工具见 `docs/MCP.md`。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 同步对话（支持 thinking/fast 模式） |
| POST | `/api/chat/stream` | SSE 流式对话 |
| GET | `/api/chat/history/{session_id}` | 获取历史记录 |
| DELETE | `/api/chat/session/{session_id}` | 清除会话 |
| GET | `/api/chat/prompt-status` | Prompt 状态 |
| POST | `/api/documents/upload` | 上传 md/txt/pdf/docx/pptx/html/htm |
| GET | `/api/documents` | 文档列表 |
| DELETE | `/api/documents/{doc_id}` | 删除文档 |
| POST | `/api/documents/reindex` | 重建索引 |
| POST | `/api/retrieval` | 低层混合检索（不执行高层 RetrievalWorkflow） |
| POST | `/api/retrieval/dense` | Dense-only baseline |
| POST | `/api/retrieval/sparse` | BM25-only baseline |
| GET | `/api/sessions` | 会话列表 |
| POST | `/api/sessions` | 创建会话 |
| GET | `/live` | 进程存活检查（不探测依赖） |
| GET | `/health` | 健康检查 |
| GET | `/api/admin/metrics` | 系统指标 |

---

## 10. 前端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.4.0 | 前端框架 |
| Vite | 5.0.0 | 构建工具 |
| TypeScript | — | 类型安全 |
| Pinia | 2.1.0 | 状态管理 |
| Vue Router | 4.2.0 | 路由 |
| Axios | 1.6.0 | HTTP 客户端 |
| Marked | 11.0.0 | Markdown 渲染 |
| Highlight.js | 11.9.0 | 代码高亮 |
| DOMPurify | 3.3.2 | XSS 防护 |

---

## 11. 核心依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| LangChain | ≥1.0.0 | LLM 编排框架 |
| LangGraph | ≥1.0.0 | 有状态工作流 |
| langchain-openai | — | OpenAI 兼容接口（LLM；任何 OpenAI 兼容端点） |
| langchain-huggingface | — | 本地 Embedding（`local-models` extra） |
| pymilvus | ≥2.5.0 | Milvus Python SDK |
| milvus-lite | ≥2.5.0 | 轻量级向量数据库 |
| sentence-transformers | ≥3.0.0 | 本地 Embedding/Reranker 模型（`local-models` extra） |
| torch | ≥2.0.0 | 本地推理后端（`local-models` extra；API-only 镜像不含） |
| FastAPI | ≥0.109.0 | Web 框架 |
| uvicorn | ≥0.27.0 | ASGI 服务器 |
| pydantic | ≥2.0.0 | 数据校验 |
| loguru | ≥0.7.0 | 日志 |

---

## 12. 硬件资源占用

| 资源 | 当前事实 |
|------|----------|
| LLM | Qwen3-14B Q4_K_M，历史实测约 12 GB/16 GB GPU 显存 |
| Embedding | 本地 BGE-M3；设备自动选择，benchmark 在 RTX 5070 Ti/cu132 上运行 |
| Reranker | `bge-reranker-v2-m3` 默认开启，是查询延迟与本地内存的重要组成部分 |
| Milvus/RAPTOR/visual | 均为本地文件，实际大小随语料、页面数和可选通道而变化 |
| API-only | 不安装 torch/BGE/Reranker 本地权重，embedding 走 DashScope |

旧的 “BGE-small 约 91 MB、Milvus 约 230 KB” 只对应早期小语料实验，不再代表当前默认部署。

---

## 13. 评测基准与回归实测

本节以 `torch 2.12.1+cu132`、RTX 5070 Ti（`sm_120`）、本地 BGE-M3/1024 与本地
`bge-reranker-v2-m3` 为环境。每个 dataset×variant×order 使用独立进程、Milvus DB、
collection、embedding registry、cache namespace、RAPTOR DB 与视觉索引；模型权重未训练或修改。

### 13.1 Shared workflow AB/BA promotion

`top_k=4`、每个进程三轮；表中为独立 AB/BA 进程的中位结果：

| 数据集 | Recall control→workflow | MRR control→workflow | nDCG control→workflow | Warm P95 ms control→workflow | Query forwards control→workflow |
|---|---:|---:|---:|---:|---:|
| builtin general | 1.000→1.000 | 1.000→1.000 | 1.000→1.000 | 104.1→66.1 | 56→24 |
| CMRC2018 | 1.000→1.000 | 0.911→0.961 | 0.934→0.971 | 177.5→146.2 | 210→90 |
| HotpotQA | 0.917→0.917 | 1.000→1.000 | 0.915→0.919 | 169.5→141.8 | 210→90 |
| MS MARCO judged | 0.900→0.900 | 0.729→0.758 | 0.773→0.795 | 135.6→105.5 | 140→60 |

四个数据集 Recall 零损失，MRR/nDCG 持平或提升，warm P95 均通过不高于 control 1.25 倍的
门禁，query embedding forwards 下降约 57%，因此 `RETRIEVAL_WORKFLOW_ENABLED=true` 保持默认。

MS MARCO 只保留 20 个同时具有有效答案和 selected passage 的 judged query。旧 adapter 曾把
10 个 `No Answer Present.`/无 selected passage 行的最后一个无关 passage 误作 ground truth；
现已由生成器与 checked-in dataset contract test 永久拒绝。298 文档语料不变，被移除行仍作为
distractor，不再制造虚假召回目标。

### 13.2 Eight-variant production matrix

balanced schedule 覆盖 BM25-only、dense-only、hybrid RRF、hybrid+reranker、production legacy、
workflow、workflow funnel 和 workflow contextual。核心结论：

- BM25-only 成本最低，但在 HotpotQA 与 MS MARCO 明显损失质量。
- Dense-only 是公开多分布下最强的低延迟 baseline，但不是所有语料的全局最优。
- Reranker 对 multi-hop/top-4 质量重要，同时是查询延迟的主要部分。
- Workflow 匹配或提升最佳 reranked 质量，并复用 query representation。
- enlarged funnel 与 contextual index 没有稳定增益，保持默认关闭。

跨进程 latency range 触发了保守 position warning，因此该矩阵用于 Pareto/确认；默认 promotion
由上面的独立 AB/BA 实验决定。

### 13.3 Public retrieval evidence

Nano-BEIR 使用完整 corpus/50 queries/qrels，MIRACL-zh 使用 5 个 query、全部正例与 200 个
deterministic negatives，后者只属于 sampled-local：

| 数据集 | 最优观察 | 结论 |
|---|---|---|
| Nano SciFact | hybrid nDCG@10 0.732，Recall@100 0.960 | lexical+dense 融合有利 |
| Nano NFCorpus | hybrid nDCG@10 0.366 | hybrid 优于单通道 |
| Nano FiQA | dense nDCG@10 0.574，Recall@100 0.846 | dense-only 明显更优 |
| MIRACL-zh sampled | dense/hybrid nDCG@10 均 1.000 | dense 更便宜，样本不足以全局 promotion |

所以不存在“所有数据都应强制 hybrid”的结论。封闭部署必须用自己的 private golden 校准通道、
reranker 和拒答阈值。

### 13.4 Optional frontier evidence boundary

ColBERT、RAPTOR、Graph PPR/path 和 ColPali 的 deterministic microbenchmark 均完成 enabled/disabled
闭环，但使用 synthetic token encoder，只证明算法与降级接线，不证明真实 checkpoint/私域收益。
这些通道继续默认关闭；ColPali 目前只保证页面定位，生成模型仍是文本模型，不能把页面命中解释为
完整视觉问答能力。

### 13.5 End-to-end eval and reproduction

2026-06-24 的 aviation_phm 示例 E2E 历史结果为 15/15 通过、平均规则分 0.911；它说明评测飞轮
与本地 LLM 链路可运行，不用于替代 2026-07-17 的检索 promotion 数据。Qwen3-14B Thinking 多轮
调用在单卡上仍受吞吐限制，较低并发更稳定。

```bash
uv run --frozen python scripts/run_paired_benchmark.py \
  --dataset data/benchmark/builtin_general.yaml \
  --dataset data/benchmark/benchmark_cmrc2018.yaml \
  --dataset data/benchmark/benchmark_hotpotqa.yaml \
  --dataset data/benchmark/benchmark_msmarco.yaml \
  --output-dir /tmp/rfo-stage2-abba --top-k 4 --repeats 3

uv run --frozen --extra benchmark python scripts/run_benchmark_matrix.py \
  --matrix data/benchmark/retrieval_baselines.yaml \
  --dataset data/benchmark/builtin_general.yaml \
  --schedule balanced --top-k 4 --repeats 3

uv run --frozen python scripts/run_eval.py \
  --dataset data/eval/golden.yaml --no-judge --concurrency 1
```

完整逐变体结果与证据等级见：

- `docs/specs/retrieval-frontier-optimization/benchmark-results.md`
- `docs/specs/retrieval-benchmark-expansion/benchmark-results.md`

---

## 14. 优化建议

### 14.1 LLM 性能优化

- 在封闭单卡部署中优先优化并发、上下文预算、TTFT 和请求排队，不把检索收益与 LLM 吞吐混为一谈。
- Temperature=0.0 保持评测确定性；若调整 Thinking/非 Thinking 采样参数，必须单独跑生成 golden 与 judge 回归。
- Fast 已通过 `/no_think` 降低生成开销；需要更高吞吐时应比较更小本地模型或受控 API endpoint。

### 14.2 检索质量优化

- 第一优先级是建立部署语料的 private golden，覆盖 exact、procedure、comparison、multi-hop、全局总结、扫描 PDF 与版本冲突。
- 依据 private golden 比较 dense-only、BM25/native sparse、hybrid 和 reranker；公开数据已经证明最优通道依赖分布。
- Reranker 是主要检索延迟来源，可在不损伤私域 nDCG/Recall 的前提下评估更小模型、较小候选池或按 query type 跳过。
- ColBERT/RAPTOR/Graph PPR/ColPali 只有在真实 checkpoint + 真实语料通过同一隔离门禁后才能默认开启。
- Contextual index 必须迁移到新 collection，并与 control 做 AB/BA；不能原地修改生产向量空间。

### 14.3 架构优化

- 将 `retrieval_diagnostics` 的聚合统计接入运维面板，重点观察 weak/conflict/empty、retry、cache hit 和通道 unavailable 比例。
- 为 RAPTOR/visual generation 增加后台维护与容量告警，但保持原子发布、旧代回滚和主摄入不阻断。
- 若要发挥 ColPali 的图表/图像价值，需要引入经过独立评审的多模态生成链；当前仅定位页面。
- 继续使用 balanced/AB-BA runner 防止 warm cache、运行顺序与共享 store 被误判为算法提升。

---

## 参考文献

- [Qwen3 Technical Report (arXiv:2505.09388)](https://arxiv.org/abs/2505.09388)
- [Qwen3-14B Model Card (HuggingFace)](https://huggingface.co/Qwen/Qwen3-14B)
- [Qwen3 Blog: Think Deeper, Act Faster](https://qwenlm.github.io/blog/qwen3/)
- [BGE-M3 Model Card (BAAI)](https://huggingface.co/BAAI/bge-m3)
- [BEIR Benchmark](https://github.com/beir-cellar/beir)
- [Milvus Lite Documentation](https://milvus.io/docs/milvus_lite.md)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
