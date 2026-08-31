# 领域自适应 RAG 智能问答平台

面向任意知识领域的本地 RAG 智能问答平台。通过 `DOMAIN_PROFILE` 切换或新增领域——
同一套代码可服务通用知识库、运维排障等任意垂直领域，新增领域只需在 `data/profiles/`
下加一份 YAML，无需改代码。仓库自带一份 `aviation_phm` 可选示例 profile，用于演示
如何把系统嵌入航空航天领域；主链路默认领域无关。

系统能够导入各类手册/文档等知识资料，通过混合检索与大语言模型生成带依据的回答
（在配置了结构化输出模板的领域下，可进一步输出摘要、要点、步骤等结构化回答）。

项目默认领域无关（`DOMAIN_PROFILE=general`），使用本地 Ollama 与 Qwen3 模型，知识库和
会话数据均可在本机运行，适合内网、离线环境和需要保护技术资料的场景。

## 核心能力

- **双问答模式**：Thinking 模式执行完整 LangGraph 流程，Fast 模式复用同一检索工作流后直接生成
- **自适应检索工作流**：按问题类型规划通道与预算，复用查询表示，执行权威排序、证据判定和最多一次有效纠正重试
- **混合检索**：本地 BGE-M3 默认使用 Dense + 原生 Sparse，API/非 M3 配置回退 BM25，经 RRF、Cross-Encoder 与证据选择收敛
- **可选前沿通道**：ColBERT、RAPTOR、Graph PPR 和 ColPali 已接入安全降级，真实模型 promotion 前保持默认关闭
- **知识库管理**：支持上传、查询、删除、去重和重建文档索引
- **结构化诊断**：输出诊断结论、可能原因、排查步骤、安全风险和依据来源
- **推理过程捕获**：支持读取 Qwen3 的 reasoning 内容
- **会话与反馈**：保存对话历史，收集点赞、点踩、纠正和标记反馈
- **可靠性能力**：包含 tracing、指标、熔断、降级和输入输出 guardrails
- **生产部署**：FastAPI 可直接托管前端静态文件，并支持 `/rag` 等反代前缀

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 编排 | LangGraph、Harness + Skills + MCP |
| 后端 API | FastAPI、Uvicorn |
| LLM | Qwen3:14b、Ollama OpenAI 兼容接口 |
| Embedding | 本地默认 BGE-M3（1024 维，可替换）；API-only 默认 DashScope text-embedding-v3 |
| 检索 | RetrievalWorkflow、Milvus Lite、BGE-M3 Sparse/BM25、RRF、bge-reranker-v2-m3 |
| 会话存储 | Redis，可自动降级到 SQLite |
| 领域适配 | `DOMAIN_PROFILE` + `data/profiles/*.yaml`（默认 general；可选示例 aviation_phm） |
| 前端 | Vue 3、Vite、TypeScript、Pinia |

## 工作流程

Thinking 模式的外层 LangGraph 与共享检索工作流如下：

```text
用户问题
  -> 意图识别
  -> Agent 判断是否调用检索工具
  -> RetrievalWorkflow
       -> 问题类型与预算规划
       -> 请求级查询表示复用
       -> Dense + Sparse（必要时启用健康的可选通道）
       -> RRF / Reranker / Authority / Evidence Selection
       -> accept | weak | conflict | empty
       -> 非 accept 时最多一次改变检索策略的纠正重试
  -> 文档相关性评分
  -> 必要时重写问题并重新检索
  -> 生成结构化诊断回答
```

Fast 模式跳过外层 Agent、Grade 和 Rewrite 节点，但复用同一 `RetrievalWorkflow`。只有
`accept` 状态进入生成；`weak`、`conflict`、`empty` 返回对应的信息缺口、冲突或无证据提示。
设置 `RETRIEVAL_WORKFLOW_ENABLED=false` 可回滚到旧的 list-only 检索路径，无需删除索引。

## 快速开始（Quick Start）

### 1. 环境要求

