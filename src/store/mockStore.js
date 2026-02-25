import { defaultProjects, tools } from '../mock/data';
const PROJECT_KEY = 'uni-portal-projects';
const TASK_KEY = 'uni-portal-tasks';
const FILES_KEY_PREFIX = 'uni-portal-files-';
const FILES_CONTENT_KEY_PREFIX = 'uni-portal-file-contents-';
const load = (key, fallback) => {
    const raw = localStorage.getItem(key);
    if (!raw) {
        return fallback;
    }
    try {
        return JSON.parse(raw);
    }
    catch {
        return fallback;
    }
};
const save = (key, value) => {
    localStorage.setItem(key, JSON.stringify(value));
};
export const ensureProjects = () => {
    const existing = load(PROJECT_KEY, null);
    if (!existing) {
        save(PROJECT_KEY, defaultProjects);
    }
};
export const getProjects = () => {
    ensureProjects();
    return load(PROJECT_KEY, defaultProjects);
};
export const getProjectById = (projectId) => {
    const projects = getProjects();
    return projects.find((item) => item.id === projectId);
};
const generateProjectId = () => {
    return `P-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
};
export const addProject = (payload) => {
    const projects = getProjects();
    const project = {
        id: generateProjectId(),
        name: payload.name,
        description: payload.description,
        repoUrl: payload.repoUrl,
        uploadFileName: payload.uploadFileName,
        uploadFolderName: payload.uploadFolderName
    };
    const next = [project, ...projects];
    save(PROJECT_KEY, next);
    // 初始化项目文件树（示例）
    const sampleFiles = [
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
    ];
    save(FILES_KEY_PREFIX + project.id, sampleFiles);
    const initContents = {
        'src/main.ts': "console.log('hello')\n",
        'src/App.vue': '<template>\n  <div>App</div>\n</template>\n',
        'src/modules/core.ts': 'export const core = () => {}\n',
        'src/modules/utils.ts': 'export const utils = () => {}\n',
        'docs/README.md': '# 项目说明\n',
        'package.json': '{\n  "name": "demo"\n}\n'
    };
    save(FILES_CONTENT_KEY_PREFIX + project.id, initContents);
    return project;
};
export const updateProject = (projectId, payload) => {
    const projects = getProjects();
    const index = projects.findIndex((p) => p.id === projectId);
    if (index !== -1) {
        const updated = { ...projects[index], ...payload };
        projects[index] = updated;
        save(PROJECT_KEY, projects);
        return updated;
    }
    throw new Error('Project not found');
};
const ensureTasks = () => {
    const existing = load(TASK_KEY, null);
    if (!existing) {
        save(TASK_KEY, []);
    }
};
export const getTasks = () => {
    ensureTasks();
    return load(TASK_KEY, []);
};
export const getTasksByProject = (projectId) => {
    return getTasks().filter((task) => task.projectId === projectId);
};
export const getTaskById = (taskId) => {
    return getTasks().find((task) => task.id === taskId);
};
const generateId = () => {
    return `T-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
};
export const createTask = (projectId, toolKey, params) => {
    const project = getProjectById(projectId);
    const tool = tools.find((item) => item.key === toolKey);
    const task = {
        id: generateId(),
        projectId,
        projectName: project?.name || '未知项目',
        toolKey,
        toolName: tool?.name || '未知工具',
        status: 'RUNNING',
        createdAt: new Date().toISOString(),
        params
    };
    const tasks = getTasks();
    const next = [task, ...tasks];
    save(TASK_KEY, next);
    return task;
};
export const updateTaskStatus = (taskId, status, errorMessage) => {
    const tasks = getTasks();
    const next = tasks.map((task) => task.id === taskId ? { ...task, status, errorMessage } : task);
    save(TASK_KEY, next);
};
export const getProjectFiles = (projectId) => {
    const key = FILES_KEY_PREFIX + projectId;
    const existing = load(key, null);
    if (existing)
        return existing;
    const fallback = [
        { name: 'README.md', type: 'file' },
        { name: 'src', type: 'dir', children: [{ name: 'index.ts', type: 'file' }] }
    ];
    save(key, fallback);
    return fallback;
};
export const getFileContent = (projectId, path) => {
    const key = FILES_CONTENT_KEY_PREFIX + projectId;
    const map = load(key, {});
    return map[path] ?? '';
};
export const saveFileContent = (projectId, path, content) => {
    const key = FILES_CONTENT_KEY_PREFIX + projectId;
    const map = load(key, {});
    map[path] = content;
    save(key, map);
};
