import request from 'supertest'
import app from '../src/app'
import prisma from '../src/prisma'

describe('Edge Cases & Security', () => {
  let token: string
  let projectId: string
  let itemId: string

  beforeAll(async () => {
    await prisma.softwareItem.deleteMany()
    await prisma.testProject.deleteMany()
    await prisma.user.deleteMany()

    const username = `edge_${Date.now()}`
    await request(app)
      .post('/api/auth/register')
      .send({ username, password: 'password123' })
    const login = await request(app)
      .post('/api/auth/login')
      .send({ username, password: 'password123' })
    token = login.body.token

    const proj = await request(app)
      .post('/api/projects')
      .set('Authorization', `Bearer ${token}`)
      .send({ name: 'EdgeProject' })
    projectId = proj.body.data.project_id

    const item = await request(app)
      .post(`/api/projects/${projectId}/items/upload`)
      .set('Authorization', `Bearer ${token}`)
      .field('name', 'EdgeItem')
      .field('paths', 'src/index.ts')
      .attach('files', Buffer.from('const x = 1;'), 'index.ts')
    itemId = item.body.data.item_id
  })

  afterAll(async () => {
    await prisma.$disconnect()
  })

  // ── Path Traversal Protection ───────────────────────

  describe('Path traversal prevention', () => {
    it('blocks ../ escape in structure path', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/structure`)
        .query({ path: '../../../etc/passwd' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(500)
    })

    it('blocks ../ escape in file content path', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/file`)
        .query({ path: '../../../etc/passwd' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(500)
    })

    it('blocks ../ escape in fs node operations', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_file', path: '../../../evil.sh' })
      expect(res.status).toBe(500)
    })
  })

  // ── Input Edge Cases ────────────────────────────────

  describe('Input edge cases', () => {
    it('handles very long project name (exactly 64 chars)', async () => {
      const name64 = 'a'.repeat(64)
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: name64 })
      expect(res.status).toBe(201)
      expect(res.body.data.name).toHaveLength(64)
    })

    it('handles empty search query gracefully', async () => {
      const res = await request(app)
        .get('/api/projects')
        .query({ search: '' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.data.items.length).toBeGreaterThan(0)
    })

    it('handles special characters in search (SQL injection attempt)', async () => {
      const res = await request(app)
        .get('/api/projects')
        .query({ search: "'; DROP TABLE test_projects; --" })
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      // Database should still be intact
      const check = await prisma.testProject.count()
      expect(check).toBeGreaterThan(0)
    })

    it('handles missing fields in register', async () => {
      const res = await request(app)
        .post('/api/auth/register')
        .send({})
      expect(res.status).toBe(400)
    })

    it('handles missing password in register', async () => {
      const res = await request(app)
        .post('/api/auth/register')
        .send({ username: 'nopass' })
      expect(res.status).toBe(400)
    })

    it('handles missing username in login', async () => {
      const res = await request(app)
        .post('/api/auth/login')
        .send({ password: 'nouser' })
      expect(res.status).toBe(500)
    })
  })

  // ── Concurrent / race condition light check ──────────

  describe('Consistency', () => {
    it('item_count stays accurate after multiple uploads and deletes', async () => {
      const before = await prisma.testProject.findUnique({
        where: { project_id: projectId }
      })

      // Upload two items via folder mode
      const i1 = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'Counter1')
        .field('paths', 'a.txt')
        .attach('files', Buffer.from('a'), 'a.txt')
      const i2 = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'Counter2')
        .field('paths', 'b.txt')
        .attach('files', Buffer.from('b'), 'b.txt')

      const mid = await prisma.testProject.findUnique({
        where: { project_id: projectId }
      })
      expect(mid!.item_count).toBe((before!.item_count) + 2)

      // Delete one
      await request(app)
        .delete(`/api/projects/${projectId}/items/${i1.body.data.item_id}`)
        .set('Authorization', `Bearer ${token}`)

      const after = await prisma.testProject.findUnique({
        where: { project_id: projectId }
      })
      expect(after!.item_count).toBe((before!.item_count) + 1)
    })
  })

  // ── Content-Type handling ───────────────────────────

  describe('Content type handling', () => {
    it('JSON files are identified correctly', async () => {
      // Create a JSON file
      await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_file', path: 'config.json' })

      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/file`)
        .query({ path: 'config.json' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.body.data.mime_type).toBe('application/json')
      expect(res.body.data.language).toBe('json')
    })

    it('unknown extensions return octet-stream', async () => {
      await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_file', path: 'data.xyzzy' })

      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/file`)
        .query({ path: 'data.xyzzy' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.body.data.mime_type).toBe('application/octet-stream')
      expect(res.body.data.kind).toBe('binary')
    })
  })

  // ── Health check ─────────────────────────────────────

  describe('GET /health', () => {
    it('returns ok without auth', async () => {
      const res = await request(app).get('/health')
      expect(res.status).toBe(200)
      expect(res.body.status).toBe('ok')
    })
  })
})
