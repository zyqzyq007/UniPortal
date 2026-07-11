import request from 'supertest'
import app from '../src/app'
import prisma from '../src/prisma'

describe('Project API', () => {
  let token: string
  let userId: string
  let projectId: string

  beforeAll(async () => {
    await prisma.softwareItem.deleteMany()
    await prisma.testProject.deleteMany()
    await prisma.user.deleteMany()

    const userRes = await request(app)
      .post('/api/auth/register')
      .send({ username: 'projectuser', password: 'password123' })
    userId = userRes.body.userId

    const loginRes = await request(app)
      .post('/api/auth/login')
      .send({ username: 'projectuser', password: 'password123' })
    token = loginRes.body.token
  })

  afterAll(async () => {
    await prisma.$disconnect()
  })

  describe('POST /api/projects', () => {
    it('creates a project', async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'TestProject', description: 'A test project' })

      expect(res.status).toBe(201)
      expect(res.body.data.name).toBe('TestProject')
      expect(res.body.data.description).toBe('A test project')
      expect(res.body.data.owner_id).toBe(userId)
      expect(res.body.data.project_id).toBeDefined()
      projectId = res.body.data.project_id

      const dbProject = await prisma.testProject.findUnique({
        where: { project_id: projectId }
      })
      expect(dbProject).toBeTruthy()
    })
  })

  describe('GET /api/projects', () => {
    it('returns paginated project list', async () => {
      const res = await request(app)
        .get('/api/projects')
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)
      expect(res.body.data.items).toBeDefined()
      expect(Array.isArray(res.body.data.items)).toBe(true)
      expect(res.body.data.total).toBeGreaterThan(0)
      expect(res.body.data.page).toBe(1)
    })
  })

  describe('GET /api/projects/:id', () => {
    it('returns project details', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)
      expect(res.body.data.name).toBe('TestProject')
      expect(res.body.data.project_id).toBe(projectId)
    })

    it('returns 404 for non-existent project', async () => {
      const res = await request(app)
        .get('/api/projects/nonexistent')
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(404)
    })
  })

  describe('PUT /api/projects/:id', () => {
    it('updates project name and description', async () => {
      const res = await request(app)
        .put(`/api/projects/${projectId}`)
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'UpdatedProject', description: 'Updated_desc' })

      expect(res.status).toBe(200)
      expect(res.body.data.name).toBe('UpdatedProject')
      expect(res.body.data.description).toBe('Updated_desc')
    })
  })

  describe('DELETE /api/projects/:id', () => {
    it('deletes project and verifies removal', async () => {
      const res = await request(app)
        .delete(`/api/projects/${projectId}`)
        .set('Authorization', `Bearer ${token}`)

      expect(res.status).toBe(200)

      const check = await prisma.testProject.findUnique({
        where: { project_id: projectId }
      })
      expect(check).toBeNull()
    })
  })
})
