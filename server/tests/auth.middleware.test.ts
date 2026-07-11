import request from 'supertest'
import app from '../src/app'
import prisma from '../src/prisma'
import jwt from 'jsonwebtoken'

const JWT_SECRET = process.env.JWT_SECRET || 'secret'

describe('Auth Middleware', () => {
  let token: string

  beforeAll(async () => {
    await prisma.softwareItem.deleteMany()
    await prisma.testProject.deleteMany()
    await prisma.user.deleteMany()

    await request(app)
      .post('/api/auth/register')
      .send({ username: 'mwuser', password: 'password123' })

    const login = await request(app)
      .post('/api/auth/login')
      .send({ username: 'mwuser', password: 'password123' })
    token = login.body.token
  })

  afterAll(async () => {
    await prisma.$disconnect()
  })

  describe('Protected routes reject unauthenticated requests', () => {
    it('returns 401 without token', async () => {
      const res = await request(app).get('/api/projects')
      expect(res.status).toBe(401)
      expect(res.body.code).toBe(401)
    })

    it('returns 401 with empty Authorization header', async () => {
      const res = await request(app)
        .get('/api/projects')
        .set('Authorization', 'Bearer ')
      expect(res.status).toBe(401)
    })

    it('returns 403 with malformed token', async () => {
      const res = await request(app)
        .get('/api/projects')
        .set('Authorization', 'Bearer invalid.token.here')
      expect(res.status).toBe(403)
    })

    it('returns 403 with expired token', async () => {
      const expired = jwt.sign(
        { id: 'fake', username: 'expired' },
        JWT_SECRET,
        { expiresIn: '0s' }
      )
      const res = await request(app)
        .get('/api/projects')
        .set('Authorization', `Bearer ${expired}`)
      expect(res.status).toBe(403)
    })

    it('returns 401 when user in token no longer exists', async () => {
      const ghost = jwt.sign(
        { id: '00000000-0000-0000-0000-000000000000', username: 'ghost' },
        JWT_SECRET,
        { expiresIn: '1h' }
      )
      const res = await request(app)
        .get('/api/projects')
        .set('Authorization', `Bearer ${ghost}`)
      expect(res.status).toBe(401)
    })
  })

  describe('Auth header vs cookie', () => {
    it('accepts token from cookie', async () => {
      const res = await request(app)
        .get('/api/projects')
        .set('Cookie', `token=${token}`)
      expect(res.status).toBe(200)
    })

    it('cookie takes precedence over header', async () => {
      const res = await request(app)
        .get('/api/projects')
        .set('Cookie', `token=${token}`)
        .set('Authorization', 'Bearer invalid')
      expect(res.status).toBe(200)
    })
  })

  describe('GET /api/auth/me', () => {
    it('returns current user when authenticated', async () => {
      const res = await request(app)
        .get('/api/auth/me')
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.code).toBe(200)
      expect(res.body.user).toBeDefined()
      expect(res.body.user.username).toBe('mwuser')
    })

    it('returns 401 when not authenticated', async () => {
      const res = await request(app).get('/api/auth/me')
      expect(res.status).toBe(401)
    })
  })
})
