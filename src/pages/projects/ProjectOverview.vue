<template>
  <div class="overview-container">
    <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <p>加载中...</p>
    </div>
    
    <div v-else-if="project" class="content">
        <div class="header">
            <div class="header-info">
                <h2>{{ project.name }}</h2>
                <div class="meta-row">
                    <span class="meta-item">创建于 {{ formatDate(project.created_at) }}</span>
                    <span class="meta-divider">|</span>
                    <span class="meta-item">ID: {{ project.project_id }}</span>
                </div>
            </div>
            <div class="actions">
                <button class="btn-primary" @click="goToUpload">上传软件项目</button>
            </div>
        </div>
        
        <div class="description-card">
            <h3>工程描述</h3>
            <p>{{ project.description || '暂无描述' }}</p>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon bg-blue">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                        <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
                        <line x1="12" y1="22.08" x2="12" y2="12"></line>
                    </svg>
                </div>
                <div class="stat-content">
                    <div class="label">软件项目数量</div>
                    <div class="value">{{ project.item_count || 0 }}</div>
                </div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon bg-green">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="17 8 12 3 7 8"></polyline>
                        <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                </div>
                <div class="stat-content">
                    <div class="label">最近上传时间</div>
                    <div class="value date-value">{{ project.last_upload_at ? formatDate(project.last_upload_at, true) : '-' }}</div>
                </div>
            </div>

            <div class="stat-card">
                <div class="stat-icon bg-purple">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12 6 12 12 16 14"></polyline>
                    </svg>
                </div>
                <div class="stat-content">
                    <div class="label">最近更新时间</div>
                    <div class="value date-value">{{ formatDate(project.updated_at, true) }}</div>
                </div>
            </div>
        </div>

        <ProjectDashboard :data="dashboardData" :loading="dashboardLoading" />
    </div>
    
    <div v-else class="error-state">
        <p>工程不存在或无权访问</p>
        <button class="btn-secondary" @click="router.push('/projects')">返回列表</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getProject } from '../../api/projects'
import type { Project } from '../../api/projects'
import { getDashboardData } from '../../mock/dashboard'
import type { DashboardData } from '../../mock/dashboard'
import ProjectDashboard from '../../components/ProjectDashboard.vue'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string
const project = ref<Project | null>(null)
const loading = ref(true)

const dashboardData = ref<DashboardData | null>(null)
const dashboardLoading = ref(false)

const fetchProject = async () => {
    try {
        loading.value = true
        const res: any = await getProject(projectId)
        if (res.code === 200) {
            project.value = res.data
            // 获取 Dashboard 数据
            fetchDashboard()
        }
    } catch (error) {
        console.error('Failed to fetch project', error)
    } finally {
        loading.value = false
    }
}

const fetchDashboard = async () => {
    dashboardLoading.value = true
    try {
        dashboardData.value = await getDashboardData(projectId)
    } catch (error) {
        console.error('Failed to fetch dashboard data', error)
    } finally {
        dashboardLoading.value = false
    }
}

const formatDate = (dateStr: string, includeTime = false) => {
    const options: Intl.DateTimeFormatOptions = {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    }
    if (includeTime) {
        options.hour = '2-digit'
        options.minute = '2-digit'
    }
    return new Date(dateStr).toLocaleString('zh-CN', options)
}

const goToUpload = () => {
    // Navigate to Items page and trigger upload (via query param or similar mechanism)
    // Or simpler: just navigate to items page, user can click upload there
    router.push({
        name: 'ProjectItems',
        params: { projectId },
        query: { action: 'upload' }
    })
}

onMounted(() => {
    fetchProject()
})
</script>

<style scoped>
.overview-container {
    padding: 24px;
    max-width: 1000px;
    margin: 0 auto;
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

.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 32px;
}

.header h2 {
    font-size: 28px;
    font-weight: 600;
    color: #1e293b;
    margin: 0 0 8px 0;
}

.meta-row {
    display: flex;
    align-items: center;
    color: #64748b;
    font-size: 14px;
}

.meta-divider {
    margin: 0 12px;
    color: #cbd5e1;
}

.btn-primary {
    background: #1e40af;
    color: white;
    padding: 10px 24px;
    border-radius: 8px;
    border: none;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.2s;
    font-size: 14px;
}

.btn-primary:hover {
    background: #1e3a8a;
}

.description-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 24px;
}

.description-card h3 {
    font-size: 16px;
    font-weight: 600;
    color: #1e293b;
    margin: 0 0 12px 0;
}

.description-card p {
    color: #475569;
    line-height: 1.6;
    margin: 0;
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 20px;
}

.stat-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px;
    display: flex;
    align-items: center;
    gap: 16px;
}

.stat-icon {
    width: 48px;
    height: 48px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
}

.bg-blue { background: #eff6ff; color: #3b82f6; }
.bg-green { background: #f0fdf4; color: #22c55e; }
.bg-purple { background: #f5f3ff; color: #8b5cf6; }

.stat-content {
    flex: 1;
}

.stat-content .label {
    font-size: 13px;
    color: #64748b;
    margin-bottom: 4px;
}

.stat-content .value {
    font-size: 18px;
    font-weight: 600;
    color: #1e293b;
}

.stat-content .value.highlight {
    font-size: 24px;
    color: #1e40af;
}

.stat-content .date-value {
    font-size: 16px;
}

.error-state {
    text-align: center;
    padding: 60px 0;
}

.error-state p {
    color: #ef4444;
    margin-bottom: 16px;
}

.btn-secondary {
    padding: 8px 16px;
    background: white;
    border: 1px solid #cbd5e1;
    color: #64748b;
    border-radius: 6px;
    cursor: pointer;
}
</style>
