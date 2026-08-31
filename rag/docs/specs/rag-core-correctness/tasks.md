# RAG Core Correctness — Tasks

## Spec and review

- [x] 编写 requirements/design/tasks 三段式规格。
- [x] 并行 critic/defender 评审并归档 `review/{critic,defender,tracking}.md`。
- [x] 解决或接受全部 Critical/High findings（v4 终审 F-12..F-16 已闭环）。

## Red tests

- [x] [REQ-RCC-001/002] 添加 Markdown 多级标题升降、跳级与正文归属失败测试。
- [x] [REQ-RCC-003..006] 添加 evidence 序列化、checkpoint、预算裁剪及旧消息回退测试。
- [x] [REQ-RCC-006A/006B] 添加 fast 三入口 kept-source 与恶意 evidence delimiter golden。
- [x] [REQ-RCC-006C] 添加 binary/per-doc grade sync+async 间接注入 golden。
- [x] [REQ-RCC-007..009] 添加 raw logit、缺失信号与全降级测试。
- [x] [REQ-RCC-010..012] 添加 embedding 默认、Milvus URI 优先级与安全指纹测试。
- [x] [REQ-RCC-012A] 添加 legacy 512/no-sparse collection 阻断与新 collection 迁移测试。
- [x] [REQ-RCC-012A] 添加 BGE-small/512→DashScope-v3/512 同维异模型阻断测试。
- [x] [REQ-RCC-013/014] 添加 graph schema migration、跨 source 共存与独立删除测试。
- [x] [REQ-RCC-017] 添加 benchmark 正常/异常资源关闭与延迟聚合失败测试。
- [x] [REQ-RCC-009A/009B] 添加 mixed signal、布尔 logit 与 nullable/零分来源失败测试。
- [x] [REQ-RCC-017] 添加 benchmark 三轮默认、质量 median/worst 与最差值门禁失败测试。
- [x] [REQ-RCC-003] 添加正/负超界整数 sanitizer 与 sync/async strict checkpoint 失败测试。
- [x] [REQ-RCC-018] 添加同 thread 两轮 request-state 隔离及四个 graph 入口对称测试。
- [x] [REQ-RCC-010A] 添加显式非默认模型不复用 BGE-M3 path/sparse、未知维度 fail-fast 与 actual-source fingerprint 测试。
- [x] [REQ-RCC-017A] 添加 tracked baseline 缺失、schema/config 错配与非法指标 fail-closed 测试。
- [x] [REQ-RCC-003A] 添加 caller evidence 嵌套 object/Path/循环/越界整数的请求边界与 strict saver 回归测试。
- [x] [REQ-RCC-009B] 添加真实 `1.0` 显示 `100.0%`、`null` 不显示的 Playwright 回归。

## Implementation

- [x] [REQ-RCC-001/002] 用 heading stack 修复 Markdown 层级解析。
- [x] [REQ-RCC-003..006] 新增 structured evidence 并接入 retrieve/generate，保留兼容文本。
- [x] [REQ-RCC-006A/006B] fast 三入口复用 evidence packer，并升级 prompt 定界与 SHA/golden。
- [x] [REQ-RCC-006C] binary/per-doc grade 复用安全 evidence renderer 与 prompt 单源。
- [x] [REQ-RCC-007..009] 统一 sigmoid 与缺失信号融合语义。
- [x] [REQ-RCC-010..012] 统一 embedding/Milvus 默认值并增加安全配置指纹。
- [x] [REQ-RCC-012A] 实现 schema compatibility gate 与离线新 collection 迁移命令。
- [x] [REQ-RCC-013/014] 升级 Graph relation 复合主键、事务迁移及 v1 备份恢复。
- [x] [REQ-RCC-017] 让 benchmark 有限退出并输出 warm P50/P95。
- [x] [REQ-RCC-009A/009B] 统一 finite raw-logit 与 REST/UI nullable score 语义。
- [x] [REQ-RCC-017] 让 benchmark 原生重复运行并输出 median/worst，门禁使用最差值。
- [x] [REQ-RCC-003] 限制 evidence 整数为 strict-msgpack 可表示范围并传播 degraded。
- [x] [REQ-RCC-018] 在 harness 四入口统一重置请求级 `shared_state`。
- [x] [REQ-RCC-010A] 收敛 embedding model/source/dimension/sparse 配置并按实际加载源登记。
- [x] [REQ-RCC-017A] 迁移并校验版本控制中的 benchmark baseline，门禁缺失时失败。
- [x] [REQ-RCC-003A] 在 producer/consumer 与 harness checkpoint 边界复用 evidence 规范化契约。
- [x] [REQ-RCC-009B] 统一 `[0,1]` 闭区间来源分数 formatter。

