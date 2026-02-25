<template>
  <div class="layout">
    <header class="topbar">
      <div class="topbar-left">
        <div class="brand">一体化测试平台</div>
        <RouterLink class="project project-link" to="/projects">项目：{{ projectName }}</RouterLink>
      </div>
      <div class="topbar-right">
        <RouterLink to="/profile" class="user">{{ username }}</RouterLink>
        <button class="link" @click="logout">退出</button>
      </div>
    </header>
    <div class="body">
      <aside class="sidebar">
        <RouterLink :to="`/projects/${projectId}`" class="nav-item">项目概览</RouterLink>
        <RouterLink :to="`/projects/${projectId}/tools`" class="nav-item">工具中心</RouterLink>
        <RouterLink :to="`/projects/${projectId}/tasks`" class="nav-item">任务中心</RouterLink>
      </aside>
      <main class="content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearToken, clearUser, getUserName } from '../utils/auth'
import { useProjectState } from '../store/projectState'

const route = useRoute()
const router = useRouter()
const { state, fetchProjectInfo, clearProject } = useProjectState()

const projectId = computed(() => route.params.projectId as string)
const projectName = computed(() => state.currentProject?.name || '未选择')
const username = computed(() => getUserName())

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
}

.topbar {
  height: 64px;
  background: var(--color-primary-900); /* 替换为深藏青色 */
  color: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand {
  font-size: 18px;
  font-weight: 700;
}

.project {
  font-size: 14px;
  color: #bfdbfe; /* 浅蓝色 */
}

.project-link {
  color: #93c5fd;
  text-decoration: underline;
  cursor: pointer;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user {
  color: #f8fafc;
  text-decoration: none;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}

.user:hover {
  opacity: 0.8;
  text-decoration: underline;
}

.link {
  border: none;
  background: transparent;
  color: #93c5fd;
  cursor: pointer;
}

.body {
  flex: 1;
  display: flex;
}

.sidebar {
  width: 220px;
  background: #0f172a; /* 保持深色背景，与主色调协调 */
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 20px 16px;
}

.nav-item {
  padding: 10px 12px;
  border-radius: 8px;
  color: #ffffff;
  text-decoration: none;
  opacity: 0.8;
  transition: all 0.2s;
}

.nav-item:hover {
  background: rgba(37, 99, 235, 0.2); /* 悬停时使用主色调的低透明度 */
  opacity: 1;
}

.nav-item.router-link-exact-active {
  background: var(--color-primary-600); /* 选中时使用鲜亮蓝 */
  color: #ffffff;
  opacity: 1;
}

.content {
  flex: 1;
  padding: 24px;
}
</style>
