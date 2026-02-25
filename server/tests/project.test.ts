import request from 'supertest';
import app from '../src/app';
import prisma from '../src/prisma';
import fs from 'fs';
import path from 'path';

const STORAGE_ROOT = path.join(__dirname, '../storage');

describe('Project API', () => {
  let token: string;
  let userId: string;

  beforeAll(async () => {
    await prisma.project.deleteMany();
    await prisma.user.deleteMany();

    // Register & Login
    const userRes = await request(app)
      .post('/api/auth/register')
      .send({ username: 'projectuser', password: 'password123' });
    userId = userRes.body.userId;

    const loginRes = await request(app)
      .post('/api/auth/login')
      .send({ username: 'projectuser', password: 'password123' });
    token = loginRes.body.token;
  });

  afterAll(async () => {
    // Cleanup files
    if (fs.existsSync(STORAGE_ROOT)) {
      // Be careful not to delete real data if any, but in test env it's fine
    }
    await prisma.$disconnect();
  });

  let projectId: string;

  describe('POST /api/projects', () => {
    it('should create a project', async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .send({ name: 'Test Project', description: 'Desc', repoUrl: 'https://example.com/repo.git' });

      expect(res.status).toBe(201);
      expect(res.body.data.name).toBe('Test Project');
      expect(res.body.data.owner_id).toBe(userId);
      projectId = res.body.data.project_id;

      // Verify folder existence
      const projectPath = res.body.data.path;
      expect(fs.existsSync(projectPath)).toBe(true);
      expect(fs.existsSync(path.join(projectPath, 'package.json'))).toBe(true);
    });

    it('should create a project with archive upload', async () => {
      const res = await request(app)
        .post('/api/projects')
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'Archive Project')
        .attach('archive', Buffer.from('zipdata'), 'sample.zip');

      expect(res.status).toBe(201);
      expect(res.body.data.name).toBe('Archive Project');
      const projectPath = res.body.data.path;
      expect(fs.existsSync(path.join(projectPath, 'sample.zip'))).toBe(true);
    });
  });

  describe('GET /api/projects', () => {
    it('should list user projects', async () => {
      const res = await request(app)
        .get('/api/projects')
        .set('Authorization', `Bearer ${token}`);

      expect(res.status).toBe(200);
      expect(Array.isArray(res.body.data)).toBe(true);
      expect(res.body.data.length).toBeGreaterThan(0);
      const ids = res.body.data.map((p: any) => p.project_id);
      expect(ids).toContain(projectId);
    });
  });

  describe('GET /api/projects/:id/structure', () => {
    it('should return project structure', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/structure`)
        .set('Authorization', `Bearer ${token}`);

      expect(res.status).toBe(200);
      const root = res.body.data;
      expect(root.name).toBe('root');
      expect(root.type).toBe('directory');
      expect(root.children).toBeDefined();
    });
  });

  describe('GET /api/projects/:id/file', () => {
    it('should return file content', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/file`)
        .query({ path: 'package.json' })
        .set('Authorization', `Bearer ${token}`);

      expect(res.status).toBe(200);
      expect(res.body.data.content).toContain('"name"');
    });
  });

  describe('DELETE /api/projects/:id', () => {
    it('should delete the project', async () => {
      const res = await request(app)
        .delete(`/api/projects/${projectId}`)
        .set('Authorization', `Bearer ${token}`);
      
      expect(res.status).toBe(200);
      
      // Verify DB deletion
      const check = await prisma.project.findUnique({ where: { project_id: projectId } });
      expect(check).toBeNull();
    });
  });
});