## Verification

- [x] 运行新增单元与进程内 E2E，记录本轮红→绿证据。
- [x] 运行 `uv run --frozen ruff check` 与定向测试。
- [x] 运行 unit/e2e/perf（排除真实后端 marker）与三轮隔离真实检索 benchmark。
- [x] 构建前端并运行 Playwright，检查关键功能截图。
- [x] 更新 review tracking、CHANGELOG 与最终命令结果。

## Verification Record

- Red: `/tmp/rcc-final-blockers-red.log`（F-12..F-16 新契约 `13 failed, 40 passed`）；
  `/tmp/rcc-final-ui-score-red.log`（真实 `1.0` 未显示 `100.0%`）；
  `/tmp/rcc-final-playwright-3.log`（并行会话删除全局计数竞态 `1 failed, 18 passed`）；
  `/tmp/rcc-f13-opaque-cache-red.log`（BGE-M3 opaque cache path 误走 dense adapter，`1 failed`）。
- Green targeted: `/tmp/rcc-final-blockers-green.log`（`53 passed`）；
  `/tmp/rcc-final-expanded-targeted-green.log`（`217 passed, 2 skipped`）；会话历史角色顺序
  `/tmp/rcc-final-session-order-green.log`（`1 passed`）；opaque cache 修复
  `/tmp/rcc-f13-opaque-cache-green.log`（`1 passed`）、配置套件 `36 passed`、dispatch `2 passed`。
- Backend: `uv run --frozen pytest tests/unit/ tests/e2e/ tests/perf/ -q` →
  `917 passed, 6 skipped, 7 warnings`（`/tmp/rcc-final-full-matrix-4.log`）。
- Quality: 全仓 `uv run --frozen ruff check .`、`ruff format --check .`、`git diff --check`
  与 `import api.main` 均通过；日志为 `/tmp/rcc-final-{ruff-4,format-4}.log` 与
  `/tmp/rcc-final-import-2.log`。
- Retrieval benchmark: 隔离 Milvus/registry、local BGE-M3/1024/native sparse、reranker on、
  GraphRAG off，均为 3 轮：builtin general hit `100%/100%`、precision `0.250/0.250`、
  recall `1.000/1.000`、warm P50/P95 `74.5/98.7 ms`；CMRC2018 为
  `100%/100%`、`0.250/0.250`、`1.000/1.000`、post-fix warm P50/P95
  `153.5/306.9 ms`；HotpotQA 为 `100%/100%`、`0.458/0.458`、`0.917/0.917`、
  `122.3/168.1 ms`。两份 fresh tracked-baseline regression gate 均通过
  （`/tmp/rcc-final-benchmark-{cmrc,hotpot}-postfix-gate.log`）。
- Frontend: production build 通过（`/tmp/rcc-final-web-build-2.log`）；完整 Playwright
  `19 passed`（`/tmp/rcc-final-playwright-4.log`）；sessions 并行重复 3 轮 `12 passed`
  （`/tmp/rcc-final-sessions-repeat.log`）。关键截图已核验 sources/upload/admin/feedback/session，
  会话历史为 user→assistant。
- Rollback drill: 实现提交 `440092b` 写入含新 evidence 键与 legacy `ToolMessage` 的 checkpoint；
  `origin/main@45d68f0` 读取并继续 invoke，输出 `CURRENT_WRITE_OK` 与
  `ORIGIN_MAIN_READ_AND_CONTINUE_OK`（`/tmp/rcc-f18-*.log`）。
- 非阻断 warnings: `pkg_resources` deprecation、SWIG type deprecation、既有 async
  checkpoint/session SQLite `ResourceWarning`；均未产生测试失败。
