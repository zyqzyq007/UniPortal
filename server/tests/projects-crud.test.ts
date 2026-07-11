import request from 'supertest'
import app from '../src/app'
import prisma from '../src/prisma'

describe('Projects CRUD', () => {
  let token: string
  let userId: string

  beforeAll(async () => {
    await prisma.softwareItem.deleteMany()
    await prisma.testProject.deleteMany()
    await prisma.user.deleteMany()

    const reg = await request(app)
      .post('/api/auth/register')
      .send({ username: 'cruduser', password: 'password123' })
    userId = reg.body.userId

    const login = await request(app)
      .post('/api/auth/login')
      .send({ username: 'cruduser', password: 'password123' })
    token = login.body.token
  })

  afterAll(async () => {
    await prisma.$disconnect()
  })

  describe('POST /api/projects — input validation', () => {
    it('rejects empty name', async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: '' })
      expect(res.status).toBe(400)
    })

    it('rejects name with special characters', async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'test@#$' })
      expect(res.status).toBe(400)
    })

    it('rejects name longer than 64 chars', async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'a'.repeat(65) })
      expect(res.status).toBe(400)
    })

    it('rejects description longer than 500 chars', async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'valid', description: 'x'.repeat(501) })
      expect(res.status).toBe(400)
    })

    it('creates project with valid Chinese name', async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: '测试项目' })
      expect(res.status).toBe(201)
    })

    it('creates project with mixed alphanumeric and underscore', async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'Test_Project_01' })
      expect(res.status).toBe(201)
    })
  })

  describe('GET /api/projects — pagination, search, sort', () => {
    beforeAll(async () => {
      // Create multiple projects for pagination testing
      const names = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon']
      for (const name of names) {
        await request(app)
          .post('/api/projects')
          .set('Authorization', `Bearer ${token}`)
          .send({ name })
      }
    })

    it('returns paginated results with default page/limit', async () => {
      const res = await request(app)
        .get('/api/projects')
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.code).toBe(200)
      expect(res.body.data.items).toBeDefined()
      expect(res.body.data.total).toBeGreaterThan(0)
      expect(res.body.data.page).toBe(1)
      expect(res.body.data.limit).toBe(10)
      expect(res.body.data.totalPages).toBeDefined()
    })

    it('returns empty items for page beyond total', async () => {
      const res = await request(app)
        .get('/api/projects')
        .query({ page: 999, limit: 10 })
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.data.items).toHaveLength(0)
    })

    it('searches by name', async () => {
      const res = await request(app)
        .get('/api/projects')
        .query({ search: 'Alpha' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.data.total).toBe(1)
      expect(res.body.data.items[0].name).toBe('Alpha')
    })

    it('sorts by name ascending', async () => {
      const res = await request(app)
        .get('/api/projects')
        .query({ sort: 'name', order: 'asc' })
        .set('Authorization', `Bearer ${token}`)
      const names = res.body.data.items.map((p: any) => p.name)
      const sorted = [...names].sort()
      expect(names).toEqual(sorted)
    })

    it('sorts by name descending', async () => {
      const res = await request(app)
        .get('/api/projects')
        .query({ sort: 'name', order: 'desc' })
        .set('Authorization', `Bearer ${token}`)
      const names = res.body.data.items.map((p: any) => p.name)
      const sorted = [...names].sort().reverse()
      expect(names).toEqual(sorted)
    })

    it('only returns projects owned by the current user', async () => {
      // Register another user and create a project
      const reg2 = await request(app)
        .post('/api/auth/register')
        .send({ username: 'other_crud', password: 'password123' })
      const login2 = await request(app)
        .post('/api/auth/login')
        .send({ username: 'other_crud', password: 'password123' })
      const token2 = login2.body.token

      await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token2}`)
        .send({ name: 'OtherUserProject' })

      const res1 = await request(app)
        .get('/api/projects')
        .set('Authorization', `Bearer ${token}`)
      // Should not see the other user's project
      const allNames = res1.body.data.items.map((p: any) => p.name)
      expect(allNames).not.toContain('OtherUserProject')
    })
  })

  describe('PUT /api/projects/:id', () => {
    let projectId: string

    beforeAll(async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'UpdateTarget' })
      projectId = res.body.data.project_id
    })

    it('updates name and description', async () => {
      const res = await request(app)
        .put(`/api/projects/${projectId}`)
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'NewName', description: 'New description' })
      expect(res.status).toBe(200)
      expect(res.body.data.name).toBe('NewName')
      expect(res.body.data.description).toBe('New description')
    })

    it('returns 404 for non-existent project', async () => {
      const res = await request(app)
        .put('/api/projects/nonexistent-id')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'test' })
      expect(res.status).toBe(404)
    })

    it('returns 403 when updating another user project', async () => {
      const login2 = await request(app)
        .post('/api/auth/login')
        .send({ username: 'other_crud', password: 'password123' })
      const token2 = login2.body.token

      const res = await request(app)
        .put(`/api/projects/${projectId}`)
        .set('Authorization', `Bearer ${token2}`)
        .send({ name: 'Hacked' })
      expect(res.status).toBe(403)
    })
  })

  describe('DELETE /api/projects/:id', () => {
    let deleteTarget: string

    beforeAll(async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'DeleteTarget' })
      deleteTarget = res.body.data.project_id
    })

    it('deletes project and returns success', async () => {
      const res = await request(app)
        .delete(`/api/projects/${deleteTarget}`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.code).toBe(200)
    })

    it('confirms project is removed from DB', async () => {
      const check = await prisma.testProject.findUnique({
        where: { project_id: deleteTarget }
      })
      expect(check).toBeNull()
    })

    it('returns 404 for already deleted project', async () => {
      const res = await request(app)
        .delete(`/api/projects/${deleteTarget}`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(404)
    })

    it('returns 403 when deleting another user project', async () => {
      // Create a new project
      const create = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'CantDeleteMe' })

      const login2 = await request(app)
        .post('/api/auth/login')
        .send({ username: 'other_crud', password: 'password123' })
      const token2 = login2.body.token

      const res = await request(app)
        .delete(`/api/projects/${create.body.data.project_id}`)
        .set('Authorization', `Bearer ${token2}`)
      expect(res.status).toBe(403)
    })
  })
})
