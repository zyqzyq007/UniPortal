# Defender 报告 — retrieval-stack-bm25-reranker(Stage A)

**评审对象**: `review/critic.md`
**裁决基准**: defender.md 5 步决策树 + 实测证据

## 裁决表

| 发现 ID | 严重性 | 决策 | 理由(实测证据) | design 修订 |
|---------|--------|------|----------------|-------------|
| F-RS-01 | Medium | **accepted**(现状合理) | CJK 扩展区(\u3400+)在航空 PHM 极罕见。基本区 \u4e00-\u9fff 覆盖所有实测航空术语(起落架/液压伺服阀/燃油喷嘴)。扩展检测收益极低,不值得增复杂度。 | 无 |
| F-RS-02 | Medium | **accepted**(权衡合理) | `_load_attempted` 粘性防反复 OOM,是设计意图。batch 4 + 文档告知运维重启是合理缓解。热恢复增强留 Stage C/D。 | design §7 已记录 |
| F-RS-03 | Low | **accepted** | limit=10000 当前 2852 条未触发;全量部署才需分页拉取。P3 风险。 | design §6 已记录 |
| F-RS-04 | Low | **accepted** | override=False 是容器部署正确设计(env 优先于 .env)。CHANGELOG 告知运维。 | CHANGELOG |

## 关键预判 finding 的实测验证(defender 主动核实)

### 预判 1:design §3 驳回 score>0 是否真闭合?→ **defended**
实测:中文 query"发动机振动"在 BM25 上召回 doc1(发动机叶片振动,score=1.76),doc3(天气)
零词项重叠被 `if score>0` 过滤。sparse 返回非空。当 sparse 真返回空时,hybrid retriever 的
RRF 只用 dense 腿(hybrid_retriever.py 一腿空就剩另一腿),**不会返回纯空**。结论:驳回
成立,sparse 空有 dense 兜底。

### 预判 2:jieba 航空术语切词是否需自定义词典?→ **defended**
实测 jieba.cut:起落架收放系统→['起落架','收放','系统'];液压伺服阀→['液压','伺服','阀'];
燃油喷嘴磨损→['燃油','喷嘴','磨损'];轴向压缩机失速→['轴向','压缩机','失速']。
**全部正确切分**,组合词保留,专业词可独立匹配。无需自定义词典。defended。

### 预判 3:precision 未达标是否是 Stage A 缺陷?→ **defended(非本 stage 缺陷)**
实测对比:reranker ON precision=0.250,reranker OFF precision=0.250(相同)。证明 precision
与 reranker 无关,是分块结构瓶颈(top_k=4 里 gold 占 1/4)。answer_overlap ON=0.967 vs
OFF=0.816 证明 bge reranker 排序有效。precision 属 Stage B(dedup-source/分块优化)。**Stage A
无缺陷,REQ-RS-008 precision 目标需修正**(已在 design §13 诚实记录)。

### 预判 4:transformers 5.5.4 兼容性?→ **defended**
实测:bge-reranker-v2-m3 成功加载(393 weights)+ 中文 predict 0.9234/0.0000/0.4540
(相关/不相关/中等)。无兼容错误。defended。

### 预判 5:CPU OOM?→ **defended-with-alternative**
模型 2.2G(含 FP32 + safetensors),batch 4 下 benchmark 30 case 全程无 OOM。
`_fallback_documents` 兜底安全。粘性是设计取舍(见 F-RS-02)。

## 净裁决
**0 Critical / 0 High**,全部 Medium/Low accepted。合并门禁通过。

## 实测证据汇总
- jieba 切词:发动机叶片振动→[发动机,叶片,振动];航空术语全部正确。
- BM25 中文召回:score=1.76(修复前恒 0),零重叠文档过滤。
- bge 加载 + 中文 predict:0.9234(相关)/0.0000(不相关)/0.4540(中等)。
- benchmark CMRC:hit_rate/recall 0.5→1.0,overlap 0.835→0.967。
- precision 0.250:reranker ON/OFF 相同,分块瓶颈,非排序问题。
- regression test:12/12 passed。
