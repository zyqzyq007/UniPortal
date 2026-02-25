<template>
  <div class="dashboard-container" ref="containerRef" @scroll="handleScroll">
    <!-- 错误状态显示 -->
    <div v-if="loadError" class="error-container">
      <div class="error-content">
        <div class="error-icon">😕</div>
        <h2>项目加载失败</h2>
        <p class="error-msg">{{ loadErrorMessage }}</p>
        <div class="error-actions">
          <button v-if="!isNotFound" class="btn btn-primary" @click="fetchProjectData">重试</button>
          <RouterLink class="btn btn-outline" to="/projects">返回项目列表</RouterLink>
        </div>
      </div>
    </div>

    <div v-else class="dashboard" :style="{ transform: `translateY(${contentOffset}px)` }">
      <!-- 1. 项目基本信息 -->
      <header class="project-header">
        <div class="header-content" v-if="!isEditing">
          <div class="title-row">
            <h2>{{ project?.name || '加载中...' }}</h2>
            <button class="btn-icon" @click="startEdit" title="编辑项目信息">
              ✎
            </button>
          </div>
          <p class="desc">{{ project?.description || '暂无描述' }}</p>
        </div>
        <div class="header-content edit-mode" v-else>
          <div class="form-group">
            <input 
              v-model="editForm.name" 
              class="input-name" 
              placeholder="项目名称（必填，最大50字符）"
              maxlength="50"
            />
            <span class="error-text" v-if="editErrors.name">项目名称不能为空</span>
          </div>
          <div class="form-group">
            <textarea 
              v-model="editForm.description" 
              class="input-desc" 
              placeholder="项目描述（最大500字符）"
              maxlength="500"
              rows="3"
            ></textarea>
          </div>
          <div class="edit-actions">
            <button class="btn btn-primary btn-sm" @click="saveProject" :disabled="saving">
              {{ saving ? '保存中...' : '保存' }}
            </button>
            <button class="btn btn-outline btn-sm" @click="cancelEdit" :disabled="saving">取消</button>
          </div>
          <p class="error-text" v-if="saveError">{{ saveError }}</p>
        </div>
        
        <div class="header-right">
          <RouterLink class="btn btn-outline" to="/projects">项目列表</RouterLink>
        </div>
      </header>

      <div class="main-layout">
        <!-- 2. 左侧主区域：文件结构 + 快捷入口 -->
        <div class="left-column">
          <!-- 2.1 文件结构 -->
          <div class="card file-tree-card">
            <div class="card-header">
              <h3>项目文件结构</h3>
            </div>
            <div class="tree-container">
              <FileTree :nodes="files" :activePath="activePath" @open-file="onOpenFile" />
            </div>
          </div>

          <!-- 2.2 核心入口 -->
          <div class="quick-actions">
            <RouterLink :to="`/projects/${projectId}/tools`" class="action-card tool-card">
              <div class="icon">🛠️</div>
              <div class="info">
                <h4>工具中心</h4>
                <p>六大工具一键接入</p>
              </div>
              <span class="arrow">→</span>
            </RouterLink>
            
            <RouterLink :to="`/projects/${projectId}/tasks`" class="action-card task-card">
              <div class="icon">📋</div>
              <div class="info">
                <h4>任务中心</h4>
                <p>查看所有任务状态</p>
              </div>
              <span class="arrow">→</span>
            </RouterLink>
          </div>
        </div>

        <!-- 3. 右侧区域：编辑器 + 任务状态概览 -->
        <div class="right-column">
          <div class="card editor-card">
            <h3>编辑器</h3>
            <div class="editor-container">
              <EditorPane :projectId="projectId" :filePath="activePath" :fileType="activeType" />
            </div>
          </div>
          <div class="card stats-card">
            <h3>任务状态概览</h3>
            <div class="stats-list">
              <div class="stat-item total">
                <span class="label">任务总数</span>
                <span class="value">{{ totalTasks }}</span>
              </div>
              <div class="stat-item running">
                <span class="label">运行中</span>
                <span class="value">{{ runningTasks }}</span>
              </div>
              <div class="stat-item failed">
                <span class="label">已失败</span>
                <span class="value">{{ failedTasks }}</span>
              </div>
            </div>
            <div class="stats-footer">
              <RouterLink :to="`/projects/${projectId}/tasks`" class="link">查看详情</RouterLink>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 滚动提示 -->
    <Transition name="fade">
      <div v-if="showScrollIndicator" class="scroll-indicator" @click="scrollToBottom">
        <span class="arrow-down">↓</span>
        <span class="text">下滑查看更多</span>
      </div>
    </Transition>
    
    <!-- 底部渐变遮罩 -->
    <div class="scroll-mask" :class="{ visible: showScrollIndicator }"></div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import FileTree from '../../components/FileTree.vue'
import EditorPane from '../../components/EditorPane.vue'
import { getProject, updateProject, getProjectStructure } from '../../api/projects'
import type { Project } from '../../api/projects'
// Tasks API would be similar, skipping for now as not requested in core plan but keeping mock for display
import { getTasksByProject } from '../../store/mockStore'
import type { TaskItem } from '../../store/mockStore' // Import from store file where it's defined

