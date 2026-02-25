import request from 'supertest';
import app from '../src/app';
import prisma from '../src/prisma';
import bcrypt from 'bcryptjs';

describe('Auth API', () => {
  beforeAll(async () => {
    // Clean DB
    await prisma.project.deleteMany();
    await prisma.user.deleteMany();
  });

  afterAll(async () => {
    await prisma.$disconnect();
  });

  const testUser = {
    username: 'testuser',
    password: 'password123',
  };

  describe('POST /api/auth/register', () => {
    it('should register a new user', async () => {
      const res = await request(app)
        .post('/api/auth/register')
        .send(testUser);
      
      expect(res.status).toBe(201);
      expect(res.body.message).toBe('User created successfully');
      expect(res.body.userId).toBeDefined();

      // Verify DB
      const user = await prisma.user.findUnique({ where: { username: testUser.username } });
      expect(user).toBeTruthy();
      expect(user?.username).toBe(testUser.username);
    });

    it('should fail if username exists', async () => {
      const res = await request(app)
        .post('/api/auth/register')
        .send(testUser);
      
      expect(res.status).toBe(409);
    });
  });

  describe('POST /api/auth/login', () => {
    it('should return 404 for non-existent user', async () => {
      const res = await request(app)
        .post('/api/auth/login')
        .send({ username: 'nonexistent', password: 'password' });
      
      expect(res.status).toBe(404);
      expect(res.body.code).toBe(404);
      expect(res.body.action).toBe('立即注册');
    });

    it('should return 401 for wrong password', async () => {
      const res = await request(app)
        .post('/api/auth/login')
        .send({ username: testUser.username, password: 'wrongpassword' });
      
      expect(res.status).toBe(401);
      expect(res.body.code).toBe(401);
    });

    it('should login successfully and return token', async () => {
      const res = await request(app)
        .post('/api/auth/login')
        .send(testUser);
      
      expect(res.status).toBe(200);
      expect(res.body.token).toBeDefined();
      expect(res.header['set-cookie']).toBeDefined();
    });
  });
});
