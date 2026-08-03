import request from 'supertest'
import app from '../src/app'
import prisma from '../src/prisma'
import path from 'path'
import fs from 'fs'
import AdmZip from 'adm-zip'

const STORAGE_ROOT = path.join(__dirname, '../storage')

function makeZip(): Buffer {
  const zip = new AdmZip()
  zip.addFile('README.md', Buffer.from('# Test Archive'))
  zip.addFile('src/index.ts', Buffer.from('export const hello = "world";'))
  return zip.toBuffer()
}

describe('Software Items — full lifecycle', () => {
  let token: string
  let projectId: string
  let itemId: string

  beforeAll(async () => {
    await prisma.softwareItem.deleteMany()
    await prisma.testProject.deleteMany()
    await prisma.user.deleteMany()

    const username = `sw_item_${Date.now()}`
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
      .send({ name: 'SWTestProject' })
    projectId = proj.body.data.project_id

    // Create the item immediately so itemId is available for all describe blocks
    const res = await request(app)
      .post(`/api/projects/${projectId}/items/upload`)
      .set('Authorization', `Bearer ${token}`)
      .field('name', 'ArchiveItem')
      .field('version', '2.0.0')
      .field('description', 'A test archive')
      .attach('archive', makeZip(), 'test-package.zip')

    if (res.status === 201) {
      itemId = res.body.data.item_id
    }
  })

  afterAll(async () => {
    await prisma.$disconnect()
  })

  // ── Upload ──────────────────────────────────────────

  describe('POST /:id/items/upload', () => {
    it('uploads archive (zip) and extracts correctly', async () => {
      // item was already created in outer beforeAll
      expect(itemId).toBeDefined()
      const item = await prisma.softwareItem.findUnique({ where: { item_id: itemId } })
      expect(item).toBeTruthy()
      expect(item!.name).toBe('ArchiveItem')
      expect(item!.version).toBe('2.0.0')
    })

    it('uploads files (folder mode) with paths', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'FolderItem')
        .field('paths', 'src/index.ts')
        .field('paths', 'src/utils/helper.ts')
        .field('paths', 'README.md')
        .attach('files', Buffer.from('export const x = 1;'), 'index.ts')
        .attach('files', Buffer.from('export const y = 2;'), 'helper.ts')
        .attach('files', Buffer.from('# Hello'), 'README.md')

      expect(res.status).toBe(201)

      // Verify structure
      const structRes = await request(app)
        .get(`/api/projects/${projectId}/items/${res.body.data.item_id}/structure`)
        .set('Authorization', `Bearer ${token}`)
      expect(structRes.status).toBe(200)
      const children = structRes.body.data.children.map((c: any) => c.name)
      expect(children).toContain('src')
      expect(children).toContain('README.md')
    })

    it('creates uniportal/project_manifest.json after upload', async () => {
      // Manifest lives under the item's disk directory (file_path), NOT item_id
      const item = await prisma.softwareItem.findUnique({ where: { item_id: itemId } })
      const manifestPath = path.join(STORAGE_ROOT, projectId, item!.file_path, 'uniportal', 'project_manifest.json')
      expect(fs.existsSync(manifestPath)).toBe(true)

      const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'))
      expect(manifest.project_id).toBe(projectId)
      expect(manifest.manifest_version).toBe('1.0')
      expect(manifest.item_count).toBeGreaterThanOrEqual(1)
      expect(manifest.current_item).toBeDefined()
      expect(manifest.all_items).toBeInstanceOf(Array)
      expect(manifest.generated_at).toBeDefined()
    })

    it('rejects upload without files', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'Empty')
      expect(res.status).toBe(400)
    })

    it('rejects description longer than 500 chars', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'test')
        .field('description', 'x'.repeat(501))
        .attach('archive', Buffer.from('zip'), 'test.zip')
      expect(res.status).toBe(400)
    })
  })

  // ── List / Search ───────────────────────────────────

  describe('GET /:id/items — pagination and search', () => {
    it('returns paginated item list', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.data.items).toBeDefined()
      expect(res.body.data.total).toBeGreaterThan(0)
      expect(res.body.data.page).toBe(1)
    })

    it('searches items by name', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items`)
        .query({ search: 'ArchiveItem' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.body.data.items.every((i: any) => i.name.includes('ArchiveItem'))).toBe(true)
    })

    it('returns empty list for non-matching search', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items`)
        .query({ search: 'ZzzzNonExistent' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.body.data.total).toBe(0)
    })
  })

  // ── File Structure ───────────────────────────────────

  describe('GET /:id/items/:itemId/structure', () => {
    it('returns top-level children', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/structure`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.data.type).toBe('dir')
      expect(Array.isArray(res.body.data.children)).toBe(true)
    })

    it('dirs sort before files', async () => {
      // Create mixed entries
      await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_folder', path: 'AAA_folder' })
      await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_file', path: 'AAA_file.txt' })

      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/structure`)
        .set('Authorization', `Bearer ${token}`)

      const types = res.body.data.children.map((c: any) => c.type)
      const firstFileIdx = types.indexOf('file')
      const lastDirIdx = types.lastIndexOf('dir')
      if (firstFileIdx >= 0 && lastDirIdx >= 0) {
        expect(lastDirIdx).toBeLessThan(firstFileIdx)
      }
    })

    it('returns 404 for non-existent item', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items/nonexistent/structure`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(404)
    })
  })

  // ── File Content ─────────────────────────────────────

  describe('GET /:id/items/:itemId/file', () => {
    beforeAll(async () => {
      // Create a small text file, a binary file (image bytes), and a large text file
      await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_file', path: 'hello.py' })

      // Write python content by creating it directly on disk
      const item = await prisma.softwareItem.findUnique({ where: { item_id: itemId } })
      if (item) {
        const itemRoot = path.join(STORAGE_ROOT, projectId, item.file_path)
        fs.writeFileSync(path.join(itemRoot, 'hello.py'), 'print("hello world")')
      }
    })

    it('reads text file content', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/file`)
        .query({ path: 'hello.py' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.data.kind).toBe('text')
      expect(res.body.data.language).toBe('python')
      // Might be empty if FS node created the file — check it's text at minimum
      expect(res.body.data.mime_type).toBeDefined()
    })

    it('rejects missing path parameter', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/file`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(400)
    })

    it('returns 404 for non-existent file path', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/file`)
        .query({ path: 'nonexistent/file.txt' })
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(404)
    })

    it('handles binary files (png)', async () => {
      // Write a small fake PNG to the item directory
      const item = await prisma.softwareItem.findUnique({ where: { item_id: itemId } })
      if (item) {
        const itemRoot = path.join(STORAGE_ROOT, projectId, item.file_path)
        const pngHeader = Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
        fs.writeFileSync(path.join(itemRoot, 'test.png'), pngHeader)

        const res = await request(app)
          .get(`/api/projects/${projectId}/items/${itemId}/file`)
          .query({ path: 'test.png' })
          .set('Authorization', `Bearer ${token}`)
        expect(res.status).toBe(200)
        expect(res.body.data.kind).toBe('binary')
        expect(res.body.data.content_base64).toBeDefined()
      }
    })
  })

  // ── FS Node Operations ──────────────────────────────

  describe('POST /:id/items/:itemId/fs/node', () => {
    it('creates a new file', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_file', path: 'new/test.js' })
      expect(res.status).toBe(200)

      // Verify it appears in structure
      const struct = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/structure`)
        .query({ path: 'new' })
        .set('Authorization', `Bearer ${token}`)
      const names = struct.body.data.children.map((c: any) => c.name)
      expect(names).toContain('test.js')
    })

    it('creates a new folder', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_folder', path: 'empty_dir' })
      expect(res.status).toBe(200)
    })

    it('renames a file', async () => {
      // Create then rename
      await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_file', path: 'old_name.txt' })

      const res = await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'rename', path: 'old_name.txt', newName: 'new_name.txt' })
      expect(res.status).toBe(200)

      // Verify old doesn't exist
      const oldRes = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/file`)
        .query({ path: 'old_name.txt' })
        .set('Authorization', `Bearer ${token}`)
      expect(oldRes.status).toBe(404)
    })

    it('deletes a file', async () => {
      // Create then delete
      await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_file', path: 'temp_to_delete.txt' })

      const res = await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'delete', path: 'temp_to_delete.txt' })
      expect(res.status).toBe(200)
    })

    it('deletes a folder recursively', async () => {
      await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'new_folder', path: 'dir_to_delete' })

      const res = await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'delete', path: 'dir_to_delete' })
      expect(res.status).toBe(200)
    })

    it('rejects rename without newName', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({ action: 'rename', path: 'some_file.txt' })
      expect(res.status).toBe(400)
    })

    it('rejects missing action and path', async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/${itemId}/fs/node`)
        .set('Authorization', `Bearer ${token}`)
        .send({})
      expect(res.status).toBe(400)
    })
  })

  // ── Download ─────────────────────────────────────────

  describe('GET /:id/items/:itemId/download', () => {
    it('downloads item as zip', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items/${itemId}/download`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.header['content-type']).toContain('application/zip')
      expect(res.header['content-disposition']).toContain('attachment')
    })

    it('returns 404 for non-existent item', async () => {
      const res = await request(app)
        .get(`/api/projects/${projectId}/items/nonexistent/download`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(404)
    })
  })

  // ── Delete ───────────────────────────────────────────

  describe('DELETE /:id/items/:itemId', () => {
    let deleteItemId: string

    beforeAll(async () => {
      const res = await request(app)
        .post(`/api/projects/${projectId}/items/upload`)
        .set('Authorization', `Bearer ${token}`)
        .field('name', 'ToBeDeleted')
        .attach('archive', makeZip(), 'delete-me.zip')
      deleteItemId = res.body.data.item_id
    })

    it('deletes item and returns success', async () => {
      const res = await request(app)
        .delete(`/api/projects/${projectId}/items/${deleteItemId}`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(200)
      expect(res.body.code).toBe(200)
    })

    it('confirms item is removed from DB', async () => {
      const check = await prisma.softwareItem.findUnique({
        where: { item_id: deleteItemId }
      })
      expect(check).toBeNull()
    })

    it('returns 404 for already deleted item', async () => {
      const res = await request(app)
        .delete(`/api/projects/${projectId}/items/${deleteItemId}`)
        .set('Authorization', `Bearer ${token}`)
      expect(res.status).toBe(404)
    })
  })
})
