# Defender 报告 — recall-quality-hyde-parent-store(Stage B)

**裁决基准**: defender.md 5 步决策树 + 实测证据

## 裁决表

| ID | 严重性 | 决策 | 理由(实测) |
|----|--------|------|------------|
| F-RB-01 | High | **accepted(已修)** | EICAS 故障码正则漏 `E1A02`,实测误判。修正后 FQ01/HYD3→none。这是同步评审该抓的盲点,诚实接受。 |
| F-RB-02 | Medium | **accepted** | expand 默认开是 Stage B 目标。实测 generate budget 2048 token 兜底截断,不无限膨胀。CHANGELOG 标注。 |
| F-RB-03 | Medium | **defended** | LRU 全局 dict 在 async event loop 单线程下无真并发(dict ops 无 await 抢占)。sync threads 场景罕见。可选加锁但收益低。 |
| F-RB-04 | Low | **defended** | batch split 移除换打标可靠性。slice 非热路径。实测语义多样长文本正确切分。 |
| F-RB-05 | Low | **accepted** | corpus 需重新生成。度量时执行。 |

## 实测验证

- **F-RB-01 修正验证**:E1A02/FQ01/HYD3 → none(正确);如何排查 → hyde;振动异常 → multi_query。
- **F-RB-02 budget**:generate max_context_tokens=2048(~6500 字符),单父段 ~2000 字符安全;
  `_apply_context_budget` 按 chunk 边界贪心截断兜底。
- **F-RB-04 切片**:语义多样长文本(80 段航空手册)→ 正确切分 + 同一 parent_id + store 有父段。
- **整体**:63 regression passed(含 19 新增)。

## 净裁决
0 Critical / 1 High(closed)/ Medium accepted/defended。门禁通过。
