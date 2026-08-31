# Critic 报告 — retrieval-stack-bm25-reranker(Stage A)

**评审对象**: `design.md`(及 requirements.md/tasks.md)
**评审模式**: FMEA(航空 PHM 默认)+ 必查清单
**评审者**: 独立 critic(同步执行 + 实测核实)
**结论**: **设计批准进入编码**(已实现)。0 Critical、0 High、2 Medium、2 Low。诚实记录 precision 未达标(根因在分块,非本 stage 范围)。

---

## 0. praise(防不公平苛责)

- `praise` design §3 驳回「放宽 `if score>0`」的数学论证严谨:score=0 ⟺ 零词项重叠
  (IDF 恒正 + tf=0 项贡献 0),保留会污染 RRF 融合。实测验证:中文 query 召回时
  零重叠文档(d3 天气)被正确过滤,有词项文档 score=1.76。**驳回审查建议是正确的**
  (审查建议本身缺乏数学论证)。
- `praise` §13 度量结果**诚实记录了 precision 未达标(0.250<0.261)**,并精确归因到
  分块瓶颈(reranker ON/OFF precision 相同,证明非排序问题)。这是反护短的体现。
- `praise` jieba 航空术语切词实测优秀(起落架/液压伺服阀/燃油喷嘴磨损 均正确切分),
  无需自定义词典,降低了实现复杂度。

---

## Findings

### F-RS-01 — `suggestion (non-blocking)` CJK 检测范围 `\u4e00-\u9fff` 未覆盖扩展区
- **id**: F-RS-01
- **severity**: **Medium**(边界覆盖,影响极低)
- **location**: `bm25_retriever.py` `_tokenize` 的 `re.search(r"[\u4e00-\u9fff]", token)` + min_token 分离逻辑
- **symptom**: CJK 基本区 `\u4e00-\u9fff`(20992 字)覆盖绝大多数中文。但 CJK 扩展 A 区
  `\u3400-\u4dbf`、扩展 B+ `\U00020000+`(罕见古籍字)不在内。航空 PHM 术语基本都在基本区,
  但若有罕见字符(如某些机型代号)会被误判为非中文,用 `min_token_length_en=2` 过滤。
- **impact**: 极低。航空 PHM 手册用字集中在常用字,扩展区罕见。
- **recommendation**: 可选扩展为 `[\u3400-\u9fff\uf900-\ufaff]`(含扩展 A + 兼容表意),但
  收益极低。**接受现状**,记录为已知边界。
- **status**: accepted(影响极低)

### F-RS-02 — `suggestion (non-blocking)` reranker `_load_attempted` 粘性是隐藏单点
- **id**: F-RS-02
- **severity**: **Medium**(运维:OOM 后需重启,batch 调整不可热生效)
- **location**: `reranker.py:96,113`(`_load_attempted` 粘性)+ design §7
- **symptom**: bge-v2-m3 OOM 后 `_load_attempted=True` 锁定,进程内永不重试,所有后续请求走
  `_fallback_documents`(RRF 顺序,无精排)。运维降 batch 后需重启进程才能重新加载。
- **impact**: bge CPU OOM 是真实风险(2.2G 模型 vs ms-marco 90MB)。batch 降到 4 缓解但不
  保证。粘性设计本意是"避免反复 OOM",但牺牲了热恢复。
- **recommendation**: 接受现状(batch 4 + 文档告知运维重启)。可选增强:加 `RERANKER_RETRY`
  env 或 _load_attempted TTL,但属 Stage C/D 运维优化范围。**accepted**。
- **status**: accepted

### F-RS-03 — `nitpick` BM25 bootstrap `limit=10000` 截断风险
- **id**: F-RS-03
- **severity**: **Low**(数据量相关)
- **location**: `hybrid_retriever.py:184`(`limit=10000`)
- **symptom**: 索引重建从 Milvus 拉 10000 条灌 BM25。航空手册全量入库 >1 万会截断,部分
  文档不进 BM25 索引(sparse 召回不到)。
- **impact**: 当前 2852 条未触发;全量部署可能触发。
- **recommendation**: 记录为 P3 风险,后续 stage 可改成分页拉取。**accepted**(非本 stage)。
- **status**: accepted

### F-RS-04 — `nitpick` .env 的 shell 环境变量覆盖(load_dotenv override=False)
- **id**: F-RS-04
- **severity**: **Low**(运维陷阱)
- **location**: `env_utils.py:11` `load_dotenv(override=False)` + `.env` reranker 配置
- **symptom**: 显式 shell 环境变量优先于 .env(override=False)。本 stage 改了 .env 的
  RERANKER_MODEL,但若部署环境有旧的 RERANKER_* env(如容器编排注入),会覆盖 .env 的新值,
  导致仍用旧英文模型。
- **impact**: 运维需知:改 .env 后若有外部 env 注入,需同步更新。
- **recommendation**: 文档告知(CHANGELOG)。override=False 是合理设计(容器 env 优先),
  不改。**accepted**。
- **status**: accepted

---

## 必查清单(§4 A/B/C/D)

- [x] **A 方案闭合目标**:BM25 jieba 修复(hybrid sparse 腿恢复,recall 0.5→1.0)+ reranker
  中文(bge,overlap 0.816→0.967)。
- [x] **A 边界/并发**:score=0 文档被过滤(design §3);sparse 空时 dense 腿兜底(hybrid
  降级矩阵);reranker OOM → fallback。
- [x] **A 无新失效**:降级矩阵——jieba ImportError→正则(+warning),reranker OOM→fallback。
- [x] **B §7.2 测试规范**:regression test 12 用例(切词/单字/降级告警/召回/score过滤)。
- [x] **B §13 诚实度量**:precision 未达标如实记录 + 归因分块。
- [x] **C 体裁**:8 字段 schema + Conventional Comments。
- [x] **D 可执行性**:每条 recommendation 给 file:line + verification。

## 合并门禁
- **Critical: 0** · **High: 0** → 门禁满足。
- **Medium: 2**(F-RS-01/02 accepted)· **Low: 2**(F-RS-03/04 accepted)。
- **净裁决**: ✅ **设计批准,编码完成**。
