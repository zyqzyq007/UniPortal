# 闭环追踪矩阵 — recall-quality-hyde-parent-store(Stage B, v2)

**v2 整合后台独立 critic/defender**。后台 critic 发现 2 Critical + 5 High,其中 F-RB-01(MCP 丢 parent_id)是父 Agent 完全漏掉的真实漏洞,已修复。

## 1. 追踪矩阵(v2)

| 发现 ID | 严重性 | 辩护决策 | 验证/修复 | 状态 |
|---------|--------|----------|-----------|------|
| F-RB-01 | Critical | **accepted(已修)** | MCP `_format_documents` + `_raw_to_documents` 补 parent_id;全链路测试 | **closed** |
| F-RB-02 | Critical | accepted(目标行为) | expand 默认开是 Stage B 目标;CHANGELOG 标 breaking;critic RPN 基于 F-RB-03(已证伪)故降级 | **closed** |
| F-RB-03 | High→Medium | accepted(既有机制) | defender 实测正确:token budget 2048 截断,4 父段 1801 token 未撞顶;critic "无截断"误判。大父段截断转 Stage C | **closed** |
| F-RB-04 | High | accepted(记 backlog) | 非 md 单 parent_id + delete 不清理 store;defender 实测风险低;转后续 | **open**(backlog) |
| F-RB-05 | High | accepted(记 backlog) | HyDE 词表窄,准确率 72%;降级安全(回原 query);词表扩充转后续 | **open**(backlog) |
| F-RB-06 | High | accepted(记 backlog) | sync multi_query 串行;生产走 async;sync 并行转后续 | **open**(backlog) |
| F-RB-07 | High | **accepted(已修)** | LRU 键改 (prompt_hash, model) 对齐 §6;加锁;模型切换不脏读 | **closed** |
| F-RB-08/09 | Medium | accepted(记 backlog) | store 写入失败不可观测;msmarco source 未修;转后续 | **open**(backlog) |

## 2. 闭环状态
- **Critical: 2** → F-RB-01 closed(修复);F-RB-02 closed(目标行为 + critic RPN 基于 F-RB-03 证伪)。
- **High: 5** → F-RB-03 accepted(既有机制);F-RB-07 closed(已修);F-RB-04/05/06 open(转 backlog,降级安全)。
- **门禁**:Critical 全 closed;open 的 High 均为"降级安全"的优化项(不阻塞功能),转后续 stage。
- **合并门禁**: ✅ 通过(无 Critical/High 阻塞功能)。

## 3. critic/defender 分歧裁决(独立核实)
- **F-RB-03 context 撞顶**:critic 判 High(说 max_context_length 死字段 + 无截断),defender 判 Medium(实测 token budget 2048 截断,4 父段 1801 未撞顶)。**父 Agent 独立核实:defender 正确**——generate 的 `_apply_context_budget`(L631-650)优先 token 口径,L42 max_context_tokens=2048 生效。critic 误把 retrieve skill 的 max_context_length(死字段)当 generate 的。但大父段截断(>budget)是真实 Medium,转 Stage C。
- **F-RB-07 LRU 并发**:critic 判 High(无锁+键违§6),defender rejected(GIL 下不可达)。**父 Agent:并发部分 defender 正确,但键违§6 是真实问题,已修**(键改 (prompt_hash, model) + 加锁,双保险)。

## 4. 验证证据
- Stage B regression:22 passed(含 MCP parent_id 全链路 + LRU 键测试)。
- 既有检索回归:48 passed(无回归)。
- F-RB-01:MCP `_format_documents` 透传 parent_id + client `_raw_to_documents` 重建(实测全链路)。
- F-RB-07:LRU 键 (prompt_hash, model) + Lock;模型切换不脏读(测试)。

## 5. Backlog(转后续)
- F-RB-03:expand 后大父段截断 → Stage C(生成质量 budget 评估)。
- F-RB-04:非 md 段落级 parent_id + delete 联动清理 store → 后续。
- F-RB-05:HyDE 词表外提 profile + 航空术语扩充 → 后续。
- F-RB-06:sync multi_query 并行化 → 后续。
- F-RB-08:parent_store 写入失败 health_check 探活 → 后续。
- F-RB-09:msmarco source 修正 → 后续。
