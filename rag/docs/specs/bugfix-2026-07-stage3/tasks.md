# Stage 3 Tasks — DoS Hardening & Low Sweep

- [ ] **T1** [REQ-S4] B9 red：`?limit=1e6` → 422
- [ ] **T2** [REQ-S4] B9 fix：各处 limit 加 Query(le=)
- [ ] **T3** [REQ-S5] B10 red：超大上传 → 413
- [ ] **T4** [REQ-S5] B10 fix：MAX_UPLOAD_BYTES + Content-Length/读后兜底
- [ ] **T5** [REQ-C6] B11 red：裸文件名 store 不崩
- [ ] **T6** [REQ-C6] B11 fix：两处 `or "."`
- [ ] **T7** [REQ-C7] B12 red+fix：rationale 分母、graph degraded、feedback 单例锁
- [ ] **T8** 全量矩阵 + Playwright + ruff + CHANGELOG + commit
