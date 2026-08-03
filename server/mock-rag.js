// Mock RAG service — responds with valid RAG API JSON for dry-run testing
// Usage: node server/mock-rag.js
// Listens on port 8001, same as dev default for RAG_SERVICE_URL

const http = require('http');

let documents = [];
let nextId = 1;

function json(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

function parseBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks)));
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;

  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', '*');
  res.setHeader('Access-Control-Allow-Headers', '*');
  if (req.method === 'OPTIONS') return json(res, 204, {});

  try {
    // Health
    if (path === '/health' && req.method === 'GET') {
      return json(res, 200, { status: 'ok' });
    }

    // Upload document
    if (path === '/api/documents/upload' && req.method === 'POST') {
      await parseBody(req); // consume body
      const doc = {
        id: `mock-doc-${nextId++}`,
        filename: 'uploaded-file',
        status: 'indexed',
        message: 'Document indexed successfully',
      };
      documents.push(doc);
      console.log(`[mock-rag] Document uploaded: ${doc.id}`);
      return json(res, 200, doc);
    }

    // List documents
    if (path === '/api/documents' && req.method === 'GET') {
      return json(res, 200, { documents, total: documents.length });
    }

    // Delete document
    if (path.startsWith('/api/documents/') && req.method === 'DELETE') {
      const docId = path.split('/').pop();
      documents = documents.filter((d) => d.id !== docId);
      console.log(`[mock-rag] Document deleted: ${docId}`);
      return json(res, 200, { message: 'Document deleted' });
    }

    // Hybrid retrieval
    if (path === '/api/retrieval' && req.method === 'POST') {
      const body = await parseBody(req);
      const { query = '', top_k = 5 } = JSON.parse(body.toString());
      return json(res, 200, {
        query,
        results: [
          {
            content: `这是关于 "${query}" 的需求文档片段（mock）。`,
            metadata: { document_id: documents[0]?.id || 'mock-doc-1', filename: 'test-doc.md', chunk_index: 0 },
            score: 0.92,
          },
        ],
        total: 1,
        retrieval_time_ms: 12.3,
      });
    }

    // Dense retrieval
    if (path === '/api/retrieval/dense' && req.method === 'POST') {
      const body = await parseBody(req);
      const { query = '' } = JSON.parse(body.toString());
      return json(res, 200, {
        query,
        results: [{ content: `[dense] 关于 "${query}" 的结果`, metadata: {}, score: 0.88 }],
        total: 1,
        retrieval_time_ms: 8.1,
      });
    }

    // Sparse retrieval
    if (path === '/api/retrieval/sparse' && req.method === 'POST') {
      const body = await parseBody(req);
      const { query = '' } = JSON.parse(body.toString());
      return json(res, 200, {
        query,
        results: [{ content: `[sparse] 关于 "${query}" 的结果`, metadata: {}, score: 0.75 }],
        total: 1,
        retrieval_time_ms: 5.2,
      });
    }

    return json(res, 404, { detail: 'Not found' });
  } catch (err) {
    console.error('[mock-rag] Error:', err);
    return json(res, 500, { detail: 'Internal error' });
  }
});

const PORT = 8001;
server.listen(PORT, () => {
  console.log(`[mock-rag] Mock RAG service running at http://localhost:${PORT}`);
  console.log('[mock-rag] Endpoints: upload / list / delete / retrieval');
});
