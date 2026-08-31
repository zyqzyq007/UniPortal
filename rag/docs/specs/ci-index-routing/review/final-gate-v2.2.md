# Final Design Gate — CI Index Routing v2.2

## v2.1 Residual Findings

- **N-06 High**：`--build-constraints` 不是 allowlist，不能阻止未列 build dependency 被解析。
  v2.2 改为 hashed `ci-build` 预装 + runtime `--no-build-isolation`，并让 runtime closure 保留该
  group；未列工具直接失败且不得收到网络请求。
- **N-08 High**：GitHub-hosted dispatch 无法复用同一物理 runner。v2.2 改为同一 SHA、workflow、
  runner label/architecture/image version、Python、uv、cache mode；记录 image metadata，变化时重采样。

## Gate Status

v1 F-01..F-03、v2 N-01..N-07 与 N-08 均已有可执行设计缓解。最终独立 critic 与 defender
均确认 v2.2 无残余 Critical/High，**可进入红测试**。findings 仍须在实现、永久回归测试与远端
证据齐全后才能 closed。