- Linux、WSL2 或 macOS
- Python 3.10+（开发最低版本；CI 用 3.13 提前发现兼容问题，见 `.github/workflows/`）
- uv 0.11.8、Node.js 20.20.2、npm 10.8.2（脚本会拒绝漂移版本）
- [Ollama](https://ollama.com/)
- 建议至少 16 GB 内存；运行 `qwen3:14b` 建议使用独立显卡

Redis 为可选组件。Redis 不可用时，系统会自动使用 SQLite 保存会话。

### 2. 准备 Ollama 模型

如果 Ollama 尚未作为系统服务运行，请在单独的终端启动：

```bash
ollama serve
```

然后用仓库脚本准备并核对默认模型：

```bash
./deploy_ollama.sh --model qwen3:14b
```

可以通过 `ollama list` 确认模型已经就绪。

### 3. 配置项目

```bash
git clone <repository-url>
cd RAG
cp .env.example .env
chmod 600 .env
```

如果已经进入本项目目录，直接执行 `cp .env.example .env` 即可。

默认 `.env` 配置：

```dotenv
# LLM
DEPLOYMENT_ENV=development
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=qwen3:14b
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=4096

# Embedding（默认模型；可替换，换模型/维度后须重建 collection）
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_MODEL_PATH=models/local_models/bge-m3
EMBEDDING_DIMENSION=1024
EMBEDDING_DEVICE=auto

# 领域 profile（默认 general 领域无关；嵌入航空航天示例设 aviation_phm）
# 新增领域：在 data/profiles/ 下新增 <name>.yaml 即可，无需改代码。
DOMAIN_PROFILE=general
```

完整配置与说明见 `.env.example`。

### 4. 一键启动开发环境

```bash
chmod +x run.sh stop.sh
./run.sh --profile local
```

首次启动按 `uv.lock` 与根 npm lock 同步依赖。模型资产由 `deploy.sh` / 专用下载脚本显式准备；
脚本默认只监听 loopback，不用于公网生产。

启动完成后访问：

| 服务 | 地址 |
|------|------|
| Web 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000/api |
| Swagger 文档 | http://localhost:8000/docs |
| 存活检查 | http://localhost:8000/live |
| 健康检查 | http://localhost:8000/health |

查看日志或停止服务：

```bash
tail -f logs/backend.log
tail -f logs/frontend.log
./stop.sh
```

### 5. 导入首份知识库文档

可以在前端的“文档管理”页面上传文档，也可以调用 API：

```bash
curl -X POST http://localhost:8000/api/documents/upload \
  -F "file=@md/general_test_knowledge_base.md"
```

支持上传 `.md`、`.txt`、`.pdf`、`.docx`、`.pptx`、`.html` 和 `.htm`；Office/HTML
格式需要安装 `doc` extra 中的相应解析依赖。PDF 会按页面解析：优先使用 `pypdfium2`
抽取文字层，并用 `pypdf` 逐页兜底；明确保留列分隔的表格会转成 Markdown
表格 chunk 入库；带图片页面会记录图片对象元数据。纯扫描图片 PDF 或图片内文字
需要启用 OCR 后才能进入检索索引。

`CONTEXTUAL_INDEX_ENABLED`、`RAPTOR_ENABLED` 和 `COLPALI_ENABLED` 均默认关闭。启用后，
摄入流程会分别维护独立 contextual collection、RAPTOR generation 或 PDF 页面视觉索引；
任一可选索引失败都不会阻断 Milvus/BM25 主摄入路径。

OCR 默认为关闭，适合在安装本地 OCR 引擎后按需打开：

```dotenv
PDF_OCR_ENABLED=true
PDF_OCR_ENGINE=paddleocr
PDF_OCR_LANG=ch
PDF_OCR_DPI=220
```

本项目已支持 PaddleOCR，本地依赖为 `paddlepaddle` + `paddleocr`。首次 OCR 会
下载 PaddleOCR 官方模型到 `~/.paddlex/official_models/`；CPU 环境默认禁用
PaddleX MKLDNN 路径以避免部分主机上的 oneDNN/PIR 推理错误。

上传完成并建立索引后，即可在前端询问：

```text
git 合并冲突如何解决？
```

也可以直接调用问答 API：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"git 合并冲突如何解决？","mode":"thinking"}'
```

## 手动启动

需要分别控制后端和前端时，可以使用以下方式。

安装后端与测试依赖：

```bash
# 本地推理部署（含 torch/embedding/reranker 本地权重）：
uv sync --frozen --extra dev --extra local-models
# 或 API-only 部署（零 torch，embedding 走 DashScope API）：
# uv sync --frozen --extra dev --extra api-only
```

启动后端：

```bash
DEPLOYMENT_ENV=development uv run --frozen uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

在另一个终端启动前端开发服务器：

```bash
npm ci
npm run dev --workspace web
```

Vite 开发服务器会将 `/api` 请求代理到 `http://127.0.0.1:8000`。

## Windows WSL 完整部署（推荐桌面本地方案）

Windows 11 + WSL2 Ubuntu 24.04、不使用 Docker、在 WSL 内运行 Ollama/BGE-M3/reranker 并由
systemd 管理应用时，直接按独立的 [WSL 完整部署指南](docs/deployment/WSL_DEPLOYMENT.md) 执行。
该文档从 Windows/WSL/GPU/固定工具版本开始，覆盖 `deploy_wsl.sh`、localhost 安全边界、真实
Ollama/GPU 验收、备份升级回滚，以及全部 HTTP 和进程内 MCP 接口。

```bash
./deploy_wsl.sh --dry-run
./deploy_wsl.sh
```

WSL 方案使用 `DEPLOYMENT_ENV=production` + `LOCAL_ONLY_DEPLOYMENT=true`，应用和 Ollama 只绑定
loopback；不要为解决 Windows 访问问题改成 `0.0.0.0`。

## Ubuntu 一键部署

`deploy.sh` 以普通部署账户执行 locked dependency sync、模型预热与前端构建。系统包、
Ollama、uv 和 Node 必须预先从受信渠道安装；脚本不会执行远程安装器，也不会覆盖已有 `.env`：

```bash
./deploy.sh --dry-run
./deploy.sh
```

常用选项：

```bash
./deploy.sh --skip-model
./deploy.sh --skip-embedding
./deploy.sh --skip-reranker
./deploy.sh --with-ocr --with-doc
./deploy.sh --build-offline-bundle
```

`deploy.sh` 会预热 BGE-M3、Reranker、Ollama 模型、Python 依赖和 `web/dist`。
其中 Reranker 会保存到 `models/local_models/reranker/...`，避免离线环境依赖
用户级 Hugging Face cache。BGE-M3 下载器会校验训练好的 sparse/ColBERT heads；
ColPali 不属于默认部署资产，只有显式运行 `scripts/download_colpali.py` 才会准备。

裸机的服务账户、只读代码、systemd、Nginx 与 TLS 边界见
[Bare-metal deployment](docs/deployment/bare-metal.md)。

