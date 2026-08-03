# UniPortal 知识库 RAG 检索接口

> 适用对象：所有需要调用知识库检索能力的 AI 子工具开发者
> 目标：子工具通过统一接口获取需求文档中的相关知识片段

---

## 一、概述

UniPortal 知识库基于 [Xiaofei-Hua/RAG](https://github.com/Xiaofei-Hua/RAG)，支持文档上传后自动分块索引，提供混合检索（dense + sparse + RRF + 重排序）能力。

子工具调用检索接口获取与查询相关的文档片段，用于增强 AI 分析、测试用例生成等场景。

---

## 二、接口地址

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/knowledge/{projectId}/retrieval` | POST | 混合检索（推荐） |
| `/api/knowledge/{projectId}/retrieval/dense` | POST | 纯语义检索 |
| `/api/knowledge/{projectId}/retrieval/sparse` | POST | 纯关键词检索 (BM25) |

---

## 三、鉴权方式

与 UniPortal 其他接口一致，使用 Cookie JWT 或 Authorization Header。

### 方式一：Cookie（推荐，iframe 场景）

子工具在 iframe 内嵌时，浏览器自动携带 UniPortal 的登录 Cookie：

```javascript
fetch(`/api/knowledge/${projectId}/retrieval`, {
  method: 'POST',
  credentials: 'include',  // 自动携带 Cookie
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ query: '用户登录功能需求', top_k: 5 }),
})
```

### 方式二：Bearer Token

从 iframe URL 参数或 parent window 获取 token：

```javascript
const urlParams = new URLSearchParams(window.location.search);
const token = urlParams.get('portal_token');

fetch(`/api/knowledge/${projectId}/retrieval`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  },
  body: JSON.stringify({ query: '用户登录功能需求', top_k: 5 }),
})
```

---

## 四、请求格式

### 混合检索（推荐）

```json
POST /api/knowledge/{projectId}/retrieval
Content-Type: application/json

{
  "query": "用户登录功能需求",
  "top_k": 5
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 检索查询文本 |
| `top_k` | integer | 否 | 返回结果数量，默认 5，范围 1-50 |

### Dense / Sparse 检索

请求格式与混合检索一致，仅端点不同。

---

## 五、响应格式

```json
{
  "code": 200,
  "data": {
    "query": "用户登录功能需求",
    "results": [
      {
        "content": "## 3.1 用户登录功能\n\n用户可通过用户名和密码登录系统...",
        "metadata": {
          "document_id": "abc123",
          "filename": "需求规格说明书.md",
          "chunk_index": 5
        },
        "score": 0.87
      },
      {
        "content": "### 3.1.2 密码要求\n\n密码长度不少于8位，包含大小写字母和数字...",
        "metadata": {
          "document_id": "abc123",
          "filename": "需求规格说明书.md",
          "chunk_index": 6
        },
        "score": 0.82
      }
    ],
    "total": 2,
    "retrieval_time_ms": 45.2
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | string | 原始查询文本 |
| `results` | array | 检索结果列表，按相关度降序 |
| `results[].content` | string | 文档片段内容 |
| `results[].metadata` | object | 来源文档元信息 |
| `results[].score` | number | 相关度分数 (0-1) |
| `total` | integer | 实际返回数量 |
| `retrieval_time_ms` | number | 检索耗时（毫秒） |

---

## 六、子工具 iframe 集成示例

### 获取 projectId

子工具嵌入在 ToolViewer iframe 中，URL 格式为 `/projects/{projectId}/tools/{toolKey}`。通过以下方式获取 projectId：

```javascript
// 方式一：从父窗口 URL 解析
const parentPath = window.parent.location.pathname;
const match = parentPath.match(/\/projects\/([^/]+)/);
const projectId = match ? match[1] : null;

// 方式二：从 URL 参数获取
const urlParams = new URLSearchParams(window.location.search);
const projectId = urlParams.get('portal_project_id');
```

### 完整调用示例

```javascript
async function searchKnowledge(query, topK = 5) {
  // 解析 projectId
  const urlParams = new URLSearchParams(window.location.search);
  const projectId = urlParams.get('portal_project_id');
  if (!projectId) {
    // 从父窗口 URL 获取
    const parentPath = window.parent.location.pathname;
    const match = parentPath.match(/\/projects\/([^/]+)/);
    projectId = match ? match[1] : null;
  }
  if (!projectId) throw new Error('无法获取 projectId');

  const response = await fetch(`/api/knowledge/${projectId}/retrieval`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK }),
  });

  const result = await response.json();
  if (result.code !== 200) {
    throw new Error(result.message || '检索失败');
  }
  return result.data;
}

// 使用
const { results } = await searchKnowledge('单元测试覆盖率要求');
results.forEach(r => console.log(`[${r.score.toFixed(2)}] ${r.content.slice(0, 100)}...`));
```

---

## 七、错误码

| HTTP 状态 | code | 说明 |
|---|---|---|
| 400 | 400 | 缺少 query 参数 |
| 401 | 401 | 未登录 |
| 404 | 404 | 项目不存在 |
| 503 | 503 | RAG 服务不可用 |
| 500 | 500 | 服务器内部错误 |

---

## 八、项目隔离

检索接口自动按 `projectId` 过滤结果，只返回当前项目已上传文档的相关片段。跨项目数据不可见。

---

## 九、支持的文档格式

| 格式 | 说明 |
|---|---|
| `.pdf` | PDF 文档（含文字型，扫描件需 OCR 支持） |
| `.md` | Markdown |
| `.txt` | 纯文本 |
| `.docx` | Word 文档 |
| `.pptx` | PowerPoint 演示文稿 |
| `.html` / `.htm` | 网页文件 |
