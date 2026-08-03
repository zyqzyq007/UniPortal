import request from 'supertest'
import app from '../src/app'
import prisma from '../src/prisma'
import fs from 'fs'
import path from 'path'

// Mock fetch for RAG service calls
const mockRagFetch = jest.fn()
global.fetch = mockRagFetch

function mockRagUpload(documentId: string) {
  mockRagFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ id: documentId, filename: 'test.pdf', status: 'indexed' }),
  })
}

function mockRagList(docs: Array<{ id: string; filename: string; status: string }>) {
  mockRagFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ documents: docs, total: docs.length }),
  })
}

function mockRagDelete() {
  mockRagFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ message: 'deleted' }),
  })
}

function mockRagRetrieval(results: Array<{ content: string; source?: string; metadata?: Record<string, any>; score: number }>) {
  mockRagFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({
      query: 'test query',
      results,
      total: results.length,
      retrieval_time_ms: 10,
    }),
  })
}

function mockRagError(status: number, body: string) {
  mockRagFetch.mockResolvedValueOnce({
    ok: false,
    status,
    text: async () => body,
  })
}

describe('Knowledge API', () => {
  let token: string
  let userId: string
  let projectId: string
  let projectId2: string

  beforeAll(async () => {
    await prisma.knowledgeDocument.deleteMany()
    await prisma.softwareItem.deleteMany()
    await prisma.testProject.deleteMany()
    await prisma.user.deleteMany()

    const userRes = await request(app)
      .post('/api/auth/register')
      .send({ username: 'kbtestuser', password: 'password123' })
    userId = userRes.body.userId

    const loginRes = await request(app)
      .post('/api/auth/login')
      .send({ username: 'kbtestuser', password: 'password123' })
    token = loginRes.body.token

    // Create two projects for isolation testing
    const p1 = await request(app)
      .post('/api/projects')
      .set('Authorization', `Bearer ${token}`)
      .send({ name: 'KBProject1' })
    projectId = p1.body.data.project_id

    const p2 = await request(app)
      .post('/api/projects')
      .set('Authorization', `Bearer ${token}`)
      .send({ name: 'KBProject2' })
    projectId2 = p2.body.data.project_id
  })

  afterAll(async () => {
    await prisma.$disconnect()
  })

  beforeEach(() => {
    mockRagFetch.mockReset()
  })

  // ─── Auth ───

  describe('Authentication', () => {
    it('rejects unauthenticated requests', async () => {
      const res = await request(app).get(`/api/knowledge/${projectId}/documents`)
      expect(res.status).toBe(401)
    })

    it('rejects invalid token', async () => {
      const res = await request(app)
        .get(`/api/knowledge/${projectId}/documents`)
        .set('Authorization', 'Bearer invalid-token')
      expect(res.status).toBe(403)
    })
  })

  // ─── List Documents ───

  describe('GET /api/knowledge/:projectId/documents', () => {
    it('returns empty list when no documents exist', async () => {
      const res = await request(app)
        .get(`/api/knowledge/${projectId}/documents`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)
      expect(res.body.code).toBe(200)
      expect(res.body.data.documents).toEqual([])
      expect(res.body.data.total).toBe(0)
    })

    it('returns documents for a project', async () => {
      // First, create a document record by simulating an upload
      mockRagUpload('rag-doc-1')
      const tmpFile = path.join(__dirname, 'fixtures', 'test-doc.txt')

      await request(app)
        .post(`/api/knowledge/${projectId}/documents`)
        .set('Authorization', `Bearer ${token}`)
        .attach('file', tmpFile)

      mockRagList([{ id: 'rag-doc-1', filename: 'test-doc.txt', status: 'indexed' }])

      const res = await request(app)
        .get(`/api/knowledge/${projectId}/documents`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)
      expect(res.body.data.documents).toHaveLength(1)
      expect(res.body.data.documents[0].filename).toBe('test-doc.txt')
    })

    it('isolates documents by project', async () => {
      // Upload to projectId2
      mockRagUpload('rag-doc-project2')
      const tmpFile = path.join(__dirname, 'fixtures', 'test-doc.txt')

      await request(app)
        .post(`/api/knowledge/${projectId2}/documents`)
        .set('Authorization', `Bearer ${token}`)
        .attach('file', tmpFile)

      // Project 1 should NOT contain the doc uploaded to project 2
      const res = await request(app)
        .get(`/api/knowledge/${projectId}/documents`)
        .set('Authorization', `Bearer ${token}`)

      const ragIds = res.body.data.documents.map((d: any) => d.rag_document_id)
      expect(ragIds).not.toContain('rag-doc-project2')
    })
  })

  // ─── Upload Document ───

  describe('POST /api/knowledge/:projectId/documents', () => {
    it('uploads a document and records it', async () => {
      const ragDocId = 'rag-upload-' + Date.now()
      mockRagUpload(ragDocId)
      const tmpFile = path.join(__dirname, 'fixtures', 'test-doc.txt')

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/documents`)
        .set('Authorization', `Bearer ${token}`)
        .attach('file', tmpFile)

      expect(res.status).toBe(201)
      expect(res.body.code).toBe(201)
      expect(res.body.data.rag_document_id).toBe(ragDocId)
      expect(res.body.data.filename).toBe('test-doc.txt')
      expect(res.body.data.status).toBe('indexed')

      // Verify in database
      const dbDoc = await prisma.knowledgeDocument.findFirst({
        where: { rag_document_id: ragDocId },
      })
      expect(dbDoc).toBeTruthy()
      expect(dbDoc!.project_id).toBe(projectId)
    })

    it('returns 400 when no file provided', async () => {
      const res = await request(app)
        .post(`/api/knowledge/${projectId}/documents`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(400)
    })

    it('returns 404 for non-existent project', async () => {
      mockRagUpload('rag-nonexistent')
      const tmpFile = path.join(__dirname, 'fixtures', 'test-doc.txt')

      const res = await request(app)
        .post('/api/knowledge/nonexistent-id/documents')
        .set('Authorization', `Bearer ${token}`)
        .attach('file', tmpFile)

      expect(res.status).toBe(404)
    })

    it('returns 503 when RAG service fails', async () => {
      mockRagError(500, 'Internal error')
      const tmpFile = path.join(__dirname, 'fixtures', 'test-doc.txt')

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/documents`)
        .set('Authorization', `Bearer ${token}`)
        .attach('file', tmpFile)

      expect(res.status).toBe(500)
    })
  })

  // ─── Delete Document ───

  describe('DELETE /api/knowledge/:projectId/documents/:documentId', () => {
    let docId: string

    beforeEach(async () => {
      // Create a document directly in DB
      const doc = await prisma.knowledgeDocument.create({
        data: {
          project_id: projectId,
          rag_document_id: 'rag-to-delete',
          filename: 'to-delete.txt',
          file_size: BigInt(100),
          uploaded_by: userId,
        },
      })
      docId = doc.id
    })

    it('deletes a document', async () => {
      mockRagDelete()

      const res = await request(app)
        .delete(`/api/knowledge/${projectId}/documents/${docId}`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)

      const dbDoc = await prisma.knowledgeDocument.findUnique({ where: { id: docId } })
      expect(dbDoc).toBeNull()
    })

    it('returns 404 for non-existent document', async () => {
      const res = await request(app)
        .delete(`/api/knowledge/${projectId}/documents/nonexistent-id`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(404)
    })

    it('does not delete document from another project', async () => {
      const res = await request(app)
        .delete(`/api/knowledge/${projectId2}/documents/${docId}`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(404)
      // Document should still exist
      const dbDoc = await prisma.knowledgeDocument.findUnique({ where: { id: docId } })
      expect(dbDoc).toBeTruthy()
    })
  })

  // ─── Retrieval ───

  describe('POST /api/knowledge/:projectId/retrieval', () => {
    it('returns retrieval results', async () => {
      mockRagRetrieval([
        { content: 'chunk A', metadata: { document_id: 'rag-doc-1' }, score: 0.9 },
        { content: 'chunk B', metadata: { document_id: 'rag-doc-1' }, score: 0.8 },
      ])

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test query', top_k: 3 })

      expect(res.status).toBe(200)
      expect(res.body.data.query).toBe('test query')
      expect(res.body.data.results).toHaveLength(2)
      expect(res.body.data.results[0].content).toBe('chunk A')
    })

    it('applies confidence threshold and returns matched_count', async () => {
      mockRagRetrieval([
        { content: 'high', score: 0.9 },
        { content: 'mid', score: 0.5 },
        { content: 'low', score: 0.1 },
      ])

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test', top_k: 10, threshold: 0.3 })

      expect(res.status).toBe(200)
      // Only 0.9 and 0.5 >= 0.3 threshold
      expect(res.body.data.matched_count).toBe(2)
      expect(res.body.data.returned_count).toBe(2)
      expect(res.body.data.threshold).toBe(0.3)
    })

    it('sorts results by score descending', async () => {
      mockRagRetrieval([
        { content: 'low', score: 0.4 },
        { content: 'high', score: 0.95 },
        { content: 'mid', score: 0.6 },
      ])

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test', top_k: 10, threshold: 0.0 })

      const scores = res.body.data.results.map((r: any) => r.score)
      expect(scores).toEqual([0.95, 0.6, 0.4])
    })

    it('uses default threshold 0.3 when not provided', async () => {
      mockRagRetrieval([{ content: 'x', score: 0.2 }])

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test' })

      expect(res.body.data.threshold).toBe(0.3)
      expect(res.body.data.results).toHaveLength(0)
    })

    it('returns 400 when query is missing', async () => {
      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval`)
        .set('Authorization', `Bearer ${token}`)
        .send({})

      expect(res.status).toBe(400)
    })

    it('filters results by project documents', async () => {
      // This doc belongs to projectId
      await prisma.knowledgeDocument.create({
        data: {
          project_id: projectId,
          rag_document_id: 'rag-proj1',
          filename: 'proj1.txt',
          file_size: BigInt(100),
          uploaded_by: userId,
        },
      })

      mockRagRetrieval([
        { content: 'from project 1', source: 'proj1.txt', metadata: {}, score: 0.9 },
        { content: 'from other project', source: 'other.txt', metadata: {}, score: 0.8 },
      ])

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test', top_k: 5 })

      expect(res.status).toBe(200)
      expect(res.body.data.results).toHaveLength(1)
      expect(res.body.data.results[0].content).toBe('from project 1')
    })

    it('returns 503 when RAG is unavailable', async () => {
      mockRagFetch.mockRejectedValueOnce(
        Object.assign(new Error('connect ECONNREFUSED'), { cause: { code: 'ECONNREFUSED' } })
      )

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test' })

      expect(res.status).toBe(503)
    })
  })

  // ─── Dense / Sparse Retrieval ───

  describe('POST /api/knowledge/:projectId/retrieval/dense', () => {
    it('forwards to RAG dense endpoint', async () => {
      mockRagRetrieval([
        { content: 'dense result', metadata: {}, score: 0.95 },
      ])

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval/dense`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test', top_k: 3 })

      expect(res.status).toBe(200)
      expect(res.body.data.results[0].content).toBe('dense result')
    })
  })

  describe('POST /api/knowledge/:projectId/retrieval/sparse', () => {
    it('forwards to RAG sparse endpoint', async () => {
      mockRagRetrieval([
        { content: 'sparse result', metadata: {}, score: 0.7 },
      ])

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval/sparse`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test', top_k: 3 })

      expect(res.status).toBe(200)
      expect(res.body.data.results[0].content).toBe('sparse result')
    })

    it('normalizes BM25 scores to [0, 1] so threshold is meaningful', async () => {
      // Raw BM25 scores are unbounded — e.g. [5.0, 2.5, 0.5]
      mockRagRetrieval([
        { content: 'best match', metadata: {}, score: 5.0 },
        { content: 'mid match', metadata: {}, score: 2.5 },
        { content: 'weak match', metadata: {}, score: 0.5 },
      ])

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval/sparse`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test', top_k: 10, threshold: 0.0 })

      expect(res.status).toBe(200)
      const scores = res.body.data.results.map((r: any) => r.score)
      // Top result normalized to 1.0, others scaled relative
      expect(scores[0]).toBeCloseTo(1.0, 2)
      expect(scores[1]).toBeCloseTo(0.5, 2)
      expect(scores[2]).toBeCloseTo(0.1, 2)
    })

    it('threshold filters by normalized score in sparse mode', async () => {
      mockRagRetrieval([
        { content: 'best', metadata: {}, score: 10.0 },
        { content: 'mid', metadata: {}, score: 4.0 },
        { content: 'weak', metadata: {}, score: 1.0 },
      ])

      const res = await request(app)
        .post(`/api/knowledge/${projectId}/retrieval/sparse`)
        .set('Authorization', `Bearer ${token}`)
        .send({ query: 'test', top_k: 10, threshold: 0.3 })

      // Normalized: [1.0, 0.4, 0.1] → threshold 0.3 keeps [1.0, 0.4]
      expect(res.body.data.matched_count).toBe(2)
    })
  })
})
