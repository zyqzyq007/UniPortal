<template>
  <div class="tool-viewer">
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>正在加载工具资源...</p>
    </div>
    <iframe
      v-if="targetUrl"
      :src="targetUrl"
      class="iframe"
      @load="onLoad"
      frameborder="0"
    ></iframe>
    <div v-else class="error">
      <p>未找到该工具的访问地址</p>
      <RouterLink :to="`/projects/${projectId}/tools`" class="btn">返回工具中心</RouterLink>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { tools } from '../../mock/data'

const route = useRoute()
const projectId = computed(() => route.params.projectId as string)
const toolKey = computed(() => route.params.toolKey as string)

const loading = ref(true)
const targetUrl = computed(() => {
  const tool = tools.find((t) => t.key === toolKey.value)
  return tool?.targetUrl || ''
})

const onLoad = () => {
  loading.value = false
}

// 监听路由变化，重置加载状态
watch(toolKey, () => {
  loading.value = true
})

onMounted(() => {
  if (!targetUrl.value) {
    loading.value = false
  }
})
</script>

<style scoped>
.tool-viewer {
  width: 100%;
  height: calc(100vh - 64px); /* 减去顶部导航高度 */
  display: flex;
  flex-direction: column;
  position: relative;
}

.iframe {
  flex: 1;
  width: 100%;
  height: 100%;
  border: none;
}

.loading,
.error {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
  z-index: 10;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 16px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.btn {
  margin-top: 16px;
  padding: 8px 16px;
  background: #3b82f6;
  color: white;
  border-radius: 6px;
  text-decoration: none;
}
</style>
