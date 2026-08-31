# web/AGENTS.md — 前端专属规范

> 本文件补充根 `AGENTS.md`，仅当工作目录在 `web/` 子树下时由 Agent 加载。
> 技术栈：Vue 3 + Vite + TypeScript + Pinia。

## 1. 目录与产物

```
web/
├── src/                # Vue SPA 源码（stores / views）
├── dist/               # 构建产物（Playwright E2E 与生产静态部署依赖）
├── package.json
├── playwright.config.ts
└── vite.config.ts
```

- **`web/dist` 契约**：Playwright E2E 与生产静态部署都依赖 `web/dist`。改前端后必须 `npm run build` 重新生成。
- 依赖锁文件 `package-lock.json`，禁止 `@latest` 写法。

## 2. 命令（绝对路径、可独立执行）

```bash
# 安装依赖
cd web && npm ci

# 开发
cd web && npm run dev

# 构建（生成 dist/，E2E/部署前置）
cd web && npm run build

# Playwright E2E（需 web/dist + 后端运行）
cd web && npm run build && cd ..
npx playwright test --config=web/playwright.config.ts
```

### 2.1 首跑环境准备（一次性，易踩坑）

- **浏览器 + 系统库**：首次跑 E2E 必须装 chromium 及其系统依赖，否则报
  `error while loading shared libraries: libasound.so.2` 之类缺库错：
  ```bash
  cd web && npx playwright install --with-deps chromium
  ```
  `--with-deps` 会装齐 `libnss3`/`libatk`/`libasound2t64`/`libgbm1` 等全套系统库（需 sudo）。
  CI 由 `.github/workflows/e2e-ui.yml` 自动执行；**本地首跑必须手动执行一次**。
- **`web/dist` 前置**：`web/dist` 被 `.gitignore`（`.gitignore:53`），clone 后不存在。
  后端 SPA catch-all（`api/main.py`）以 `web/dist/index.html` 存在为门控——缺失则 `/` 只返回 API-info JSON，
  浏览器 E2E 全部失败。**改前端后、跑 E2E 前**必须 `cd web && npm run build` 重新生成。

### 2.2 本地手动验证流程（spec 之外的快速验证）

需要快速眼见为实（不跑完整 spec 矩阵）时，用 faked 后端 + 一次性验证脚本，跑完即删：

```bash
# 1) 启动带 fakes 的后端（后台；RAG_E2E_FAKES=1 注入子进程 fake，无 Ollama/Milvus 依赖）
PYTEST_RUN=1 RAG_E2E_FAKES=1 \
  OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama \
  uv run --frozen uvicorn api.main:app --host 127.0.0.1 --port 8765 &

# 2) 健康确认：SPA 在 / 返回 HTML（非 JSON）、/api/admin/health 返回 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/        # 期望 200
curl -s http://127.0.0.1:8765/ | grep -q '<div id="app">' && echo "SPA OK"

# 3) 跑验证脚本（截图落 tests/e2e_ui/screenshots/，详见 §3.3）
cd web && NODE_PATH=$(pwd)/node_modules node <一次性脚本.cjs>
```

- 一次性验证脚本**必须落 `tests/e2e_ui/` 下**（如 `tests/e2e_ui/demo_chat.cjs`），**禁止**散落在 `web/` 根
  （违反根 AGENTS.md §7「测试只进 `tests/`」）。验证用、非回归用——跑完确认后即删，**不进 git**。
- 验证完毕后停后端：`pkill -f "uvicorn api.main"`；清理临时数据：`rm -rf /tmp/e2e_ui_data_*`。


## 3. 前端测试纪律（根 AGENTS.md §7 的前端部分）

- 涉及前端的改动必须给齐 **Playwright E2E**，证明功能在 UI 层完整：chat / SSE 流式 / 文档上传 / 会话。
- **截图是端到端验证的必要手段**：纯 DOM 选择器断言无法覆盖视觉/布局/异步渲染问题。E2E 在每个关键交互节点
  （页面加载、消息渲染、上传完成、流式增量）必须截图。降级/错误态同样必须截图。
- Playwright 脚本放 `tests/e2e_ui/`（不是 `web/` 内），CI 以独立 job 运行（`.github/workflows/e2e-ui.yml`）。
- 前端 E2E 不在默认 `pytest testpaths` 内（需 Node + 构建产物），由 `e2e-ui.yml` 单独驱动。

### 3.1 子进程 fake 注入契约（浏览器 E2E 的根因机制）

浏览器 E2E 经 `webServer` 拉起一个**独立 uvicorn 子进程**，该进程**不在 pytest 内**，因此
`tests/conftest.py` 的进程内 monkeypatch 对它无效。为让浏览器 E2E 确定、不依赖 Ollama/Milvus：

- **`RAG_E2E_FAKES=1`**（由 `playwright.config.ts` 的 webServer 与 `e2e-ui.yml` 注入）触发
  `tests/e2e_ui/_fakes.py` 的 `install()`，在 `api/main.py` 构建应用**之前**替换 harness/LLM/retriever/
  intent/fast_mode 等 getter；`wire_overrides(app)` 在 `app = create_app()` 之后注入会话记忆依赖覆盖。
  两处钩子均以 `RAG_E2E_FAKES` env 门控，**生产路径（env 未置）完全跳过、零行为变化**。
