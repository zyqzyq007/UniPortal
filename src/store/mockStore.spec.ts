import { describe, expect, it, beforeEach, vi } from 'vitest'

// Minimal localStorage mock
const store: Record<string, string> = {}
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store[key] ?? null,
  setItem: (key: string, val: string) => { store[key] = val },
  removeItem: (key: string) => { delete store[key] }
})

beforeEach(() => {
  Object.keys(store).forEach(k => delete store[k])
})

import { describe as viDescribe, expect as viExpect, it as viIt } from 'vitest'
import {
  ensureProjects,
  getProjects,
  getProjectById,
  addProject,
  updateProject,
  getTasks,
  getTasksByProject,
  getTaskById,
  createTask,
  updateTaskStatus,
  getProjectFiles,
  getFileContent,
  saveFileContent
} from '../store/mockStore'
import type { TaskStatus } from '../store/mockStore'

describe('mockStore', () => {
  describe('projects', () => {
    it('ensureProjects initializes with defaults when empty', () => {
      ensureProjects()
      const projects = getProjects()
      expect(projects.length).toBeGreaterThan(0)
    })

    it('getProjectById returns matching project', () => {
      ensureProjects()
      const projects = getProjects()
      const first = projects[0]
      const found = getProjectById(first.id)
      expect(found).toBeDefined()
      expect(found!.name).toBe(first.name)
    })

    it('getProjectById returns undefined for non-existent id', () => {
      ensureProjects()
      expect(getProjectById('nonexistent')).toBeUndefined()
    })

    it('addProject adds a new project', () => {
      const before = getProjects().length
      const p = addProject({ name: 'New Project', description: 'A new project' })
      expect(p.id).toBeDefined()
      expect(getProjects().length).toBe(before + 1)
      expect(getProjects()[0].name).toBe('New Project')
    })

    it('updateProject modifies project fields', () => {
      ensureProjects()
      const projects = getProjects()
      const target = projects[0]
      const updated = updateProject(target.id, { name: 'Renamed' })
      expect(updated.name).toBe('Renamed')
      expect(getProjectById(target.id)!.name).toBe('Renamed')
    })

    it('updateProject throws on non-existent project', () => {
      expect(() => updateProject('bad-id', { name: 'x' })).toThrow()
    })
  })

  describe('tasks', () => {
    it('creates task with running status', () => {
      ensureProjects()
      const projects = getProjects()
      const task = createTask(projects[0].id, 'doc-review', { docUrl: 'http://x.com' })
      expect(task.status).toBe('RUNNING')
      expect(task.toolKey).toBe('doc-review')
      expect(task.projectId).toBe(projects[0].id)
    })

    it('getTasksByProject filters by project', () => {
      ensureProjects()
      const projects = getProjects()
      createTask(projects[0].id, 'doc-review', {})
      createTask(projects[0].id, 'unit-test', {})
      const tasks = getTasksByProject(projects[0].id)
      expect(tasks).toHaveLength(2)
    })

    it('getTaskById finds task', () => {
      ensureProjects()
      const task = createTask(getProjects()[0].id, 'doc-review', {})
      expect(getTaskById(task.id)!.id).toBe(task.id)
    })

    it('updateTaskStatus changes status', () => {
      ensureProjects()
      const task = createTask(getProjects()[0].id, 'doc-review', {})
      updateTaskStatus(task.id, 'SUCCEEDED')
      expect(getTaskById(task.id)!.status).toBe('SUCCEEDED')
    })

    it('updateTaskStatus sets error message on failure', () => {
      ensureProjects()
      const task = createTask(getProjects()[0].id, 'doc-review', {})
      updateTaskStatus(task.id, 'FAILED', 'Something went wrong')
      const updated = getTaskById(task.id)!
      expect(updated.status).toBe('FAILED')
      expect(updated.errorMessage).toBe('Something went wrong')
    })
  })

  describe('files', () => {
    it('getProjectFiles returns default structure', () => {
      ensureProjects()
      const projects = getProjects()
      const files = getProjectFiles(projects[0].id)
      expect(Array.isArray(files)).toBe(true)
    })

    it('getFileContent returns empty for unknown path', () => {
      ensureProjects()
      const projects = getProjects()
      expect(getFileContent(projects[0].id, 'unknown.ts')).toBe('')
    })

    it('saveFileContent and getFileContent round-trip', () => {
      ensureProjects()
      const projects = getProjects()
      saveFileContent(projects[0].id, 'test.ts', 'const x = 1;')
      expect(getFileContent(projects[0].id, 'test.ts')).toBe('const x = 1;')
    })
  })
})
