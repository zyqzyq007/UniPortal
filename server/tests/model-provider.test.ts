import request from 'supertest'
import app from '../src/app'
import prisma from '../src/prisma'

// Mock fetch for test-connection endpoint
const mockFetch = jest.fn()
global.fetch = mockFetch as any

describe('Model Provider API', () => {
  let token: string
  let userId: string
  let providerId: string

  beforeAll(async () => {
    await prisma.modelProvider.deleteMany()
    await prisma.softwareItem.deleteMany()
    await prisma.testProject.deleteMany()
    await prisma.user.deleteMany()

    const userRes = await request(app)
      .post('/api/auth/register')
      .send({ username: 'mptest', password: 'password123' })
    userId = userRes.body.userId

    const loginRes = await request(app)
      .post('/api/auth/login')
      .send({ username: 'mptest', password: 'password123' })
    token = loginRes.body.token
  })

  afterAll(async () => {
    await prisma.$disconnect()
  })

  beforeEach(() => {
    mockFetch.mockReset()
  })

  describe('POST /api/model-providers', () => {
    it('creates a provider', async () => {
      const res = await request(app)
        .post('/api/model-providers')
        .set('Authorization', `Bearer ${token}`)
        .send({
          name: 'Test DashScope',
          provider_type: 'dashscope',
          base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
          api_key: 'sk-test-1234567890',
          capabilities: ['embedding', 'llm'],
        })

      expect(res.status).toBe(201)
      expect(res.body.data.name).toBe('Test DashScope')
      expect(res.body.data.provider_type).toBe('dashscope')
      // API key should be masked
      expect(res.body.data.api_key).toContain('***')
      expect(res.body.data.api_key).not.toContain('1234567890')
      providerId = res.body.data.id
    })

    it('rejects missing required fields', async () => {
      const res = await request(app)
        .post('/api/model-providers')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'Incomplete' })
      expect(res.status).toBe(400)
    })
  })

  describe('GET /api/model-providers', () => {
    it('lists user providers with masked keys', async () => {
      const res = await request(app)
        .get('/api/model-providers')
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)
      expect(Array.isArray(res.body.data)).toBe(true)
      expect(res.body.data.length).toBeGreaterThan(0)
      expect(res.body.data[0].api_key).toContain('***')
    })

    it('rejects unauthenticated requests', async () => {
      const res = await request(app).get('/api/model-providers')
      expect(res.status).toBe(401)
    })
  })

  describe('PUT /api/model-providers/:id', () => {
    it('updates provider name', async () => {
      const res = await request(app)
        .put(`/api/model-providers/${providerId}`)
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'Renamed Provider' })

      expect(res.status).toBe(200)
      expect(res.body.data.name).toBe('Renamed Provider')
    })

    it('preserves api_key when not provided (masked value)', async () => {
      const res = await request(app)
        .put(`/api/model-providers/${providerId}`)
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'Keep Key' })

      expect(res.status).toBe(200)
      // Original key preserved (still masked)
      expect(res.body.data.api_key).toContain('***')
    })

    it('returns 404 for non-existent provider', async () => {
      const res = await request(app)
        .put('/api/model-providers/nonexistent-id')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'X' })
      expect(res.status).toBe(404)
    })
  })

  describe('POST /api/model-providers/:id/test', () => {
    it('tests connection and classifies models', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          data: [
            { id: 'qwen-plus' },
            { id: 'qwen-turbo' },
            { id: 'text-embedding-v3' },
            { id: 'bge-m3' },
            { id: 'gte-rerank' },
          ],
        }),
      })

      const res = await request(app)
        .post(`/api/model-providers/${providerId}/test`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)
      expect(res.body.data.ok).toBe(true)
      expect(res.body.data.models.llm).toContain('qwen-plus')
      expect(res.body.data.models.embedding).toContain('text-embedding-v3')
      expect(res.body.data.models.embedding).toContain('bge-m3')
      expect(res.body.data.models.reranker).toContain('gte-rerank')
    })

    it('handles connection failure gracefully', async () => {
      mockFetch.mockRejectedValueOnce(new Error('ECONNREFUSED'))

      const res = await request(app)
        .post(`/api/model-providers/${providerId}/test`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)
      expect(res.body.data.ok).toBe(false)
      expect(res.body.data.error).toBeTruthy()
    })

    it('handles non-200 HTTP response', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 401 })

      const res = await request(app)
        .post(`/api/model-providers/${providerId}/test`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)
      expect(res.body.data.ok).toBe(false)
      expect(res.body.data.error).toContain('401')
    })
  })

  describe('GET /api/model-providers/available-models', () => {
    it('aggregates models from active providers', async () => {
      const res = await request(app)
        .get('/api/model-providers/available-models')
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)
      expect(res.body.data.llm).toBeInstanceOf(Array)
      // Models should be prefixed with provider name
      expect(res.body.data.llm.some((m: string) => m.includes('qwen-plus'))).toBe(true)
    })
  })

  describe('DELETE /api/model-providers/:id', () => {
    it('deletes a provider', async () => {
      const res = await request(app)
        .delete(`/api/model-providers/${providerId}`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)

      // Verify gone
      const list = await request(app)
        .get('/api/model-providers')
        .set('Authorization', `Bearer ${token}`)
      expect(list.body.data.find((p: any) => p.id === providerId)).toBeUndefined()
    })

    it('returns 404 for non-existent provider', async () => {
      const res = await request(app)
        .delete('/api/model-providers/nonexistent')
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(404)
    })
  })

  describe('Isolation', () => {
    it('user A cannot see user B providers', async () => {
      // Create provider as user A
      await request(app)
        .post('/api/model-providers')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'UserA Provider', provider_type: 'openai', base_url: 'https://x' })

      // Register user B
      await request(app).post('/api/auth/register').send({ username: 'mpuserB', password: 'pass' })
      const tokenB = (await request(app)
        .post('/api/auth/login')
        .send({ username: 'mpuserB', password: 'pass' })).body.token

      const listB = await request(app)
        .get('/api/model-providers')
        .set('Authorization', `Bearer ${tokenB}`)

      expect(listB.body.data).toEqual([])
    })
  })
})
