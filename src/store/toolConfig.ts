import { ref, watch } from 'vue'

const DEFAULT_HOST = '211.71.15.55'
const STORAGE_KEY = 'TOOL_SERVER_HOST'

const savedHost = localStorage.getItem(STORAGE_KEY)

// 全局的服务器基础地址
export const serverHost = ref(savedHost || DEFAULT_HOST)

// 监听并保存到 localStorage
watch(serverHost, (newHost) => {
  localStorage.setItem(STORAGE_KEY, newHost)
})

// 恢复默认配置
export const resetServerHost = () => {
  serverHost.value = DEFAULT_HOST
}

// 动态计算最终的工具 URL
export const getToolUrl = (originalUrl: string) => {
  if (!originalUrl) return ''
  // 替换所有默认的 211.71.15.55 为当前配置的 host
  return originalUrl.replace('211.71.15.55', serverHost.value)
}
