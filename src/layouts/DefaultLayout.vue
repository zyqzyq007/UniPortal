<template>
  <div class="layout">
    <header class="topbar">
      <div class="topbar-left">
        <div class="brand">智能装备测试一体化平台</div>
        <div class="divider">/</div>
        <div class="project-info">
            <span class="label">当前工程：</span>
            <span class="name">{{ projectName }}</span>
        </div>
      </div>
      <div class="topbar-right">
        <button class="switch-btn" @click="switchProject" :disabled="isSwitching">
            <span v-if="isSwitching" class="spinner"></span>
            <span v-else>切换工程</span>
        </button>
        <RouterLink to="/profile" class="user">
            <div class="avatar">{{ username.charAt(0).toUpperCase() }}</div>
            <span>{{ username }}</span>
        </RouterLink>
        <button class="link logout" @click="logout">退出</button>
      </div>
    </header>
    
    <div class="project-tabs">
        <div class="tabs-container">
            <RouterLink :to="`/projects/${projectId}/overview`" class="tab-item" active-class="active">
                工程概览
            </RouterLink>
            <RouterLink :to="`/projects/${projectId}/items`" class="tab-item" active-class="active">
                项目管理
            </RouterLink>
            <RouterLink :to="`/projects/${projectId}/tools`" class="tab-item" active-class="active">
                工具中心
            </RouterLink>
            <RouterLink :to="`/projects/${projectId}/tasks`" class="tab-item" active-class="active">
                任务中心
            </RouterLink>
        </div>
    </div>

    <div class="body">
      <main class="content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearToken, clearUser, getUserName } from '../utils/auth'
import { useProjectState } from '../store/projectState'

const route = useRoute()
const router = useRouter()
const { state, fetchProjectInfo, clearProject } = useProjectState()
const isSwitching = ref(false)

const projectId = computed(() => route.params.projectId as string)
const projectName = computed(() => state.currentProject?.name || '加载中...')
const username = computed(() => getUserName() || 'Guest')

// Watch route changes to update project info
watch(
  () => projectId.value,
  (newId) => {
    if (newId) {
      fetchProjectInfo(newId)
    } else {
      clearProject()
    }
  },
  { immediate: true }
)

const switchProject = async () => {
    isSwitching.value = true
    // Simulate a small delay for smooth transition feel if needed, or just push
    await new Promise(resolve => setTimeout(resolve, 300))
    await router.push('/project-management')
    isSwitching.value = false
}

const logout = () => {
  clearToken()
  clearUser()
  router.push('/login')
}
</script>

<style scoped>
.layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: #f8fafc;
}

.topbar {
  height: 60px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  z-index: 10;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand {
  font-size: 18px;
  font-weight: 700;
  color: #1e40af; /* 主色调 */
}

.divider {
    color: #cbd5e1;
    font-size: 20px;
}

.project-info {
    display: flex;
    align-items: center;
    gap: 8px;
}

.project-info .label {
    color: #64748b;
    font-size: 14px;
}

.project-info .name {
    font-weight: 600;
    color: #1e293b;
    font-size: 15px;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 24px;
}

.switch-btn {
    background-color: #1e40af;
    color: white;
    border: none;
    padding: 6px 16px;
    border-radius: 4px;
    font-size: 14px;
    cursor: pointer;
    transition: background-color 0.2s;
    display: flex;
    align-items: center;
    gap: 8px;
    height: 32px;
}

.switch-btn:hover {
    background-color: #1e3a8a;
}

.switch-btn:disabled {
    opacity: 0.7;
    cursor: not-allowed;
}

.spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255,255,255,0.3);
    border-radius: 50%;
    border-top-color: white;
    animation: spin 0.8s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.user {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  color: #334155;
  font-weight: 500;
  transition: opacity 0.2s;
}

.user:hover {
  opacity: 0.8;
}

.avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #e0e7ff;
    color: #3730a3;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 600;
    font-size: 14px;
}

.link {
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  font-size: 14px;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s;
}

.link:hover {
    background: #f1f5f9;
    color: #ef4444;
}

/* Tabs */
.project-tabs {
    background: white;
    border-bottom: 1px solid #e2e8f0;
    padding: 0 24px;
}

.tabs-container {
    display: flex;
    gap: 32px;
    max-width: 1200px;
    margin: 0 auto;
}

.tab-item {
    padding: 16px 4px;
    text-decoration: none;
    color: #64748b;
    font-size: 14px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
}

.tab-item:hover {
    color: #1e40af;
}

.tab-item.active {
    color: #1e40af;
    border-bottom-color: #1e40af;
}

.body {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.content {
  flex: 1;
  width: 100%;
}
</style>
