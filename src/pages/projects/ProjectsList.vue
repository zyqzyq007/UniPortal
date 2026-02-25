<template>
  <div class="container">
    <div class="page-title">
      <div class="left-actions">
        <button v-if="showBackButton" class="btn-back" @click="goBack" aria-label="返回上一页">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M20 12H4M4 12L10 6M4 12L10 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span>返回</span>
        </button>
        <h2>项目列表</h2>
      </div>
      <RouterLink class="btn btn-primary" to="/projects/upload">上传项目/仓库</RouterLink>
    </div>
    <div class="card-grid">
      <div 
        class="card" 
        v-for="project in projects" 
        :key="project.project_id"
        :class="{ 'card-active': activeCardId === project.project_id }"
        @click="handleCardClick(project.project_id)"
        @touchstart="handleTouchStart(project.project_id)"
        role="button"
        aria-label="双击进入项目详情"
        tabindex="0"
      >
        <div class="card-content">
          <h3>{{ project.name }}</h3>
          <p :class="{ 'placeholder': !project.description }">
            {{ project.description || '暂无描述' }}
          </p>
        </div>
        <RouterLink class="btn-enter" :to="`/projects/${project.project_id}`" @click.stop>进入项目</RouterLink>
        <button class="btn-delete" @click.stop="confirmDelete(project)" title="删除项目">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
        </button>
      </div>
    </div>

    <!-- 删除确认弹窗 -->
    <div v-if="showDeleteModal" class="modal-overlay">
      <div class="modal-content">
        <h3>确认删除</h3>
        <p>您确定要删除项目 "{{ projectToDelete?.name }}" 吗？此操作无法撤销。</p>
        <div class="modal-actions">
          <button class="btn-cancel" @click="cancelDelete" :disabled="isDeleting">取消</button>
          <button class="btn-confirm-delete" @click="handleDelete" :disabled="isDeleting">
            {{ isDeleting ? '删除中...' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getProjects, deleteProject } from '../../api/projects'
import type { Project } from '../../api/projects'

const router = useRouter()
const projects = ref<Project[]>([])
const loading = ref(true)
const activeCardId = ref<string | null>(null)

// 删除相关状态
const showDeleteModal = ref(false)
const projectToDelete = ref<Project | null>(null)
const isDeleting = ref(false)

// 双击检测状态
let lastClickTime = 0
let lastClickId = ''
let clickTimeout: ReturnType<typeof setTimeout> | null = null

// 检查是否应该显示返回按钮
const showBackButton = computed(() => {
  const state = window.history.state
  const back = state?.back
  // 如果没有历史记录，或者上一页是登录页，则不显示返回按钮
  return back && typeof back === 'string' && !back.includes('/login')
})

const fetchProjects = async () => {
  try {
    loading.value = true
    const res: any = await getProjects()
    projects.value = res.data
  } catch (error) {
    console.error('Failed to fetch projects', error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchProjects()
})

const goBack = () => {
  router.back()
}

const confirmDelete = (project: Project) => {
  projectToDelete.value = project
  showDeleteModal.value = true
}

const cancelDelete = () => {
  showDeleteModal.value = false
  projectToDelete.value = null
}

const handleDelete = async () => {
  if (!projectToDelete.value) return
  
  console.log('Deleting project:', projectToDelete.value)
  
  try {
    isDeleting.value = true
    await deleteProject(projectToDelete.value.project_id)
    console.log('Delete success')
    // 从列表中移除
    projects.value = projects.value.filter(p => p.project_id !== projectToDelete.value?.project_id)
    showDeleteModal.value = false
    projectToDelete.value = null
  } catch (error: any) {
    console.error('Delete failed', error)
    if (error.code === 404) {
      alert('项目不存在或已被删除，将从列表中移除')
      projects.value = projects.value.filter(p => p.project_id !== projectToDelete.value?.project_id)
      showDeleteModal.value = false
      projectToDelete.value = null
    } else {
      alert('删除失败，请重试')
    }
  } finally {
    isDeleting.value = false
  }
}

const handleCardClick = (id: string) => {
  const now = Date.now()
  
  // 触发视觉反馈
  activeCardId.value = id
  setTimeout(() => {
    activeCardId.value = null
  }, 200)

  // 双击逻辑：同一ID且时间间隔小于300ms
  if (id === lastClickId && now - lastClickTime < 300) {
    if (clickTimeout) clearTimeout(clickTimeout)
    // 双击触发
    router.push(`/projects/${id}`)
    lastClickId = ''
    lastClickTime = 0
  } else {
    // 单击
    lastClickId = id
    lastClickTime = now
    
    // 重置点击状态（防抖/防止误判）
    if (clickTimeout) clearTimeout(clickTimeout)
    clickTimeout = setTimeout(() => {
      lastClickId = ''
      lastClickTime = 0
    }, 300)
  }
}

// 移动端触摸支持优化
const handleTouchStart = (id: string) => {
  // 可以在这里添加额外的触摸逻辑，目前复用点击逻辑即可
  // 这里的touchstart主要用于更快的响应视觉反馈
  activeCardId.value = id
}
</script>

<style scoped>
.page-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.left-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.btn-back {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  padding: 0 16px 0 12px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s;
}

.btn-back:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.btn-back:active {
  transform: scale(0.98);
}

.btn-primary {
  background: #3b82f6;
  color: white;
  padding: 8px 16px;
  border-radius: 6px;
  text-decoration: none;
  font-size: 14px;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: #2563eb;
}

/* 卡片布局优化 */
.card-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px; /* 间距设置为12px */
}

.card {
  position: relative;
  /* 计算宽度：(100% - 3个间距) / 4 */
  width: calc((100% - 36px) / 4);
  height: 140px;
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 16px;
  box-sizing: border-box;
  transition: all 0.2s ease, transform 0.1s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  cursor: pointer;
  user-select: none; /* 防止双击选中文本 */
  touch-action: manipulation; /* 优化触摸响应 */
}

.card:hover {
  transform: translateY(-4px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
  border-color: #cbd5e1;
}

.card.card-active {
  transform: scale(0.98);
  background-color: #f8fafc;
  border-color: #93c5fd;
}

.card-content {
  flex: 1;
  overflow: hidden;
  pointer-events: none; /* 让点击事件穿透到 card */
}

.card h3 {
  margin: 0 0 12px 0;
  font-size: 18px;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card p {
  margin: 0;
  font-size: 14px;
  color: #64748b;
  line-height: 1.2;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card p.placeholder {
  color: #94a3b8;
}

.btn-enter {
  position: absolute;
  right: 15px;
  bottom: 15px;
  width: 80px;
  height: 32px;
  background: #3b82f6;
  color: white;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  text-decoration: none;
  transition: background 0.2s;
  z-index: 2; /* 确保按钮在卡片之上 */
}

.btn-enter:hover {
  background: #2563eb;
}

/* 响应式适配 */
@media (max-width: 1024px) {
  .card {
    /* 3列布局: (100% - 2个间距) / 3 */
    width: calc((100% - 24px) / 3);
  }
}

@media (max-width: 768px) {
  .btn-back {
    min-width: 48px;
    min-height: 48px;
    padding: 0 12px;
  }
  
  .card {
    /* 2列布局: (100% - 1个间距) / 2 */
    width: calc((100% - 12px) / 2);
  }
}

@media (max-width: 480px) {
  .card {
    /* 1列布局 */
    width: 100%;
  }
}

.btn-delete {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 28px;
  height: 28px;
  border-radius: 4px;
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  z-index: 5;
}

.btn-delete:hover {
  background: #fee2e2;
  color: #ef4444;
}

/* 模态框样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 100;
}

.modal-content {
  background: white;
  padding: 24px;
  border-radius: 12px;
  width: 90%;
  max-width: 400px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.modal-content h3 {
  margin: 0 0 12px 0;
  color: #1e293b;
  font-size: 18px;
}

.modal-content p {
  color: #64748b;
  margin: 0 0 24px 0;
  line-height: 1.5;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-cancel {
  padding: 8px 16px;
  border: 1px solid #cbd5e1;
  background: white;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
}

.btn-cancel:hover {
  background: #f8fafc;
  color: #1e293b;
}

.btn-confirm-delete {
  padding: 8px 16px;
  border: none;
  background: #ef4444;
  color: white;
  border-radius: 6px;
  cursor: pointer;
}

.btn-confirm-delete:hover {
  background: #dc2626;
}

.btn-confirm-delete:disabled {
  background: #fca5a5;
  cursor: not-allowed;
}
</style>