> 上述为**本地推理部署**（含 torch / 本地 LLM / 本地 embedding 权重，需 GPU 或
> 大内存）。若目标环境**无 GPU、镜像 < 4 GB、仅 API 连接**，请改用
> [API-only 部署（DashScope，零 torch）](#api-only-部署dashscope零-torch)。

### 构建离线部署包

在一台有网络的同架构机器上完成预热并打包：

```bash
./deploy.sh --build-offline-bundle
```

默认生成 `offline_bundle.tar.gz`。包绑定构建机的 OS/版本、架构、Python patch 与 ABI，包含：

- 项目代码与 `web/dist` 前端静态构建产物
- bundled uv、专用 uv cache、`uv.lock` 与平台 metadata
- `models/local_models/` 下的 Embedding、Reranker、Ollama 模型目录快照
- `SHA256SUMS` 和 `install_offline.sh`

在断网目标机上解压并安装：

```bash
tar -xzf offline_bundle.tar.gz
cd offline_bundle
./install_offline.sh /opt/rag-platform
```

目标机仍需预先具备基础系统能力：`python3`、可用的 `ollama` 可执行文件，以及可选的
系统共享库。安装器会先校验全量 SHA-256 与平台/ABI，再执行 `uv sync --frozen --offline`。
升级必须停服并显式增加 `--upgrade`，详细流程见 [Offline deployment](docs/deployment/offline.md)。

启动 Ollama 时请设置：

```bash
export OLLAMA_MODELS=/opt/rag-platform/models/local_models/ollama
ollama serve
```

## 生产静态部署

生产环境不运行 Vite 开发服务器。裸机和容器方案均只把应用发布到 loopback，再由 Nginx/TLS
入口代理；完整、可验证的命令见 [Deployment guide](docs/deployment/README.md)。手工构建前端：

```bash
npm ci
npm run build --workspace web
```

然后只启动 FastAPI：

```bash
DEPLOYMENT_ENV=production uv run --frozen --no-sync uvicorn api.main:app --host 127.0.0.1 --port 8000
```

构建输出位于 `web/dist/`。FastAPI 会托管前端资源，并为 Vue Router 提供
SPA fallback。此时前端与 API 均通过 `http://localhost:8000` 访问。

### 使用 `/rag` 反代前缀

构建时设置前端公共路径：

```bash
VITE_BASE_PATH=/rag npm run build --workspace web
APP_ROOT_PATH=/rag DEPLOYMENT_ENV=production uv run --frozen --no-sync \
  uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Nginx 配置示例：

```nginx
location /rag/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

该配置会移除 `/rag` 前缀后再转发给 FastAPI。浏览器请求
`/rag/api/chat` 时，FastAPI 实际收到 `/api/chat`。生产直接使用经过测试的
`deploy/nginx/rag-platform-prefix.conf`，并保证 Vite base、`APP_ROOT_PATH` 与 proxy stripping
三者成对发布。

## 配置说明

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DEPLOYMENT_ENV` | 必须显式设置 | `development` 或 `production`；生产启用 fail-closed 校验 |
| `ALLOWED_ORIGINS` | 本地 loopback origins | 生产必须为明确的非 loopback HTTP(S) origin，禁止 `*` |
| `ADMIN_API_KEY` | 空（仅开发） | 生产必填；Admin 端点不再允许 loopback 兜底 |
| `DOMAIN_PROFILES_DIR` | `data/profiles` | immutable domain profile 目录；容器为 `/app/config/profiles` |
| `OPENAI_BASE_URL` | `http://localhost:11434/v1` | LLM OpenAI 兼容接口 |
| `OPENAI_API_KEY` | `ollama` | LLM API Key |
| `LLM_MODEL` | `qwen3:14b` | 问答模型名称 |
| `LLM_TEMPERATURE` | `0.0` | LLM 采样温度 |
| `LLM_MAX_TOKENS` | `4096` | 单次回答最大生成 token |
| `LLM_TIMEOUT` | `60` | 单次 LLM 请求超时秒数 |
| `LLM_MAX_RETRIES` | `1` | LLM 客户端重试次数 |
| `EMBEDDING_PROVIDER` | `auto` | Embedding 提供方：`auto`（torch 可导入则 `local` 否则 `api`）/ `local`（本地 BGE，需 `--extra local-models`）/ `api`（DashScope `text-embedding-v3`，零 torch）。详见 `docs/specs/api-only-deploy/` |
| `DASHSCOPE_API_KEY` | _（空）_ | DashScope API Key；`EMBEDDING_PROVIDER=api` 时必填（运行时注入，勿入库）。见 §API-only 部署 |
| `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com` | DashScope 服务端点（可覆盖为内网网关） |
| `EMBEDDING_MODEL` | provider-aware | 本地默认 `BAAI/bge-m3`；API 默认 DashScope `text-embedding-v3`；显式配置始终优先 |
| `EMBEDDING_MODEL_PATH` | provider-aware | 本地默认 `models/local_models/bge-m3`；API 模式为空 |
| `EMBEDDING_DIMENSION` | provider-aware | 本地默认 `1024`；API 默认 `512` |
| `EMBEDDING_DEVICE` | `auto` | Embedding 运行设备；`auto` 自动探测（CUDA 可用且 wheel 含本机 sm_xx 时用 `cuda`，否则 `cpu`），也可显式设 `cpu`/`cuda` |
| `EMBEDDING_NORMALIZE` | `true` | 是否归一化 Embedding 向量 |
| `MILVUS_SPARSE_INDEX` | model-aware | 仅本地 BGE-M3 默认 `true`；API 或其它模型必须为 `false` |
| `DOMAIN_PROFILE` | `general` | 领域 profile（`data/profiles/<name>.yaml`）；默认领域无关，可选示例 `aviation_phm` |
| `EMBEDDING_BATCH_SIZE` | `8` | Embedding 编码批大小 |
| `RERANKER_ENABLED` | `true` | 是否在 RRF 融合后启用 Cross-Encoder 重排序（默认开启；设 `false` 关闭） |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | 重排序模型（多语言 cross-encoder） |
| `RERANKER_MODEL_PATH` | `models/local_models/reranker/bge-reranker-v2-m3` | 本地模型目录，存在时优先于模型 ID 加载（气隙自洽） |
| `RERANKER_DEVICE` | `auto` | Reranker 运行设备；`auto` 自动探测，也可显式设 `cpu`/`cuda` |
| `RERANKER_WARMUP` | `false` | 是否在服务启动时加载 Reranker |
| `RERANKER_CANDIDATE_TOP_K` | `10` | Dense 与当前 sparse backend 各自送入 RRF 的候选数 |
| `RERANKER_TOP_K` | `5` | 调用方未指定 `top_k` 时的最终默认结果数 |
| `RERANKER_BATCH_SIZE` | `4`（`.env.example`） | 重排序批大小；未设置环境变量时代码回退值为 `8` |
| `RETRIEVAL_WORKFLOW_ENABLED` | `true` | 统一 Fast/Thinking/MCP 的自适应计划、纠正重试与终止语义；设 `false` 回滚旧检索路径 |
| `RETRIEVAL_CANDIDATE_FUNNEL_ENABLED` | `false` | 独立 candidate/rerank/selection/final 预算实验；控制实验未过质量门禁，默认关闭 |
| `CONTEXTUAL_INDEX_ENABLED` | `false` | 使用 bounded `index_text` + 原始 `display_text`；只允许在新 collection 上开启 |
| `COLBERT_RERANK_ENABLED` | `false` | BGE-M3 token MaxSim 重排，OOM/不可用时保留 Cross-Encoder/RRF 顺序 |
| `RAPTOR_ENABLED` | `false` | 全局摘要层级检索；摘要命中会回溯到原始 chunk，不把摘要当唯一证据 |
| `RAPTOR_DB_PATH` | `data/raptor.db` | RAPTOR building/ready/retired 代际 SQLite 路径 |
| `GRAPH_PPR_ENABLED` | `false` | 多跳问题的 bounded Personalized PageRank 与短路径检索 |
| `COLPALI_ENABLED` | `false` | PDF 全页面视觉定位；模型缺失/OOM 时回退 OCR/文本 |
| `COLPALI_MODEL_PATH` | `models/local_models/colpali` | 显式离线准备的 ColPali 本地目录；运行时绝不下载 |
| `VISUAL_INDEX_PATH` | `data/visual_index.db` | 视觉页面 building/ready 代际索引路径 |
| `RETRIEVAL_CACHE_NAMESPACE` | `default` | 检索与 query-vector 内存缓存命名空间，隔离实验/模型配置 |
| `OTEL_ENABLED` | `false` | 是否启用 OpenTelemetry tracing |
| `OTEL_SERVICE_NAME` | `rag-platform` | Trace 中的服务名 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 空 | OTLP/HTTP trace 接收地址 |
| `OTEL_SAMPLE_RATE` | `1.0` | Trace 采样率，范围 0～1 |
| `OTEL_CONSOLE_EXPORTER` | `false` | 是否将 Span 输出到控制台 |
| `MILVUS_DB_URI` | `./milvus_data.db` | Milvus Lite 数据库路径 |
| `COLLECTION_NAME` | `rag_knowledge_base` | Milvus collection 名称 |
| `MAX_UPLOAD_BYTES` | `52428800` | 最大上传体积（50 MiB），超限返回 HTTP 413 |
| `PDF_EXTRACT_TABLES` | `true` | 是否将明确列分隔的 PDF 表格转为 Markdown chunk |
| `PDF_OCR_ENABLED` | `false` | 是否对扫描页/图片页启用 OCR |
| `PDF_OCR_ENGINE` | `paddleocr` | OCR 引擎，目前支持 `paddleocr`、`tesseract` |
| `PDF_OCR_LANG` | `ch` | OCR 语言配置 |
| `PDF_OCR_DPI` | `220` | PDF 页面渲染为 OCR 图片时的 DPI |
| `PDF_OCR_MIN_TEXT_CHARS` | `20` | 页面文字少于该阈值时才尝试 OCR |
| `PDF_ASSET_DIR` | `data/document_assets` | OCR 页面图片与后续图片资产目录 |
| `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT` | `0` | PaddleOCR CPU 兼容性开关，默认禁用 MKLDNN |
| `APP_ROOT_PATH` | 空 | FastAPI 对外反代路径前缀 |
| `VITE_BASE_PATH` | `/` | 前端构建时的公共路径 |
| `WEB_DIST_DIR` | `web/dist` | FastAPI 托管的前端构建目录 |

系统启动时会加载项目根目录的 `.env`。由 Shell、Docker 或 Kubernetes
传入的环境变量优先级高于 `.env`，因此无需修改文件即可覆盖配置。

### 更换 LLM

项目支持任意 OpenAI 兼容接口。以切换到另一个 Ollama 模型为例：

```bash
ollama pull qwen3:8b
```

修改 `.env`：

```dotenv
LLM_MODEL=qwen3:8b
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=2048
```

重启后端后生效。也可以只对单次启动覆盖：

```bash
LLM_MODEL=qwen3:8b uv run --frozen uvicorn api.main:app --port 8000
```

### 更换 Embedding 模型

Embedding 配置包含三个必须匹配的字段：

```dotenv
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_MODEL_PATH=models/local_models/bge-large-zh-v1.5
EMBEDDING_DIMENSION=1024
```

- `EMBEDDING_MODEL` 是下载来源或 Hugging Face 模型 ID。
- `EMBEDDING_MODEL_PATH` 是本地缓存路径。路径内存在已保存模型时优先加载本地模型。
- `EMBEDDING_DIMENSION` 必须与模型实际输出维度一致。
- 本地 BGE-M3 初次准备或历史缓存升级时运行
  `uv run --frozen --extra local-models python scripts/download_bge_m3.py`。下载器会保留完整
  snapshot，并强制校验 `sparse_linear.pt` 与 `colbert_linear.pt`；仅有 AutoModel 基础权重时，
  系统不会使用随机初始化的头部，而是保留 dense 并将 sparse/ColBERT 安全降级。
- 显式选择非 BGE-M3 本地模型时，系统不会继承 BGE-M3 的默认缓存路径或维度；
  未显式给出 `EMBEDDING_DIMENSION` 会直接报配置错误，避免静默建立错误向量空间。
- Milvus native sparse 只支持本地 BGE-M3。API embedding 或其它本地模型必须设置
  `MILVUS_SPARSE_INDEX=false`；显式启用会在启动阶段 fail fast。
- Collection registry 记录实际加载的模型来源、维度、sparse capability 与训练头指纹，任一变化都必须迁移。

切换 embedding 模型、维度或 sparse capability 时，已有 collection 会被兼容性门禁阻断，
不会继续混用不同向量空间。用 parent store 中的可信正文重建到一个**新** collection：

```bash
uv run --frozen python scripts/migrate_embedding_collection.py \
  --target-collection rag_knowledge_base_m3 \
  --sample-query "用于抽样验证的知识库问题"
```

验证输出后显式切换 `COLLECTION_NAME`；旧 collection 与对应 embedding 配置应保留用于回滚。
不要原地 drop 旧 collection；迁移命令会校验 indexed source 覆盖、写入完整性、目标 schema
和抽样非零召回，失败时清理不完整目标。`deploy.sh` 会按照当前 `.env` 准备本地 Embedding；
`run.sh` 只负责 locked dependency sync 与开发生命周期，不隐式下载模型资产。

若要实验 contextual index，必须创建另一个新 collection，并显式加
`--contextual-index`；不要原地改写当前 collection：

```bash
uv run --frozen python scripts/migrate_embedding_collection.py \
  --target-collection rag_knowledge_base_context_v1 \
  --contextual-index \
  --sample-query "用于抽样验证的知识库问题"
```

### API-only 部署（DashScope，零 torch）

适用于**镜像 < 4 GB、无 GPU、不可跑本地模型**的联网 API 节点。该模式下
所有推理走远程 API：LLM 走 DashScope Qwen（OpenAI 兼容），embedding 走 DashScope
`text-embedding-v3`，reranker 关闭（检索回退 RRF 顺序）。torch/
sentence-transformers/transformers/langchain-huggingface 不进入镜像。

配置和镜像启动统一使用无 secret 示例、文件型 secret 与 Compose：

```bash
cp deploy/env/api-only.env.example deploy/env/api-only.env
mkdir -m 700 -p deploy/secrets
# 由当前安全终端或 secret manager 写入三个非空 secret 文件
docker compose -f deploy/compose.api-only.yaml up -d --build
```

> **PII 合规提醒**：embedding API 会把上传的文档原文发送到 DashScope。对话层
> 的输入脱敏（`agent/guardrails/pii.py`）**不覆盖摄入路径**——若部署合规要求
> PII 不出域，需在摄入前另行脱敏（见 `docs/specs/api-only-deploy/design.md` §9）。

完整操作、`/rag/` 前缀和验证命令见
[API-only Docker deployment](docs/deployment/api-only-docker.md)；历史设计见
`docs/specs/api-only-deploy/`。

### 两阶段重排序（默认开启）

混合检索执行 Dense + 当前 sparse backend（本地 BGE-M3 native sparse 或 BM25 fallback）召回和
RRF 融合后，默认再用 Cross-Encoder 对融合候选文档
进行第二阶段重排序，提升最终排序精度。默认配置如下（无需手动设置即可生效）：

```dotenv
RERANKER_ENABLED=true
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_MODEL_PATH=models/local_models/reranker/bge-reranker-v2-m3
RERANKER_DEVICE=auto
RERANKER_WARMUP=false
RERANKER_CANDIDATE_TOP_K=10
RERANKER_TOP_K=5
RERANKER_BATCH_SIZE=4
```

`RERANKER_DEVICE=auto` 会在 CUDA 可用且安装的 torch wheel 含本机 GPU 的
`sm_xx` kernel 时自动用 GPU，否则用 CPU（无需为 GPU/无 GPU 环境分别配置）。

`deploy.sh` 和 `scripts/download_reranker.py` 会把模型保存到
`RERANKER_MODEL_PATH`，便于离线运行。若该路径为空且只使用 Hugging Face 模型 ID，
首次加载会自动下载到：

```text
~/.cache/huggingface/hub/models--<organization>--<model-name>/
```

推荐保留项目内路径，便于离线打包。需要提前下载并验证模型时运行：

```bash
uv run --frozen python scripts/download_reranker.py
```

配置 `RERANKER_WARMUP=true` 后，服务启动时会加载模型，
避免首个检索请求承担模型加载耗时。

默认 `BAAI/bge-reranker-v2-m3` 是多语言 cross-encoder，对中文（通用中文知识库、可选示例
知识库）和英文均有效。如需降低资源占用，可改用更轻量的模型（例如
`cross-encoder/ms-marco-MiniLM-L-6-v2`，但主要面向英文），再根据显存、延迟和检索
效果决定是否切换。

Cross-Encoder 会增加检索延迟和内存占用，如需关闭设 `RERANKER_ENABLED=false`。
启用后（默认），检索 API 会返回：

- `retrieval_score`：RRF 融合后的召回分数
- `rerank_score`：Cross-Encoder 相关性分数
- `rerank_applied`：本次是否成功应用重排

模型加载失败时系统会保留 RRF 顺序并标记 `rerank_applied=false`，不会中断检索。
运行状态可通过 `/api/admin/health` 查看：`cold` 表示尚未下载，`ready` 表示已缓存但
尚未加载，`healthy` 表示已加载，`degraded` 表示加载失败。

### OpenTelemetry 可观测性

系统支持 FastAPI HTTP Span 与 Agent Skill Span，可通过 OTLP/HTTP 导出到
Jaeger、Grafana Tempo 或 OpenTelemetry Collector。以本地 Jaeger 为例：

```bash
docker run --rm --name rag-jaeger \
  -p 16686:16686 -p 4318:4318 \
  jaegertracing/all-in-one:latest
```

修改 `.env` 并重启后端：

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=rag-platform
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
OTEL_SAMPLE_RATE=1.0
```

随后访问 `http://localhost:16686`，可以查看 HTTP 请求及
`agent.skill.agent`、`agent.skill.retrieve`、`agent.skill.grade`、
`agent.skill.generate` 等 Span。生产环境建议降低采样率。

当前生效配置可通过以下接口查看：

```bash
curl http://localhost:8000/api/admin/config
```

## 常用 API

| 功能 | 方法与路径 |
|------|------------|
| 非流式问答 | `POST /api/chat` |
| SSE 流式问答 | `POST /api/chat/stream` |
| 上传知识文档 | `POST /api/documents/upload` |
| 文档列表 | `GET /api/documents` |
| 混合检索 | `POST /api/retrieval` |
| 会话列表 | `GET /api/sessions` |
| 提交反馈 | `POST /api/feedback` |
| 系统配置 | `GET /api/admin/config` |
| 详细健康检查 | `GET /api/admin/health` |
| 进程存活 | `GET /live` |

完整 HTTP 请求和响应格式见 [API 文档](docs/API.md)；进程内 MCP 工具契约见
[MCP 文档](docs/MCP.md)。

## 测试

安装开发依赖并运行 pytest 单元测试（本地推理 profile，含 torch；API-only 测试用
`--extra api-only` 替代 `--extra local-models`）：

```bash
uv sync --frozen --extra dev --extra local-models
uv run --frozen pytest
```

启动后端后，可以运行独立 API 和全链路测试：

```bash
uv run --frozen python tests/api/test_health.py
uv run --frozen python tests/api/test_chat.py
uv run --frozen python tests/api/test_documents.py
uv run --frozen python tests/api/test_sessions.py
uv run --frozen python tests/api/test_retrieval.py
uv run --frozen python tests/api/test_feedback.py
uv run --frozen python tests/integration/test_system.py
```

验证前端生产构建：

```bash
npm ci
npm run build --workspace web
```

### 并发压测

启动后端并导入知识库后，可以使用内置异步压测脚本测试 SSE 接口：

```bash
uv run --frozen python scripts/load_test.py \
  --mode fast \
  --requests 20 \
  --concurrency 4
```

脚本输出成功率、吞吐量、端到端 P50/P95/P99 延迟和首 Token 延迟（TTFT）。
Thinking 模式可通过 `--mode thinking` 测试。

更多测试说明见 [tests/README.md](tests/README.md)。

### 检索 benchmark 与版本化回归门禁

`scripts/run_benchmark.py` 默认执行三轮真实检索，报告 hit rate、context precision/recall 的
中位数与最差值，并在排除首个冷查询后报告 warm P50/P95。回归门禁读取版本控制中的
`data/benchmark/baselines/`；基线缺失、损坏、数据集/语料摘要、运行参数或 embedding identity
不匹配时均 fail closed，不会自动创建基线。

```bash
# 读取已提交基线并执行门禁
uv run --frozen python scripts/run_benchmark.py \
  --dataset data/benchmark/benchmark_cmrc2018.yaml \
  --top-k 4 --repeats 3 --fail-on-regression

# 只有明确评审本次指标后才更新候选基线；不能与 --fail-on-regression 同时使用
uv run --frozen python scripts/run_benchmark.py \
  --dataset data/benchmark/benchmark_cmrc2018.yaml \
  --top-k 4 --repeats 3 --update-baseline
```

2026-07-16 使用独立进程/库/collection/registry/cache 的 AB 与 BA 配对实验：

| 数据集 | Recall control→workflow | MRR control→workflow | nDCG control→workflow | Warm P95 ms control→workflow | Query forwards control→workflow |
|--------|-------------------------|----------------------|-----------------------|-------------------------------|---------------------------------|
| builtin general | 1.000→1.000 | 1.000→1.000 | 1.000→1.000 | 104.1→66.1 | 56→24 |
| CMRC2018 | 1.000→1.000 | 0.911→0.961 | 0.934→0.971 | 177.5→146.2 | 210→90 |
| HotpotQA | 0.917→0.917 | 1.000→1.000 | 0.915→0.919 | 169.5→141.8 | 210→90 |
| MS MARCO judged | 0.900→0.900 | 0.729→0.758 | 0.773→0.795 | 135.6→105.5 | 140→60 |

AB/BA 的主质量指标完全一致，四个数据集均通过质量损失 `≤0.02`、P95 增幅
`≤25%` 的 promotion gate，因此共享 `RetrievalWorkflow` 默认开启。主模型权重没有变化；
收益来自一次查询表示复用、问题类型计划、authority/reranker 排序保护、filter fail-closed
和一致的证据选择/拒答边界。

MS MARCO 只统计 20 个同时具有有效答案和 selected passage 的可评分查询；旧生成器曾把
`No Answer Present.` 行的最后一条无关 passage 当作 ground truth，现已由生成器与数据契约测试永久拒绝。

完整隔离实验：

```bash
uv run --frozen python scripts/run_paired_benchmark.py \
  --dataset data/benchmark/builtin_general.yaml \
  --dataset data/benchmark/benchmark_cmrc2018.yaml \
  --dataset data/benchmark/benchmark_hotpotqa.yaml \
  --dataset data/benchmark/benchmark_msmarco.yaml \
  --output-dir /tmp/rfo-stage2-abba --top-k 4 --repeats 3

uv run --frozen python scripts/run_frontier_benchmark.py \
  --fixture data/benchmark/frontier_specialized.yaml \
  --repeats 5 --output-json /tmp/rfo-frontier.json
```

多 baseline balanced matrix 与公开 IR adapter：

```bash
uv run --frozen --extra benchmark python scripts/run_benchmark_matrix.py \
  --matrix data/benchmark/retrieval_baselines.yaml \
  --dataset data/benchmark/builtin_general.yaml \
  --dataset data/benchmark/benchmark_cmrc2018.yaml \
  --dataset data/benchmark/benchmark_hotpotqa.yaml \
  --dataset data/benchmark/benchmark_msmarco.yaml \
  --schedule balanced --top-k 4 --repeats 3

uv run --frozen --extra benchmark python scripts/prepare_ir_benchmark.py \
  --dataset nano-beir/scifact \
  --dataset nano-beir/nfcorpus \
  --dataset nano-beir/fiqa \
  --corpus-mode full --offline
```

公开结果显示策略依赖数据分布：SciFact/NFCorpus 更偏好 hybrid，FiQA 更偏好 dense-only，
MIRACL-zh 小样本中 dense 与 hybrid 同质。因此封闭部署应以自己的 private golden 做最终通道校准，
而不是照搬单一公开榜单。完整矩阵与证据等级见
`docs/specs/retrieval-benchmark-expansion/benchmark-results.md`。

ColBERT、RAPTOR、Graph PPR 与 ColPali 的 deterministic microbenchmark 已通过算法闭环，
但使用 synthetic token encoder，不具备真实模型 promotion 资格，仍默认关闭。ColPali 需由操作员
显式执行 `uv run --frozen python scripts/download_colpali.py` 准备本地资产。详见
`docs/specs/retrieval-frontier-optimization/benchmark-results.md`。

## 链路测评与反馈回流（评测飞轮）

系统内置一套**可信评测 + 线上反馈回流**闭环，把 RAG 作为可度量、可持续优化的能力。全部基于本地 Qwen3 自研 LLM-as-judge，零外部依赖、纯内网离线可用。

```
线上  ─► chat ──采样──► InferenceStore(query, 检索上下文, answer, trace_id)
         │                       │
         ▼                       │ 负反馈触发晋升
       feedback ─trace_id─► 候选池 ─curate─► golden.yaml
                                       │
离线                                   ▼ run_eval.py
 golden.yaml ─► EvalRunner ─► EvalScorer ─► 本地 Qwen3 Judge
                 │           (规则 + 可信指标)
                 ▼
          历史记录 ─► 回归对比 ─► CI 门禁
```

### 可信指标（全部本地 Qwen3 判定）

| 指标 | 含义 |
|------|------|
| **Faithfulness（忠实度）** | 答案声明中被检索内容支持的比例（声明抽取 + 逐条 NLI，RAGAS 范式） |
| **Answer Relevancy（答案相关度）** | 原问题与"由答案反推的问题"的 BGE 向量余弦 |
| **Hallucination（幻觉）** | 硬声明（限值/步骤/结论）中缺乏检索支持的比例 |
| **Context Precision/Recall** | 检索片段排序质量 / 参考答案被检索覆盖的比例 |

### 运行离线评测

评测支持**两种离线模式**，均可在内网/断网环境运行：

**模式一：golden 集评测（重新跑管道生成答案再打分）**

需要本地 Ollama + Milvus 在线（用于生成被评测的答案）：

```bash
# 完整评测（含 judge），结果写入 data/eval/runs/
uv run --frozen python scripts/run_eval.py

# 快速规则评测（不调 judge，CI 友好）
uv run --frozen python scripts/run_eval.py --no-judge --concurrency 8

# CI 回归门禁：与基线对比，回归则退出码 1
uv run --frozen python scripts/run_eval.py --tag ci --fail-on-regression
```

**模式二：replay 评测（纯数据，不跑管道、不联网）**

从 JSONL 读取已记录的 `(query, answer, contexts)`，直接喂给 judge 打分。
**完全不调用 harness / 检索 / 生成，零网络依赖**——适合气隙环境、历史推理复盘、judge/prompt 变更后的重评分：

```bash
# judge 开启（需本地 Ollama + 本地 BGE）
uv run --frozen python scripts/replay_eval.py data/eval/replay_samples.jsonl

# 纯规则模式（连 LLM 都不需要，任何环境可跑）
uv run --frozen python scripts/replay_eval.py data/eval/replay_samples.jsonl --no-judge

# 回归门禁
uv run --frozen python scripts/replay_eval.py data/eval/replay_samples.jsonl --fail-on-regression
```

JSONL 格式见 `data/eval/replay_samples.jsonl`，每行一条 `{id, query, answer, contexts, reference_answer, intent}`。

评测数据集外置于 `data/eval/golden.yaml`，无需改代码即可增删用例。

### 离线性声明

整套自测评机制设计为零外部网络依赖（`EMBEDDING_PROVIDER=local`；API-only 部署下 embedding 走 DashScope，见 §API-only 部署）：

| 组件 | 离线方式 |
|------|---------|
| LLM judge | 本地 Ollama Qwen3（`OPENAI_BASE_URL` 默认 `http://localhost:11434/v1`） |
| Embedding | 本地 BGE（优先从 `EMBEDDING_MODEL_PATH` 加载，路径存在即不联网） |
| 存储 | SQLite（judge 缓存、inference、候选池全为本地文件） |
| replay 评测 | 纯数据，不跑管道，不联网 |
| 优雅降级 | LLM 不可达时，judge 熔断降级为规则评分（NLI 指标返回"未判定"而非误报为 0） |

### 候选标注工作台

用户点赞踩/纠正/标记的负反馈会自动把对应推理晋升到候选池：

```bash
uv run --frozen python scripts/curate_golden.py --list          # 查看待标注候选
uv run --frozen python scripts/curate_golden.py --show <id>     # 查看详情
uv run --frozen python scripts/curate_golden.py --promote <id>  # 晋升为 golden（纠正的 corrected_answer 直接成为参考答案）
uv run --frozen python scripts/curate_golden.py --misses        # 查看检索召回不足信号
```

### 配置

```dotenv
# 线上推理日志采样率（0.1 = 10%）；降级/低置信/强制检索的请求必定采样
EVAL_SAMPLE_RATE=0.1
```

### Admin API

- `GET /api/admin/eval/runs` — 评测历史
- `GET /api/admin/eval/runs/{run_id}` — 单次评测详情
- `GET /api/admin/eval/candidates` — 待标注候选池
- `GET /api/admin/inferences` — 采样推理列表
- `GET /api/admin/inferences/{trace_id}` — 单条推理（含检索上下文 + 答案）
- `GET /api/admin/retrieval-misses` — 检索召回不足信号

更多评测闭环细节见本节、[评测闭环规格](docs/specs/eval-closure-metric-accuracy/)
以及 [系统技术报告](docs/technical_report.md)。

## 项目结构

```text
agent/
├── harness/       LangGraph 编排、计划、生命周期与可观测性
├── skills/        Agent、检索、评分、重写和生成技能（目录式布局）
├── context/       Agent 共享状态与会话上下文
├── mcp/           MCP 服务端、客户端与检索工具
├── eval/          可信评测与反馈回流飞轮（judge/scorer/runner/dataset/history/...）
├── guardrails/    输入输出安全检查（input/output/grounding/pii）
├── feedback/      用户反馈与升级处理
├── memory/        长期记忆提取与存储
└── metrics/       指标与成本

api/               FastAPI 应用、路由（chat/documents/sessions/admin/feedback/retrieval）与中间件
core/              检索工作流（planner/corrective/selector/frontier）、意图、会话、降级、tracing
documents/         文档解析（markdown/pdf/ocr）、注册表、Milvus、parent/graph store
models/            LLM 与 Embedding 配置
web/               Vue 3 + Vite + TS + Pinia 前端
tests/             单元、进程内 E2E、性能、前端 E2E、API 与全链路测试
docs/              HTTP API、MCP、技术报告、specs/（需求-设计-评审）与评审模板
scripts/           eval/replay、paired/matrix/public benchmark、负载测试与本地模型准备
utils/             log_utils / env_utils / print_utils / think_tag_utils
data/              运行时 SQLite、Milvus Lite、RAPTOR/视觉索引与 benchmark/eval 数据
```

> 更新于本目录的树以实际目录为准；详细的模块契约、降级矩阵、不变量见
> [AGENTS.md](AGENTS.md) 及子目录 `agent/AGENTS.md`、`core/AGENTS.md`、`web/AGENTS.md`、`tests/AGENTS.md`。

## 数据与运行时文件

以下内容会在本地运行时生成，并已通过 `.gitignore` 排除：

- `data/`：会话、反馈、文档注册、评测、RAPTOR、视觉索引及文档资产
- `milvus_data.db*`：Milvus Lite 数据库与锁文件
- `models/local_models/`：本地 Embedding 模型
- `web/dist/`：前端生产构建产物
- `logs/`、`.pids/`：运行日志与进程文件

## 常见问题

### Ollama 连接失败

确认 Ollama 正在运行，模型已经下载：

```bash
curl http://localhost:11434/api/tags
ollama list
```

### 首次启动较慢

本地推理 profile 首次运行需要准备 BGE-M3、Reranker 和 Ollama 权重，完整资产为数 GB；
`scripts/download_bge_m3.py` 还会验证 sparse/ColBERT 训练头。API-only profile 不下载这些
本地模型。后续启动会复用本地快照和索引。

### Redis 不可用

Redis 是可选组件。连接失败时，系统会自动降级到 `data/sessions.db`。

### 修改了反代前缀但前端资源仍然 404

`VITE_BASE_PATH` 是构建时变量。修改后必须重新构建；同时设置 `APP_ROOT_PATH` 并使用 stripping
proxy 模板。三者的完整契约见 [API-only Docker deployment](docs/deployment/api-only-docker.md)。

## 更多文档

- [API 接口文档](docs/API.md)
- [MCP 工具契约](docs/MCP.md)
- [系统技术报告](docs/technical_report.md)
- [部署总览](docs/deployment/README.md)
- [WSL 完整部署（本地模型、systemd、localhost）](docs/deployment/WSL_DEPLOYMENT.md)
- [开发部署](docs/deployment/development.md)
- [裸机生产部署](docs/deployment/bare-metal.md)
- [API-only Docker 部署](docs/deployment/api-only-docker.md)
- [离线与气隙部署](docs/deployment/offline.md)
- [生产运维手册](docs/deployment/operations.md)
- [Agent Skills 说明](agent/skills/README.md)
- [测试说明](tests/README.md)