const route = useRoute()
const projectId = computed(() => route.params.projectId as string)
const files = ref([])
const project = ref<Project | undefined>()
const tasks = ref<TaskItem[]>([])
const activePath = ref<string>('')
const activeType = ref<string>('')
const loadError = ref(false)
const loadErrorMessage = ref('')

// 编辑状态
const isEditing = ref(false)
const saving = ref(false)
const saveError = ref('')
const editForm = reactive({
  name: '',
  description: ''
})
const editErrors = reactive({
  name: false
})

const startEdit = () => {
  if (project.value) {
    editForm.name = project.value.name
    editForm.description = project.value.description || ''
    isEditing.value = true
    saveError.value = ''
    editErrors.name = false
  }
}

const cancelEdit = () => {
  isEditing.value = false
  saveError.value = ''
}

const saveProject = async () => {
  // 验证
  if (!editForm.name.trim()) {
    editErrors.name = true
    return
  }
  editErrors.name = false
  
  saving.value = true
  saveError.value = ''
  
  try {
    const res: any = await updateProject(projectId.value, {
      name: editForm.name,
      description: editForm.description
    })
    project.value = res.data
    isEditing.value = false
  } catch (e: any) {
    saveError.value = e.message || '保存失败，请稍后重试'
    console.error(e)
  } finally {
    saving.value = false
  }
}

const totalTasks = computed(() => tasks.value.length)
const runningTasks = computed(() => tasks.value.filter((t: TaskItem) => t.status === 'RUNNING').length)
const failedTasks = computed(() => tasks.value.filter((t: TaskItem) => t.status === 'FAILED').length)

// 滚动交互逻辑
const containerRef = ref<HTMLElement | null>(null)
const showScrollIndicator = ref(false)
const contentOffset = ref(0)
let lastScrollTop = 0

const checkScroll = () => {
  const el = containerRef.value
  if (!el) return
  
  // 检查是否可滚动且未滚动到底部 (容差 20px)
  const isScrollable = el.scrollHeight > el.clientHeight
  const isAtBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 20
  
  showScrollIndicator.value = isScrollable && !isAtBottom
}

const handleScroll = () => {
  checkScroll()
  
  // 简单的滚动反馈效果
  const el = containerRef.value
  if (el) {
    const currentScroll = el.scrollTop
    const diff = currentScroll - lastScrollTop
    
    // 向下滑动时产生微小的位移反馈，但限制最大值防止抖动
    if (diff > 0 && currentScroll < 100) {
      contentOffset.value = Math.min(diff * 0.1, 5)
    } else {
      contentOffset.value = 0
    }
    
    lastScrollTop = currentScroll
  }
}

const scrollToBottom = () => {
  containerRef.value?.scrollTo({
    top: containerRef.value.scrollHeight,
    behavior: 'smooth'
  })
}

const fetchProjectData = async () => {
  loadError.value = false
  loadErrorMessage.value = ''
  
  if (!projectId.value) {
    loadError.value = true
    loadErrorMessage.value = '无效的项目ID'
    return
  }

  try {
    const [projRes, structRes] = await Promise.all([
      getProject(projectId.value),
      getProjectStructure(projectId.value).catch(() => ({ data: { name: 'root', type: 'directory', children: [] } }))
    ])
    project.value = (projRes as any).data
    
    const root = (structRes as any).data
    files.value = root.children || [] // Display children of root
    
    // Keep mock tasks for now
    tasks.value = getTasksByProject(projectId.value)
    
    const firstFile = findFirstFile(files.value)
    if (firstFile) activePath.value = firstFile
  } catch (e: any) {
    console.error('Failed to load project', e)
    loadError.value = true
    if (e.code === 404) {
      loadErrorMessage.value = '未找到该项目，可能已被删除或无权限访问'
    } else if (e.code === 403) {
      loadErrorMessage.value = '您没有权限访问该项目'
    } else if (e.code === 503) {
      loadErrorMessage.value = '后端服务不可用，请确认服务已启动并监听 8080'
    } else {
      loadErrorMessage.value = e.message || '加载项目失败，请稍后重试'
    }
  }
}

onMounted(() => {
  fetchProjectData()
  
  // 初始化检查滚动状态 (延迟确保 DOM 渲染)
  setTimeout(checkScroll, 100)
  window.addEventListener('resize', checkScroll)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkScroll)
})

const onOpenFile = (payload: { path: string; type: string }) => {
  activePath.value = payload.path
  activeType.value = payload.type
}

const findFirstFile = (list: any[]): string | null => {
  for (const n of list) {
    if (n.type === 'file') return n.name
    if (n.type === 'dir' && n.children && n.children.length) {
      const sub = findFirstFile(n.children.map((c: any) => ({ ...c, name: `${n.name}/${c.name}` })))
      if (sub) return sub
    }
  }
  return null
}
const isNotFound = computed(() => loadErrorMessage.value.includes('未找到') || loadErrorMessage.value.includes('无效'))
</script>

<style scoped>
.dashboard-container {
  height: 100%;
  overflow-y: auto;
  position: relative;
  scroll-behavior: smooth;
  -webkit-overflow-scrolling: touch; /* iOS 惯性滚动 */
}

