import { ref, watch } from 'vue'

// 直连模式：各工具用各自的 IP:端口 直接访问（data.ts 里写死 211.71.15.55:<port>）。
// serverHost = 服务器 IP，运行时把 data.ts 中的 211.71.15.55 替换为它。
// 改服务器 IP 时，在「全局服务器配置」弹窗里改这一个值即可。
const DEFAULT_HOST = '211.71.15.55'
// 用新 key，避免之前子域名方案残留在 localStorage 的值（tools.lan:8080）被读出来
const STORAGE_KEY = 'TOOL_SERVER_HOST_DIRECT'

const savedHost = localStorage.getItem(STORAGE_KEY)

// 全局的服务器基础地址
export const serverHost = ref(savedHost || DEFAULT_HOST)

watch(serverHost, (newHost) => {
  localStorage.setItem(STORAGE_KEY, newHost)
})

export const resetServerHost = () => {
  serverHost.value = DEFAULT_HOST
}

// 动态计算最终的工具 URL：把默认 IP 替换为当前配置的 host
export const getToolUrl = (originalUrl: string) => {
  if (!originalUrl) return ''
  return originalUrl.split('211.71.15.55').join(serverHost.value)
}
