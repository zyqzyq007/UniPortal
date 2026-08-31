from __future__ import annotations

from agent.eval.types import EvalCase


def get_default_eval_cases() -> list[EvalCase]:
    """Domain-neutral fallback cases, mirroring ``data/eval/golden.yaml``.

    Used only when the golden YAML is absent. The default profile is
    domain-agnostic, so these cases verify generic RAG capability (factual
    recall, procedure, comparison, chat, edge) without binding the regression
    contract to any vertical domain.
    """
    return [
        # Factual recall (5)
        EvalCase(
            id="fact_python_gil_01",
            query="Python 的 GIL 是什么？它对多线程有什么影响？",
            expected_sections=[],
            expected_keywords=["GIL", "线程", "全局解释器锁"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="medium",
        ),
        EvalCase(
            id="fact_http_https_02",
            query="HTTP 和 HTTPS 有什么区别？HTTPS 是如何保证安全的？",
            expected_sections=[],
            expected_keywords=["HTTPS", "加密", "TLS", "证书"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="easy",
        ),
        EvalCase(
            id="fact_git_rebase_03",
            query="git rebase 和 git merge 有什么区别？各适合什么场景？",
            expected_sections=[],
            expected_keywords=["rebase", "merge", "历史", "分支"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="medium",
        ),
        EvalCase(
            id="fact_docker_image_04",
            query="Docker 镜像是如何实现分层存储的？分层有什么好处？",
            expected_sections=[],
            expected_keywords=["镜像", "分层", "层", "复用"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="medium",
        ),
        EvalCase(
            id="fact_index_db_05",
            query="数据库索引为什么会加快查询？它有什么代价？",
            expected_sections=[],
            expected_keywords=["索引", "查询", "写入", "B树"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="medium",
        ),
        # Procedure (3)
        EvalCase(
            id="proc_backup_06",
            query="如何对一台 Linux 服务器进行定期备份？请给出步骤。",
            expected_sections=[],
            expected_keywords=["备份", "cron", "rsync", "恢复"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="medium",
        ),
        EvalCase(
            id="proc_deploy_07",
            query="把一个 Web 应用部署到生产环境，通常需要哪些步骤？",
            expected_sections=[],
            expected_keywords=["部署", "构建", "环境变量", "健康检查"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="medium",
        ),
        EvalCase(
            id="proc_code_review_08",
            query="一次高质量的代码评审应该关注哪些方面？",
            expected_sections=[],
            expected_keywords=["评审", "正确性", "可读性", "测试"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="easy",
        ),
        # Comparison (2)
        EvalCase(
            id="compare_sql_nosql_09",
            query="关系型数据库和 NoSQL 数据库各自适合什么场景？",
            expected_sections=[],
            expected_keywords=["关系型", "NoSQL", "事务", "场景"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="hard",
        ),
        EvalCase(
            id="compare_rest_graphql_10",
            query="REST 和 GraphQL 各自的优缺点是什么？",
            expected_sections=[],
            expected_keywords=["REST", "GraphQL", "接口", "过度获取"],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="hard",
        ),
        # General chat (2)
        EvalCase(
            id="chat_greeting_11",
            query="你好，请介绍一下你能做什么？",
            expected_sections=[],
            expected_keywords=["知识库", "问答", "检索"],
            expected_intent="general_chat",
            expected_min_sources=0,
            difficulty="easy",
        ),
        EvalCase(
            id="chat_capability_12",
            query="你能回答哪些类型的问题？",
            expected_sections=[],
            expected_keywords=["问答", "知识库", "回答"],
            expected_intent="general_chat",
            expected_min_sources=0,
            difficulty="easy",
        ),
        # Edge cases (3)
        EvalCase(
            id="edge_ambiguous_13",
            query="异常",
            expected_sections=[],
            expected_keywords=[],
            expected_intent="rag_query",
            expected_min_sources=0,
            difficulty="hard",
        ),
        EvalCase(
            id="edge_short_14",
            query="部署",
            expected_sections=[],
            expected_keywords=["部署"],
            expected_intent="rag_query",
            expected_min_sources=0,
            difficulty="hard",
        ),
        EvalCase(
            id="edge_offtopic_15",
            query="今天天气怎么样？",
            expected_sections=[],
            expected_keywords=[],
            expected_intent="general_chat",
            expected_min_sources=0,
            difficulty="easy",
        ),
    ]
