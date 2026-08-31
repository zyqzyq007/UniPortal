# CI Index Routing — Design v2.3

## 1. Root Cause and Architecture

`uv sync --frozen` 消费 `uv.lock` 的完整 artifact URL，default-index override 无法改写它。CI 采用：

```text
canonical uv.lock
   ├─ uv export --frozen --only-group ci-build ──► hashed build allowlist
   │                                                │ sync into explicit target
   └─ uv export --frozen <profile> --group ci-build ─► hashed runtime closure
                                                    │ sync --no-build-isolation
validated unique index + sanitized env ─────────────┤
                                                    ▼
uv run --frozen --no-sync ──► tests / uvicorn
```

新增 `scripts/sync_locked_deps.sh <dev|api-only>` 作为两个 workflow 与 Docker 的单一安装入口。
canonical lock 保持国内 URL；临时 requirements 不含 host，安装阶段再选择目标 index。

## 2. Dependency and Lock Placement

所有 manifest 变更使用 uv 0.11.8；`--frozen` 本身即不重锁/不同步，最后只重锁一次：

```text
uv remove --frozen flagembedding
uv add --frozen --optional local-models 'flagembedding>=1.4.0'
uv add --frozen --group ci-build 'setuptools==81.0.0'
uv lock --offline
```

该顺序避免中间状态把 FlagEmbedding 子树从 lock 删除后再选取新版本。实施前后建立 package 的
`(name, version, source, sdist hash, wheel hashes)` 映射；只允许 `rag-project` 的 base/optional/group
wiring 变化。若单次重锁仍产生其他变化，使用旧 lock 的全量 exact constraints 重锁，不接受漂移。

FlagEmbedding 1.4.0 自身直接依赖 torch/transformers；移入 `local-models` 才能让 base/dev/
API-only 真正 torch-less。installer 显式把 `ci-build` 加入其精确 runtime export，并先单独预装
hashed `setuptools==81.0.0`；随后关闭 build isolation。当前 sdist-only `jieba`/`langdetect` 使用
该 backend；若未来 package 需要 wheel/setuptools-scm/hatchling 等未列工具，构建直接失败，必须先
经 spec/lock review 扩充 allowlist，不能隐式解析。

## 3. Installer Contract

| Input | Default | Contract |
|---|---|---|
| positional profile | required | only `dev` / `api-only` |
| `UV_DEFAULT_INDEX` | Aliyun simple URL | validated target artifact index |
| `UV_PROJECT_ENVIRONMENT` | `.venv` | target venv path |
| `UV_PYTHON` | `3.13` | interpreter used to create target venv only |
| `UV_SYNC_TIMEOUT_SECONDS` | `0` | non-negative integer; CI=300, Docker=600 |
| `UV_ALLOW_INSECURE_LOOPBACK_INDEX` | unset | tests only; permits HTTP loopback |

profile mapping：

| profile | runtime export args | forbidden closure |
|---|---|---|
| dev | `--extra dev` | FlagEmbedding/torch/ST/transformers/CUDA/NVIDIA |
| api-only | `--no-dev --extra api-only` | same |

脚本必须：

1. 先验证 profile、timeout 与 index。index 使用标准 URL parser；拒绝 userinfo/query/fragment；生产
   只允许 HTTPS，测试 opt-in 仅允许 loopback HTTP。
2. 以 `mktemp` 创建 runtime/build 两个文件并 trap 删除；build 使用 `--only-group ci-build`，
   runtime 使用目标 profile 并显式 `--group ci-build`；均 frozen 且
   `--no-emit-project --no-header --no-annotate`。
3. 拒绝 runtime/build 文件中的 `--index-url`、`--extra-index-url`、`--find-links`、VCS/direct
   URL；在创建 venv 前拒绝 runtime closure 的本地模型栈。
4. `uv venv "$UV_PROJECT_ENVIRONMENT" --python "$UV_PYTHON"`，然后显式设置
   `venv_python="$UV_PROJECT_ENVIRONMENT/bin/python"`；不得依赖 `UV_PROJECT_ENVIRONMENT` 替
   `uv pip` 选解释器。
5. sync 子进程清除 `UV_INDEX`、`UV_DEFAULT_INDEX`、`UV_INDEX_URL`、`UV_EXTRA_INDEX_URL`、
   `UV_FIND_LINKS`、`UV_NO_INDEX`、`UV_INDEX_STRATEGY`、`UV_KEYRING_PROVIDER`、
   `UV_INSECURE_HOST` 及对应 `PIP_*` 输入；CLI 传唯一 `--default-index` 与
   `--index-strategy first-index`。
6. 在同一总预算内先 hashed sync `<build-file>` 到显式 target，再 hashed sync `<runtime-file>`，
   第二次必须 `--no-build-isolation`。runtime 文件也包含 `ci-build`，所以预装 setuptools 不会被
   exact sync 删除。两次均使用同一 sanitized unique index、`--python`、`--strict --no-config`；
   300/600 秒总 timeout 使用 TERM + 10 秒 KILL，保留退出码并输出
   `dependency_sync_seconds=<n>`，不回显 index。

`--no-config` 忽略文件配置，环境清理关闭更高优先级源，显式 `--python` 关闭错误 venv 选择；
三者缺一不可。

## 4. Toolchain, Workflow, and Docker

