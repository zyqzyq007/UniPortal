# 闭环追踪矩阵 — retrieval-stack-bm25-reranker(Stage A, v2)

**v2 整合后台独立 critic/defender**(独立上下文发现了我同步评审的盲点,已诚实采纳)。

## 1. 追踪矩阵(v2)

| 发现 ID | 严重性 | 辩护决策 | 验证/修复 | 状态 |
|---------|--------|----------|-----------|------|
| F-RS-001 | Critical | accepted(已修) | `.env.example` + `deploy.sh` 模板更新为 bge + batch 4 | **closed** |
| F-RS-002 | Critical | accepted(可观测性闭合) | `status()` 新增 `degraded` 标志;粘性 by-design + 运维 runbook | **closed** |
| F-RS-003 | High | accepted(文档) | design §11 env override=False 告知运维 | **closed** |
| F-RS-004 | High | accepted(现状) | CJK 基本区实测覆盖航空术语;扩展区记为边界 | **closed** |
| F-RS-005 | High | defended | jieba 航空术语实测正确(起落架/液压泵整词),无需自定义词典 | **closed** |
| F-RS-006 | High | accepted(已修) | 新增混合层测试:sparse 中文非空 + dense-only fallback | **closed** |
| PF-4a | High | accepted(已修) | 模型体积 568MB→**2.1GB FP32**(568M 参数)文档修正 | **closed** |
| F-RS-007~012 | Medium/Low | accepted/defended | 范围外或现状合理 | **accepted** |

## 2. 闭环状态
- **Critical: 2(F-RS-001/002)** → **全 closed**。
- **High: 5(F-RS-003~006, PF-4a)** → **全 closed**。
- **合并门禁**: ✅ 通过。

## 3. 关键教训(记录)
- **后台独立 critic 发现了同步评审的部署盲点**(F-RS-001 模板漂移)。我同步评审只改了
  gitignored 的 `.env`,漏了版本控制的模板——新部署会回退英文 reranker。
- **defender 实测发现事实错误**(PF-4a):我把"568M 参数"误当"568MB 体积",实际 2.1GB。
  defender 用 `safetensors` 参数计数 + `du` 反证。诚实接受修正。
- 这印证 Stage 0 的教训:**独立上下文评审 + 实测反证**是发现确认偏误的有效手段。

## 4. 验证证据
- regression test:14/14 passed(含 F-RS-006 混合层断言)。
- 既有检索测试:34 passed(无回归)。
- 模板:`.env.example`/`deploy.sh` 含 bge + batch 4。
- status() degraded:加载失败后 `degraded=True`。
- 模型体积:safetensors 2.1GB(568M 参数)。