.dashboard {
  max-width: 1200px;
  margin: 0 auto;
  padding-bottom: 60px; /* 底部留白 */
  transition: transform 0.1s ease-out; /* 平滑位移过渡 */
}

.project-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.header-content {
  flex: 1;
  margin-right: 24px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 16px;
  color: #64748b;
  padding: 4px;
  border-radius: 4px;
}
.btn-icon:hover {
  background: #f1f5f9;
  color: var(--color-primary-600);
}

.project-header h2 {
  font-size: 24px;
  color: #1e293b;
  margin: 0;
}

.desc {
  color: #64748b;
  margin: 0;
  line-height: 1.5;
}

.btn-outline {
  padding: 8px 16px;
  border: 1px solid var(--color-primary-600);
  border-radius: 6px;
  color: var(--color-primary-600);
  background: transparent;
  text-decoration: none;
  font-size: 14px;
  transition: all 0.2s;
  white-space: nowrap;
}

.btn-outline:hover {
  border-color: var(--color-primary-900);
  color: var(--color-primary-900);
  background: #eff6ff;
}

/* 编辑模式样式 */
.edit-mode {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
}

.input-name {
  font-size: 20px;
  font-weight: 600;
  padding: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  width: 100%;
  max-width: 400px;
}

.input-desc {
  font-size: 14px;
  padding: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  width: 100%;
  max-width: 600px;
  resize: vertical;
}

.edit-actions {
  display: flex;
  gap: 12px;
}

.btn-sm {
  padding: 6px 12px;
  font-size: 13px;
}

.btn-primary {
  background: var(--color-primary-600);
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.btn-primary:hover {
  background: var(--color-primary-700);
}
.btn-primary:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

.error-text {
  color: #dc2626;
  font-size: 12px;
  margin-top: 4px;
}

.main-layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 24px;
}

.left-column {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.right-column {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.file-tree-card {
  flex: 1;
  min-height: 400px;
  display: flex;
  flex-direction: column;
}

.card-header {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
}

.card-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-text-primary);
}

.tree-container {
  flex: 1;
  overflow-y: auto;
  max-height: 500px;
}

.editor-card {
  background: white;
  padding: 0;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}
.editor-card h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-text-primary);
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
}
.editor-container {
  height: 420px;
}

.quick-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  text-decoration: none;
  transition: all 0.2s;
}

.action-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(30, 58, 138, 0.08);
  border-color: var(--color-primary-600);
}

.action-card .icon {
  font-size: 24px;
  width: 48px;
  height: 48px;
  background: #eff6ff;
  color: var(--color-primary-600);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.task-card .icon {
  background: #dcfce7;
  color: var(--color-success-600);
}

.info h4 {
  margin: 0 0 4px 0;
  color: var(--color-text-primary);
  font-size: 16px;
}

.info p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.arrow {
  margin-left: auto;
  color: #cbd5e1;
  font-weight: bold;
}

.stats-card {
  background: white;
  padding: 24px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  height: fit-content;
}

.stats-card h3 {
  margin: 0 0 20px 0;
  font-size: 16px;
  color: var(--color-text-primary);
}

.stats-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  border-radius: 8px;
  background: #f8fafc;
}

.stat-item .label {
  color: #64748b;
  font-size: 14px;
}

.stat-item .value {
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.stat-item.running .value {
  color: var(--color-primary-600);
}

.stat-item.failed .value {
  color: #b91c1c;
}

.stats-footer {
  margin-top: 20px;
  text-align: right;
}

.stats-footer .link {
  color: #64748b;
  font-size: 13px;
  text-decoration: none;
}

.stats-footer .link:hover {
  color: var(--color-primary-600);
}

@media (max-width: 768px) {
  .main-layout {
    grid-template-columns: 1fr;
  }
  
  .quick-actions {
    grid-template-columns: 1fr;
  }
}

/* 滚动提示样式 */
.scroll-indicator {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  color: var(--color-primary-600);
  cursor: pointer;
  z-index: 20;
  animation: bounce 2s infinite;
}

.arrow-down {
  font-size: 24px;
  font-weight: bold;
}

.text {
  font-size: 12px;
  opacity: 0.8;
}

@keyframes bounce {
  0%, 20%, 50%, 80%, 100% {
    transform: translateX(-50%) translateY(0);
  }
  40% {
    transform: translateX(-50%) translateY(-10px);
  }
  60% {
    transform: translateX(-50%) translateY(-5px);
  }
}

/* 底部渐变遮罩 */
.scroll-mask {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 80px;
  background: linear-gradient(to top, rgba(255,255,255,0.9), transparent);
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.3s;
  z-index: 10;
}

.scroll-mask.visible {
  opacity: 1;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 错误状态样式 */
.error-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  padding: 40px;
}

.error-content {
  text-align: center;
  background: white;
  padding: 40px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  max-width: 400px;
  width: 100%;
}

.error-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.error-content h2 {
  font-size: 20px;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.error-msg {
  color: #64748b;
  margin: 0 0 24px 0;
}

.error-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
}
</style>
