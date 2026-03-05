<template>
  <div class="container">
    <div class="page-title">
      <div class="left-actions">
        <button
          type="button"
          class="btn-back"
          aria-label="返回上一页"
          @click="handleBack"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="m15 18-6-6 6-6"></path>
          </svg>
          <span>返回</span>
        </button>
        <h2>工程列表</h2>
      </div>
      <div class="right-actions">
        <RouterLink class="btn btn-primary" to="/projects/new">新建测试工程</RouterLink>
      </div>
    </div>

    <div class="filters">
        <div class="search-wrapper">
            <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input 
                v-model="searchQuery" 
                @input="handleSearch" 
                placeholder="搜索工程名称..." 
                class="search-input" 
            />
        </div>
        <select v-model="sortOrder" @change="handleSortChange" class="sort-select">
            <option value="desc">创建时间倒序</option>
            <option value="asc">创建时间正序</option>
        </select>
    </div>

    <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <p>加载中...</p>
    </div>

    <div v-else-if="projects.length === 0" class="empty-state">
        <div class="empty-content" @click="router.push('/projects/new')">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                <line x1="12" y1="11" x2="12" y2="17"></line>
                <line x1="9" y1="14" x2="15" y2="14"></line>
            </svg>
            <p>目前还没有任何工程，新建一个吧～</p>
        </div>
    </div>

    <div v-else class="project-list">
        <div class="card-grid">
            <div 
                class="card" 
                v-for="project in projects" 
                :key="project.project_id"
                @click="router.push(`/projects/${project.project_id}/overview`)"
            >
                <div class="card-content">
                    <h3>{{ project.name }}</h3>
                    <p :class="{ 'placeholder': !project.description }">
                        {{ project.description || '暂无描述' }}
                    </p>
                    <div class="card-meta">
                        <span class="date">{{ formatDate(project.created_at) }}</span>
                        <span class="count">{{ project.item_count || 0 }} 个项目</span>
                    </div>
                </div>
                
                <button class="btn-delete" @click.stop="confirmDelete(project)" title="删除工程">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        </div>

        <!-- Pagination -->
        <div v-if="totalPages > 1" class="pagination">
            <button :disabled="currentPage === 1" @click="changePage(currentPage - 1)">上一页</button>
            <span>{{ currentPage }} / {{ totalPages }}</span>
            <button :disabled="currentPage === totalPages" @click="changePage(currentPage + 1)">下一页</button>
        </div>
    </div>

    <!-- Delete Modal -->
    <div v-if="showDeleteModal" class="modal-overlay">
      <div class="modal-content">
        <h3>确认删除</h3>
        <p>您确定要删除工程 "{{ projectToDelete?.name }}" 吗？此操作将删除工程下的所有软件项目且无法撤销。</p>
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
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getProjects, deleteProject } from '../../api/projects'
import type { Project } from '../../api/projects'
import { debounce } from 'lodash-es'

const router = useRouter()
const route = useRoute()
const projects = ref<Project[]>([])
const loading = ref(true)
const searchQuery = ref('')
const sortOrder = ref<'asc' | 'desc'>('desc')
const currentPage = ref(1)
const totalPages = ref(1)
const PAGE_SIZE = 12

// Delete state
const showDeleteModal = ref(false)
const projectToDelete = ref<Project | null>(null)
const isDeleting = ref(false)

const fetchProjectsData = async () => {
    try {
        loading.value = true
        const res: any = await getProjects({
            search: searchQuery.value,
            sort: 'created_at', // currently we only support sort by created_at or name in UI, backend defaults to created_at
            order: sortOrder.value,
            page: currentPage.value,
            limit: PAGE_SIZE
        })
        
        if (res.code === 200) {
            projects.value = res.data.items
            totalPages.value = res.data.totalPages
            currentPage.value = res.data.page
        }
    } catch (error) {
        console.error('Failed to fetch projects', error)
    } finally {
        loading.value = false
    }
}

const handleSearch = debounce(() => {
    currentPage.value = 1
    fetchProjectsData()
}, 300)

const handleSortChange = () => {
    currentPage.value = 1
    fetchProjectsData()
}

const changePage = (page: number) => {
    currentPage.value = page
    fetchProjectsData()
}