- **`PYTEST_RUN=1` 只跳过 F05 生产配置启动守卫，不注入任何 fake**——禁止把它当作 fake 开关。
- 进程内 `tests/e2e/`（TestClient）与浏览器 `tests/e2e_ui/`（uvicorn 子进程）共享同一套 fake 实现语义
  （`FakeLLM`/`_FakeHarness`/`_FakeRetriever`/`_FakeIntentClassifier`/`_FakeSessionMemory`），但代码各自
  独立（conftest 用 monkeypatch，`_fakes.py` 用 setattr），**改一处必须同步另一处**。

### 3.2 hermetic 约定（测试隔离）

- 浏览器 E2E 子进程的**所有**持久化路径必须重定向到 `tests/e2e_ui/_fakes.py` 创建的进程级临时目录
  （`tmp/e2e_ui_data_*`，进程退出 `atexit` 清理）：inferences / eval / judge_cache / agent_memory /
  parent_store / documents / checkpoints / milvus + 上传临时目录。
- **禁止**写真实 `./data/`、`./milvus_data.db`、`./data/sessions.db`。会话记忆用 `app.dependency_overrides`
  覆盖为内存 fake，真实 `_SQLiteStore` 在该路径不构造。
- 新增持久化落盘时，必须在 `_fakes.py:_redirect_paths()` 与 `tests/conftest.py:tmp_data_dir` **两处**同步
  重定向，否则会污染真实库（违反根 AGENTS.md §10 持久化契约）。

### 3.3 截图与目录规范

`tests/e2e_ui/` 下截图分**两类语义**，目录与 git 策略不同：

| 类型 | 用途 | 落盘目录 | git |
|---|---|---|---|
| **基线快照** | `expect(page).toHaveScreenshot()` 的回归对比基线 | `tests/e2e_ui/<spec>.spec.ts-snapshots/` | **必须进 git**（CI 对比依赖） |
| **过程截图** | `page.screenshot()` 落盘存档 / 演示验证 | `tests/e2e_ui/screenshots/<area>/<name>.png` | **不进 git**（产出物，体积大） |

- **过程截图落盘**：经共享 helper `tests/e2e_ui/helpers.ts` 的 `screenshot(page, area, name)`，自动写入
  `tests/e2e_ui/screenshots/<area>/<name>.png`（`fullPage: true`）。
- **`screenshots/` 与 `test-results/` 进 `.gitignore`**：二者都是运行产出物（过程截图 + Playwright 失败现场），
  体积大且与平台相关，禁止入库。基线快照目录（`*-snapshots/`）相反，必须入库。
- **UI 有意变更**：先 `npx playwright test --update-snapshots` 更新基线，再 commit；PR 单列 screenshot diff。
- **降级/错误态**也必须截图（验证降级路径在 UI 层可见），不能只截正常态。

### 3.4 `data-testid` 约定（稳健选择器）

- 所有关键交互元素**必须**挂 `data-testid` 属性：导航链接、输入框、发送/模式切换/新对话按钮、
  快捷问题、消息容器、来源面板、上传区/文件 input/文档卡片/删除按钮、会话卡片/新建/刷新/删除、
  admin 各分区/熔断重置/降级模式按钮、toast。
- E2E 选择器**以 `page.getByTestId(...)` 为先**；中文文本/class 仅作辅助（文本易变、class 易重构）。
- 动态列表项用稳定容器 testid + `.first()/.last()`/`filter`，**不依赖** `v-for` 的 `:key="index"` 顺序。

### 3.5 流式 fake 契约

- `_FakeHarness.astream`（进程内 conftest 与 `_fakes.py` 两处）必须产出**真实 LangGraph stream 形态**的
  `("updates", {"<node>": {...}})` 与 `("custom", {"type":"token","content":...})` 元组，**禁止**吐裸
  `{"messages":[...]}` dict——否则 `POST /api/chat/stream` 的 RAG 分支无法匹配节点、`full_response` 为空
  （这正是曾被 `test_e2e_coverage.py` xfail 钉住的根因，现已修复）。

### 3.6 覆盖清单对齐（诚实标注）

- 当前已覆盖：chat（welcome/identity/deep/fast/SSE/sources）、**feedback（thumbs up/down/correction）**、
  documents（upload/search/delete）、sessions（list/new/open/delete）、admin（sections/degradation switch）。
- **反馈闭环**：ChatView 每条 AI 回答下有 👍/👎/纠错按钮，提交 `POST /api/feedback` 携带
  `trace_id`+`message_id`（后端在 chat 响应 metadata 与流式 `done` payload 中暴露），负反馈触发
  eval 飞轮（`on_negative_feedback` → 推理进候选池 → judge 重评）。流式路径也已补 `_capture()`，
  使流式回答进入 inference store 可被重评。E2E 覆盖三种反馈类型。
- spec 文件头**禁止**谎称覆盖未实现的功能；功能新增/移除时同步更新本清单。

## 4. 约定

- 组件命名 PascalCase，组合式 API（`<script setup lang="ts">`）。
- 状态管理用 Pinia store；跨组件共享状态禁止用全局变量。
- **HTTP 调用**：各 view/store 直接用 `fetch()`（非 axios 封装）；SSE 流式解析集中在
  `stores/chat.ts`。新增端点调用时，在对应 store/view 内就近写 `fetch`，保持与现状一致；
  复杂的重复请求逻辑（鉴权头、错误处理）可抽 helper，但**不要**重新引入一个未被使用的全局
  HTTP 客户端抽象（曾经存在过的 `src/api/index.ts` axios 客户端零调用方，已删除）。
- 代码无 emoji（与后端约定一致）。
- 遇到后端 API 变更，同步更新调用处的请求/响应类型与对应 E2E 用例。
