import request from 'supertest'
import app from '../src/app'
import prisma from '../src/prisma'

describe('Software Item Detail API', () => {
  let token = ''
  let projectId = ''
  let itemId = ''

  beforeAll(async () => {
    await prisma.softwareItem.deleteMany()
    await prisma.testProject.deleteMany()
    await prisma.user.deleteMany()

    const username = `detail_user_${Date.now()}`
    await request(app).post('/api/auth/register').send({ username, password: 'password123' })
    const login = await request(app).post('/api/auth/login').send({ username, password: 'password123' })
    token = login.body.token

    const projectRes = await request(app)
      .post('/api/projects')
      .set('Authorization', `Bearer ${token}`)
      .send({ name: 'DetailProject' })
    projectId = projectRes.body.data.project_id

    await request(app)
      .post(`/api/projects/${projectId}/items/upload`)
      .set('Authorization', `Bearer ${token}`)
      .field('name', 'DemoItem')
      .field('paths', 'README.md')
      .field('paths', 'src/main.ts')
      .attach('files', Buffer.from('# hello'), 'README.md')
      .attach('files', Buffer.from('console.log("ok")'), 'main.ts')

    const listRes = await request(app)
      .get(`/api/projects/${projectId}/items`)
      .set('Authorization', `Bearer ${token}`)
    itemId = listRes.body.data.items[0].item_id
  })

  afterAll(async () => {
    await prisma.$disconnect()
  })

  it('获取软件项目目录结构', async () => {
    const res = await request(app)
      .get(`/api/projects/${projectId}/items/${itemId}/structure`)
      .set('Authorization', `Bearer ${token}`)
    expect(res.status).toBe(200)
    expect(Array.isArray(res.body.data.children)).toBe(true)
  })

  it('获取文件内容', async () => {
    const res = await request(app)
      .get(`/api/projects/${projectId}/items/${itemId}/file`)
      .set('Authorization', `Bearer ${token}`)
      .query({ path: 'README.md' })
    expect(res.status).toBe(200)
    expect(res.body.data.kind).toBe('text')
    expect(res.body.data.content).toContain('hello')
  })

  it('正确识别 .py 文件为文本', async () => {
    // 先创建一个 py 文件
    await request(app)
      .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
      .set('Authorization', `Bearer ${token}`)
      .send({ action: 'new_file', path: 'script.py' })
    
    // 写入内容（通过 new_file 创建的是空文件，这里测试空文件也是 text）
    // 或者我们直接获取它，看 kind
    const res = await request(app)
      .get(`/api/projects/${projectId}/items/${itemId}/file`)
      .set('Authorization', `Bearer ${token}`)
      .query({ path: 'script.py' })

    expect(res.status).toBe(200)
    expect(res.body.data.kind).toBe('text')
    expect(res.body.data.language).toBe('python')
  })

  it('执行文件节点操作后可刷新结构', async () => {
    const createRes = await request(app)
      .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
      .set('Authorization', `Bearer ${token}`)
      .send({ action: 'new_file', path: 'docs/new.md' })
    expect(createRes.status).toBe(200)

    const treeRes = await request(app)
      .get(`/api/projects/${projectId}/items/${itemId}/structure`)
      .set('Authorization', `Bearer ${token}`)
    expect(treeRes.status).toBe(200)
    const names = treeRes.body.data.children.map((n: any) => n.name)
    expect(names).toContain('docs')
  })
})

