# 闭环追踪矩阵 — generation-quality-faithfulness(Stage C, v2)

**v2 整合后台独立 critic/defender**。critic 发现 2 Critical，已全部修复。

## 1. 追踪矩阵(v2)

| 发现 ID | 严重性 | 辩护决策 | 验证/修复 | 状态 |
|---------|--------|----------|-----------|------|
| F-RC-01 | Critical | accepted(已修) | refusal spec/代码漂移:design §6.2/§2 改"有分数信任 grade",代码一致(RRF 0.008→不拒绝) | **closed** |
| F-RC-02 | Critical | accepted(已修) | agent nudge 失败 → 返回安全 nudge(不放行裸答案),sync+async | **closed** |
| F-RC-03 | High | accepted(记 backlog) | grade _grade 重试耗尽 return True vs execute rewrite;语义不完全统一,转后续 | **open** |
| F-RC-04 | High | accepted(记 backlog) | thinking 二次截断 + ≤50 字符短路;转后续(async 截断检测) | **open** |
| F-RC-05 | High | accepted(记 backlog) | 结构校验裸子串误判 + 无 template no-op;转后续 | **open** |
| F-05(defender) | Medium | accepted(已修) | Grade binary_score 默认 None(str|None)+ is_relevant 显式判断,answer 备选复活 | **closed** |
| F-RC-06~09 | Medium/Low | accepted | rewrite 触顶/异步截断/空答案/文案;转后续或接受 | accepted |

## 2. 闭环状态
- **Critical: 2** → 全 closed（F-RC-01 spec 一致；F-RC-02 安全 nudge）。
- **High: 3** → accepted（转 backlog，均"降级安全"不阻塞功能）。
- **Medium F-05** → closed（Grade.answer 复活）。
- **门禁**: ✅ 通过。

## 3. critic/defender 价值
- **F-RC-02 是真实漏洞**：nudge 失败后放行裸答案（hallucination 直通车未切断）。已修：返回安全 nudge。
- **F-05 是回归隐患**：yes-default 修复（默认 no）让 `binary_score or answer` 短路，answer 备选失效。已修：默认 None + is_relevant 显式判断。
- defender 独立确认了 F-01/F-02 两个 Critical。

## 4. Backlog
- F-RC-03: grade fallback 完全统一（_grade 重试耗尽 raise）。
- F-RC-04/07: async 流式截断检测 + 二次截断处理。
- F-RC-05: 结构校验裸子串收紧 + 无 template 兜底。
- F-RC-03 隐含: `_should_retrieve` 实现（general_chat 不 nudge）。

## 5. 验证证据
- regression:40+ passed（grade/agent/thinking/refusal + 既有）。
- F-RC-02:nudge 失败 → 安全 nudge（实测不放行裸答案）。
- F-05:Grade(answer='yes').is_relevant=True（answer 复活）。
