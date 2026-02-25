import { defaultProjects, tools } from '../mock/data'
import type { ProjectItem } from '../mock/data'
export type FileNode = { name: string; type: 'file' | 'dir'; children?: FileNode[] }

export type TaskStatus = 'RUNNING' | 'SUCCEEDED' | 'FAILED'

export type TaskItem = {
  id: string
  projectId: string
  projectName: string
  toolKey: string
  toolName: string
  status: TaskStatus
  createdAt: string
  params: Record<string, string>
  errorMessage?: string
}

const PROJECT_KEY = 'uni-portal-projects'
const TASK_KEY = 'uni-portal-tasks'
const FILES_KEY_PREFIX = 'uni-portal-files-'
const FILES_CONTENT_KEY_PREFIX = 'uni-portal-file-contents-'

const load = <T>(key: string, fallback: T): T => {
  const raw = localStorage.getItem(key)
  if (!raw) {
    return fallback
  }
  try {
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

const save = (key: string, value: unknown) => {
  localStorage.setItem(key, JSON.stringify(value))
}

export const ensureProjects = () => {
  const existing = load(PROJECT_KEY, null as unknown as TaskItem[] | null)
  if (!existing) {
    save(PROJECT_KEY, defaultProjects)
  }
}

export const getProjects = () => {
  ensureProjects()
  return load(PROJECT_KEY, defaultProjects)
}

export const getProjectById = (projectId: string) => {
  const projects = getProjects()
  return projects.find((item) => item.id === projectId)
}

const generateProjectId = () => {
  return `P-${Date.now()}-${Math.floor(Math.random() * 1000)}`
}

export const addProject = (payload: {
  name: string
  description: string
  repoUrl?: string
  uploadFileName?: string
  uploadFolderName?: string
}): ProjectItem & { repoUrl?: string; uploadFileName?: string; uploadFolderName?: string } => {
  const projects = getProjects() as (ProjectItem & {
    repoUrl?: string
    uploadFileName?: string
    uploadFolderName?: string
  })[]
  const project = {
    id: generateProjectId(),
    name: payload.name,
    description: payload.description,
    repoUrl: payload.repoUrl,
    uploadFileName: payload.uploadFileName,
    uploadFolderName: payload.uploadFolderName
  }
  const next = [project, ...projects]
  save(PROJECT_KEY, next)
  // 初始化项目文件树（示例）
  const sampleFiles: FileNode[] = [
    {
      name: 'src',
      type: 'dir',
      children: [
        { name: 'main.ts', type: 'file' },
        { name: 'App.vue', type: 'file' },
        {
          name: 'modules',
          type: 'dir',
          children: [{ name: 'core.ts', type: 'file' }, { name: 'utils.ts', type: 'file' }]
        }
      ]
    },
    {
      name: 'docs',
      type: 'dir',
      children: [{ name: 'README.md', type: 'file' }]
    },
    { name: 'package.json', type: 'file' }
  ]
  save(FILES_KEY_PREFIX + project.id, sampleFiles)
  const initContents: Record<string, string> = {
    'src/main.ts': "console.log('hello')\n",
    'src/App.vue': '<template>\n  <div>App</div>\n</template>\n',
    'src/modules/core.ts': 'export const core = () => {}\n',
    'src/modules/utils.ts': 'export const utils = () => {}\n',
    'docs/README.md': '# 项目说明\n',
    'package.json': '{\n  "name": "demo"\n}\n'
  }
  save(FILES_CONTENT_KEY_PREFIX + project.id, initContents)
  return project
}

export const updateProject = (projectId: string, payload: Partial<ProjectItem>) => {
  const projects = getProjects()
  const index = projects.findIndex((p) => p.id === projectId)
  if (index !== -1) {
    const updated = { ...projects[index], ...payload }
    projects[index] = updated
    save(PROJECT_KEY, projects)
    return updated
  }
  throw new Error('Project not found')
}

const ensureTasks = () => {
  const existing = load(TASK_KEY, null as unknown as TaskItem[] | null)
  if (!existing) {
    save(TASK_KEY, [])
  }
}

export const getTasks = () => {
  ensureTasks()
  return load(TASK_KEY, [] as TaskItem[])
}

export const getTasksByProject = (projectId: string) => {
  return getTasks().filter((task) => task.projectId === projectId)
}

export const getTaskById = (taskId: string) => {
  return getTasks().find((task) => task.id === taskId)
}

const generateId = () => {
  return `T-${Date.now()}-${Math.floor(Math.random() * 1000)}`
}

export const createTask = (
  projectId: string,
  toolKey: string,
  params: Record<string, string>
) => {
  const project = getProjectById(projectId)
  const tool = tools.find((item) => item.key === toolKey)
  const task: TaskItem = {
    id: generateId(),
    projectId,
    projectName: project?.name || '未知项目',
    toolKey,
    toolName: tool?.name || '未知工具',
    status: 'RUNNING',
    createdAt: new Date().toISOString(),
    params
  }
  const tasks = getTasks()
  const next = [task, ...tasks]
  save(TASK_KEY, next)
  return task
}

export const updateTaskStatus = (taskId: string, status: TaskStatus, errorMessage?: string) => {
  const tasks = getTasks()
  const next = tasks.map((task) =>
    task.id === taskId ? { ...task, status, errorMessage } : task
  )
  save(TASK_KEY, next)
}

export const getProjectFiles = (projectId: string): FileNode[] => {
  const key = FILES_KEY_PREFIX + projectId
  const existing = load<FileNode[] | null>(key, null as unknown as FileNode[] | null)
  if (existing) return existing
  const fallback: FileNode[] = [
    { name: 'README.md', type: 'file' },
    { name: 'src', type: 'dir', children: [{ name: 'index.ts', type: 'file' }] }
  ]
  save(key, fallback)
  return fallback
}

export const getFileContent = (projectId: string, path: string): string => {
  const key = FILES_CONTENT_KEY_PREFIX + projectId
  const map = load<Record<string, string>>(key, {})
  return map[path] ?? ''
}

export const saveFileContent = (projectId: string, path: string, content: string) => {
  const key = FILES_CONTENT_KEY_PREFIX + projectId
  const map = load<Record<string, string>>(key, {})
  map[path] = content
  save(key, map)
}