- 两个 `setup-uv@v6` 显式 `version: "0.11.8"`；Docker 使用
  `ghcr.io/astral-sh/uv:0.11.8`，三处由单测保证一致并输出 `uv --version`。
- `.github/workflows/tests.yml` 的 `test` job：20 分钟；官方 PyPI；300 秒 sync；脚本 `dev`；
  job 内 `uv run --frozen --no-sync`。
- hosted cold-cache dispatch 默认 `run_backend_nightly=false`；只有显式输入为 true 时才请求
  self-hosted real-backend job，避免性能采样 workflow 永久排队。
- `.github/workflows/e2e-ui.yml`：同一 dev contract、20 分钟与 Playwright 全套；`if: always()` 上传
  screenshots/test-results，artifact 名带 run ID/attempt、保留 14 天；失败 trace 使用
  `retain-on-failure`。
- 两个 Python workflow 的 `workflow_dispatch` 增 `cold-cache` boolean；cold 模式关闭 setup-uv
  cache 并设置 `UV_NO_CACHE=1`。正常 push/PR 保留 warm cache。
- `.github/workflows/docker-api-only.yml`：30 分钟；官方 PyPI build arg；600 秒 sync；不设置正向
  `paths` 白名单（Docker `COPY . .` 的运行时代码闭包过宽，所有 main/PR 变更均执行门禁）；dispatch
  `cold-cache=true` 时 build action `no-cache: true`。
- Docker app stage 在依赖 RUN 前声明默认阿里云的 `ARG UV_DEFAULT_INDEX` 与 sync budget，显式
  `bash` 调 installer；ARG 不进入 ENV；CMD 使用 `uv run --frozen --no-sync`。
- Docker build 前记录 epoch，build 后计算 elapsed；`>1200s` 的成功 build 仍由后置 gate 置红，
  30 分钟 job timeout 是最终硬停止。依赖层时间取 installer 的结构化日志，不用完整 step 冒充。
- self-hosted backend-nightly 保持 local-models/canonical source；不属于 hosted routing。

## 5. Failure, State, and Rollback

本变更不写 `shared_state`、messages、数据库或 API schema，不触及应用热路径评分/降级语义。

| Failure | Detection | Result |
|---|---|---|
| local-model stack leaked | export guard + closure test | before-download failure |
| direct/build hash wrong | two hashed syncs + bad-hash tests | no hash bypass |
| undeclared build dependency | preinstalled allowlist + `--no-build-isolation` | fail without package request |
| wrong/hostile index | URL validation + env scrub + dual-server canary | hostile host gets zero requests |
| wrong venv | explicit `--python` + decoy/absolute-venv test | decoy unchanged |
| image package-list probe fails | `docker run` 与 grep 分离；probe 非零直接失败 | no false zero-torch success |
| sync hangs | 300/600s TERM→KILL + test | bounded non-zero exit |
| full Docker build slow | 1200s post-build gate + 1800s job bound | regression fails |
| uv semantics drift | 0.11.8 pin consistency test | PR gate fails |

回滚 workflow/Docker/script 可恢复旧路径，但 dependency placement 不应单独回退，否则恢复 API-only
zero-torch Critical。国内紧急构建不传 build arg即可；canonical source 不变。

## 6. Test Matrix and Metrics

| Layer | Cases |
|---|---|
| Unit | actual frozen exports: dev/API-only exclude, local-models retain, ci-build only setuptools; every block hashed/no URL; manifest/lock source; pinned uv/wiring; absolute target + decoy; dual HTTP servers under hostile env; bad runtime/build hash; handcrafted sdist with undeclared backend dependency makes zero package requests; invalid URL; timeout TERM/KILL; Docker 1200s/trigger/package-probe gates; cold dispatch excludes self-hosted by default |
| In-process E2E | new dev installer environment runs existing `tests/e2e/`, proving torch-less closure starts FastAPI and completes mocked RAG |
| UI E2E | new installer runs Playwright；session card 用完整 ID，删除验证 exact response + target/sentinel 双侧不变量；current-run screenshots/test-results 上传 artifact；无 UI baseline change |
| Docker | API-only build; `/app/venv/bin/python` imports FastAPI; image `<4 GB`; no FlagEmbedding/torch/ST/transformers/langchain-huggingface |
| Remote | same commit SHA/workflow/runner label+arch+image version/Python/uv: each workflow obtains at least 3 matching cold samples, resampling when hosted image rolls；hosted physical VM identity may differ；record `ImageOS`/`ImageVersion`；report cold median/max separately；retain one normal warm push sample；parse dependency/full-build seconds；never label small samples P95 |

红绿证据、implementation SHA、run URLs、cold/warm 标识与秒数写入 tracking 后才能关闭 findings。

## 7. Security Impact

- Supply chain：runtime artifact 与预装 build allowlist 均来自 frozen lock/hash；关闭 build
  isolation 阻止未声明构建依赖；uv tool pin；禁止 direct URL 与 unreviewed lock drift。
- Tampering：hostile env 被清理，unique index 固定 `first-index`，双 server 测试证明没有旁路。
- Information disclosure：URL 拒绝 userinfo/query/fragment，脚本不回显 index，ARG 不接受 secret。
- DoS：download 前 closure guard、sync TERM/KILL、job 与 full-build gate 分层限制资源。
- Spoofing/Repudiation/Elevation：不改身份权限；日志记录 uv/cache mode/host class/elapsed 供追溯。