const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    })
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
    try {
        isDeleting.value = true
        await deleteProject(projectToDelete.value.project_id)
        showDeleteModal.value = false
        projectToDelete.value = null
        fetchProjectsData() // Refresh list
    } catch (error) {
        console.error('Delete failed', error)
        alert('删除失败，请重试')
    } finally {
        isDeleting.value = false
    }
}

const handleBack = () => {
    if (window.history.length > 1) {
        router.back()
        return
    }
    if (route.path === '/project-management') {
        router.push('/projects')
        return
    }
    router.push('/profile')
}

onMounted(() => {
    fetchProjectsData()
})
</script>

<style scoped>
.container {
    padding: 24px;
    max-width: 1200px;
    margin: 0 auto;
}

.page-title {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
}

.left-actions {
    display: flex;
    align-items: center;
    gap: 12px;
}

.page-title h2 {
    font-size: 24px;
    font-weight: 600;
    color: #1e293b;
    margin: 0;
}

.btn-back {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 36px;
    padding: 0 12px 0 10px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: white;
    color: #334155;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-back:hover {
    border-color: #94a3b8;
    background: #f8fafc;
    color: #1e293b;
}

.btn-back:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
}

.btn-primary {
    background: #1e40af;
    color: white;
    padding: 10px 20px;
    border-radius: 8px;
    text-decoration: none;
    font-weight: 500;
    transition: background 0.2s;
}

.btn-primary:hover {
    background: #1e3a8a;
}

.filters {
    display: flex;
    gap: 16px;
    margin-bottom: 24px;
}

.search-wrapper {
    position: relative;
    flex: 1;
    max-width: 400px;
}

.search-icon {
    position: absolute;
    left: 12px;
    top: 50%;
    transform: translateY(-50%);
    color: #94a3b8;
}

.search-input {
    width: 100%;
    padding: 10px 12px 10px 40px;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s;
}

.search-input:focus {
    border-color: #3b82f6;
}

.sort-select {
    padding: 10px 16px;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    background: white;
    font-size: 14px;
    outline: none;
    cursor: pointer;
}

.loading-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 60px 0;
    color: #64748b;
}

.spinner {
    width: 40px;
    height: 40px;
    border: 3px solid #e2e8f0;
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 16px;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.empty-state {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 400px;
}

.empty-content {
    text-align: center;
    cursor: pointer;
    padding: 40px;
    border-radius: 16px;
    transition: background 0.2s;
}

.empty-content:hover {
    background: #f8fafc;
}

.empty-content p {
    margin-top: 16px;
    color: #64748b;
    font-size: 16px;
}

.card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 20px;
    margin-bottom: 24px;
}

.card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px;
    cursor: pointer;
    transition: all 0.2s;
    position: relative;
    height: 160px;
    display: flex;
    flex-direction: column;
}

.card:hover {
    transform: translateY(-4px);
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    border-color: #cbd5e1;
}

.card-content {
    flex: 1;
    display: flex;
    flex-direction: column;
}

.card h3 {
    margin: 0 0 8px 0;
    font-size: 18px;
    color: #1e293b;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-right: 24px; /* Space for delete button */
}

.card p {
    margin: 0;
    font-size: 14px;
    color: #64748b;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    flex: 1;
}

.card p.placeholder {
    color: #94a3b8;
}

.card-meta {
    margin-top: 16px;
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #94a3b8;
}

.btn-delete {
    position: absolute;
    top: 16px;
    right: 16px;
    background: transparent;
    border: none;
    color: #94a3b8;
    cursor: pointer;
    padding: 4px;
    border-radius: 4px;
    transition: all 0.2s;
    opacity: 0;
}

.card:hover .btn-delete {
    opacity: 1;
}

.btn-delete:hover {
    background: #fee2e2;
    color: #ef4444;
}

.pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 16px;
    margin-top: 24px;
}

.pagination button {
    padding: 8px 16px;
    border: 1px solid #e2e8f0;
    background: white;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
}

.pagination button:disabled {
    background: #f1f5f9;
    color: #94a3b8;
    cursor: not-allowed;
}

/* Modal Styles */
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
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
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

.btn-confirm-delete {
    padding: 8px 16px;
    border: none;
    background: #ef4444;
    color: white;
    border-radius: 6px;
    cursor: pointer;
}
</style>
