import request from 'supertest'
import app from '../src/app'
import prisma from '../src/prisma'
import AdmZip from 'adm-zip'
import iconv from 'iconv-lite'
import path from 'path'
import fs from 'fs'

const STORAGE_ROOT = path.join(__dirname, '../storage')

function makeZipWithNames(files: Record<string, string>): Buffer {
  const zip = new AdmZip()
  for (const [filename, content] of Object.entries(files)) {
    zip.addFile(filename, Buffer.from(content, 'utf-8'))
  }
  return zip.toBuffer()
}

describe('Archive encoding & format validation', () => {
  let token: string
  let projectId: string

  beforeAll(async () => {
    await prisma.softwareItem.deleteMany()
    await prisma.testProject.deleteMany()
    await prisma.user.deleteMany()

    const username = `archive_test_${Date.now()}`
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
      .send({ name: 'ArchiveTestProject' })
    projectId = proj.body.data.project_id
  })

  afterAll(async () => {
    await prisma.$disconnect()
  })

  describe('ZIP with Chinese filenames (UTF-8 flag set)', () => {
    it('extracts Chinese-named files correctly', async () => {
      const zip = makeZipWithNames({
        '测试文档/需求说明.md': '# 需求说明',
        '测试文档/src/index.ts': 'export const hello = "你好世界";'
      })

      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'ChineseZip')
        .attach('archive', zip, 'chinese-files.zip')

      expect(res.status).toBe(201)

      const structRes = await request(app)
        .get(`/api/projects/${projectId}/items/${res.body.data.item_id}/structure`)
        .set('Authorization', `Bearer ${token}`)

      const names = structRes.body.data.children.map((c: any) => c.name)
      expect(names).toContain('测试文档')

      // Check subdirectory
      const subRes = await request(app)
        .get(`/api/projects/${projectId}/items/${res.body.data.item_id}/structure`)
        .query({ path: '测试文档' })
        .set('Authorization', `Bearer ${token}`)

      const subNames = subRes.body.data.children.map((c: any) => c.name)
      expect(subNames).toContain('需求说明.md')
      expect(subNames).toContain('src')

      // Read content
      const fileRes = await request(app)
        .get(`/api/projects/${projectId}/items/${res.body.data.item_id}/file`)
        .query({ path: '测试文档/src/index.ts' })
        .set('Authorization', `Bearer ${token}`)

      expect(fileRes.status).toBe(200)
      expect(fileRes.body.data.content).toContain('你好世界')
    })
  })

  describe('ZIP with mixed CJK + ASCII filenames', () => {
    it('handles mixed names correctly', async () => {
      const zip = makeZipWithNames({
        '项目根目录/README.md': '# Project',
        '项目根目录/源代码/主程序.ts': 'const main = () => {}',
        '项目根目录/配置文件.json': '{}'
      })

      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'MixedNames')
        .attach('archive', zip, 'mixed.zip')

      expect(res.status).toBe(201)

      const structRes = await request(app)
        .get(`/api/projects/${projectId}/items/${res.body.data.item_id}/structure`)
        .set('Authorization', `Bearer ${token}`)

      expect(structRes.body.data.children.map((c: any) => c.name)).toContain('项目根目录')
    })
  })

  describe('Format validation', () => {
    it('rejects .7z files with clear error', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'Test7z')
        .attach('archive', Buffer.from([0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C]), 'test.7z')

      expect(res.status).toBe(400)
      expect(res.body.message).toContain('.7z')
      expect(res.body.message).toContain('.zip')
    })

    it('rejects .tar.gz files (detected as .gz)', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'TestTarGz')
        .attach('archive', Buffer.from([0x1F, 0x8B, 0x08]), 'test.tar.gz')

      expect(res.status).toBe(400)
      expect(res.body.message).toContain('不支持')
      expect(res.body.message).toContain('.gz')
    })

    it('handles files without extension', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'NoExt')
        .attach('archive', Buffer.from('data'), 'noextension')

      expect(res.status).toBe(400)
    })

    it('accepts .zip files normally', async () => {
      const zip = makeZipWithNames({ 'readme.txt': 'hello' })
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'ValidZip')
        .attach('archive', zip, 'valid.zip')

      expect(res.status).toBe(201)
    })

    it('accepts .rar files without rejection (format validation)', async () => {
      // RAR format starts with "Rar!" magic bytes
      const rarMagic = Buffer.from([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07, 0x00])
      // Append minimal data to satisfy multer's file requirement
      const padded = Buffer.concat([rarMagic, Buffer.alloc(100, 0)])

      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'RarTest')
        .attach('archive', padded, 'test.rar')

      // Should not reject with "unsupported format" — format validation passes for .rar
      // But extraction may fail since this is not a valid RAR archive
      // Either 400 (extraction failed) or 201 (if it somehow works) is fine here
      expect([201, 400]).toContain(res.status)
      if (res.status === 400) {
        expect(res.body.message).toContain('解压失败')
      }
    })
  })

  // Unit test for the encoding recovery logic via indirect behavior
  describe('Encoding recovery behavior', () => {
    it('does not mangle already-valid UTF-8 CJK filenames', async () => {
      const zip = makeZipWithNames({ '简体中文/文件.txt': 'content' })

      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'Utf8CJK')
        .attach('archive', zip, 'utf8.zip')

      expect(res.status).toBe(201)

      const structRes = await request(app)
        .get(`/api/projects/${projectId}/items/${res.body.data.item_id}/structure`)
        .set('Authorization', `Bearer ${token}`)

      const names = structRes.body.data.children.map((c: any) => c.name)
      // Should contain the correct Chinese name, not garbled text
      expect(names).toContain('简体中文')
      // Should NOT contain garbled/mojibake patterns
      const garbledPattern = names.some((n: string) =>
        n.length > 0 && /^[\x00-\x7FÀ-ɏ]+$/.test(n) &&
        n.split('').some((c: string) => c.charCodeAt(0) > 127 && c.charCodeAt(0) < 256)
      )
      expect(garbledPattern).toBe(false)
    })
  })
})
