<template>
  <div class="admin-view">
    <!-- Page Header -->
    <div class="page-header">
      <div class="header-content">
        <h1>系统管理</h1>
        <p>监控系统状态、熔断器和性能指标</p>
      </div>
      <div class="header-actions">
        <button class="btn-secondary" @click="refreshAll" data-testid="admin-refresh">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 4v6h-6"/>
            <path d="M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
          刷新
        </button>
      </div>
    </div>

    <!-- Health Status -->
    <div class="section" data-testid="admin-section-health">
      <div class="section-header">
        <h2>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
          </svg>
          系统健康状态
        </h2>
        <span class="overall-status" :class="overallHealth">
          {{ overallHealth === 'healthy' ? '正常' : overallHealth === 'degraded' ? '降级' : '异常' }}
        </span>
      </div>
      <div class="health-grid">
        <div
          v-for="(service, name) in healthData.services"
          :key="name"
          class="health-card"
          :class="service.status"
        >
          <div class="health-icon">
            <svg v-if="service.status === 'healthy'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            <svg v-else-if="service.status === 'degraded'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <svg v-else-if="service.status === 'ready' || service.status === 'cold'" viewBox="0 0 24 24" fill="currentColor" stroke="none">
              <circle cx="12" cy="12" r="5"/>
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <line x1="15" y1="9" x2="9" y2="15"/>
              <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
          </div>
          <div class="health-info">
            <div class="service-name">{{ formatServiceName(name) }}</div>
            <div class="service-status">{{ getStatusLabel(service.status) }}</div>
            <div class="service-circuit" v-if="service.circuit">
              熔断器: {{ service.circuit }}
            </div>
          </div>
        </div>
        <div v-if="Object.keys(healthData.services || {}).length === 0" class="no-data">
          暂无服务状态数据
        </div>
      </div>
    </div>

    <!-- Circuit Breakers -->
    <div class="section" data-testid="admin-section-circuits">
      <div class="section-header">
        <h2>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
            <line x1="9" y1="9" x2="15" y2="15"/>
            <line x1="15" y1="9" x2="9" y2="15"/>
          </svg>
          熔断器状态
        </h2>
      </div>
      <div class="circuit-list">
        <div v-for="(stats, name) in circuitBreakers" :key="name" class="circuit-item">
          <div class="circuit-info">
            <span class="circuit-name">{{ name }}</span>
            <span class="circuit-state" :class="stats.state">{{ getStateLabel(stats.state) }}</span>
          </div>
          <div class="circuit-stats">
            <div class="stat-item">
              <span class="stat-label">成功</span>
              <span class="stat-value success">{{ stats.successful_calls || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">失败</span>
              <span class="stat-value error">{{ stats.failed_calls || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">失败率</span>
              <span class="stat-value">{{ getFailureRate(stats) }}%</span>
            </div>
          </div>
          <button
            class="btn-reset"
            @click="resetCircuitBreaker(name)"
            :disabled="stats.state === 'closed'"
            data-testid="circuit-reset"
          >
            重置
          </button>
        </div>
        <div v-if="Object.keys(circuitBreakers || {}).length === 0" class="no-data">
          暂无熔断器数据
        </div>
      </div>
    </div>

    <!-- Degradation Mode -->
    <div class="section" data-testid="admin-section-degradation">
      <div class="section-header">
        <h2>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
          降级模式
        </h2>
      </div>
      <div class="degradation-control">
        <div class="mode-options">
          <button
            v-for="mode in degradationModes"
            :key="mode.value"
            class="mode-btn"
            :class="{ active: degradationMode === mode.value }"
            @click="setDegradationMode(mode.value)"
            :data-testid="'degradation-mode-' + mode.value"
          >
            <span class="mode-icon">{{ mode.icon }}</span>
            <span class="mode-label">{{ mode.label }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Metrics -->
    <div class="section" data-testid="admin-section-metrics">
      <div class="section-header">
        <h2>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="20" x2="18" y2="10"/>
            <line x1="12" y1="20" x2="12" y2="4"/>
            <line x1="6" y1="20" x2="6" y2="14"/>
          </svg>
          系统指标
        </h2>
      </div>
      <div class="metrics-grid">
        <div class="metric-card" v-if="metrics.memory?.rss_mb">
          <div class="metric-icon memory">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="2" y="6" width="20" height="12" rx="2"/>
              <line x1="6" y1="10" x2="6" y2="14"/>
              <line x1="10" y1="10" x2="10" y2="14"/>
              <line x1="14" y1="10" x2="14" y2="14"/>
              <line x1="18" y1="10" x2="18" y2="14"/>
            </svg>
          </div>
          <div class="metric-info">
            <div class="metric-value">{{ metrics.memory.rss_mb?.toFixed(1) }} MB</div>
            <div class="metric-label">内存使用 (RSS)</div>
          </div>
        </div>
        <div class="metric-card" v-if="metrics.memory?.vms_mb">
          <div class="metric-icon virtual">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <ellipse cx="12" cy="5" rx="9" ry="3"/>
              <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
              <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
            </svg>
          </div>
          <div class="metric-info">
            <div class="metric-value">{{ metrics.memory.vms_mb?.toFixed(1) }} MB</div>
            <div class="metric-label">虚拟内存</div>
          </div>
        </div>
        <div class="metric-card" v-if="metrics.gc">
          <div class="metric-icon gc">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
            </svg>
          </div>
          <div class="metric-info">
            <div class="metric-value">{{ metrics.gc.collections || 0 }}</div>
            <div class="metric-label">GC 次数</div>
          </div>
        </div>
        <div class="metric-card" v-if="metrics.uptime">
          <div class="metric-icon uptime">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12 6 12 12 16 14"/>
            </svg>
          </div>
          <div class="metric-info">
            <div class="metric-value">{{ formatUptime(metrics.uptime) }}</div>
            <div class="metric-label">运行时间</div>
          </div>
        </div>
      </div>
      <div v-if="!metrics.memory && !metrics.gc" class="no-data">
        暂无指标数据
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiUrl } from '@/utils/api'

const healthData = ref<any>({ services: {} })
const circuitBreakers = ref<any>({})
const degradationMode = ref('full')
const metrics = ref<any>({})

// Auto-refresh health while any service is in a transient/degraded state
// (ready/cold/degraded). The reranker is lazy-loaded (RERANKER_WARMUP=false
// by default), so it is initially "ready" until the first retrieval loads it
// into memory; without polling the card would show a stale transient state
// until the user manually clicks refresh. Once every service is "healthy",
// the timer stops to avoid needless background traffic.
let healthPollTimer: ReturnType<typeof setInterval> | null = null
const HEALTH_POLL_INTERVAL_MS = 4000
const TRANSIENT_STATES = new Set(['ready', 'cold', 'degraded'])

function _hasTransientService(): boolean {
  const services = healthData.value.services || {}
  return Object.values(services).some((s: any) => TRANSIENT_STATES.has(s.status))
}

function _syncHealthPolling() {
  const hasTransient = _hasTransientService()
  if (hasTransient && healthPollTimer === null) {
    healthPollTimer = setInterval(loadHealth, HEALTH_POLL_INTERVAL_MS)
  } else if (!hasTransient && healthPollTimer !== null) {
    clearInterval(healthPollTimer)
    healthPollTimer = null
  }
}

const degradationModes = [
  { value: 'full', label: '正常', icon: '✅' },
  { value: 'cached', label: '仅缓存', icon: '💾' },
  { value: 'simplified', label: '简化', icon: '⚡' },
  { value: 'offline', label: '离线', icon: '📴' },
]

const overallHealth = computed(() => {
  const services = healthData.value.services || {}
  const statuses = Object.values(services).map((s: any) => s.status)
  if (statuses.includes('unhealthy')) return 'unhealthy'
  if (statuses.includes('degraded')) return 'degraded'
  return 'healthy'
})

onMounted(async () => {
  await refreshAll()
})

onUnmounted(() => {
  if (healthPollTimer !== null) {
    clearInterval(healthPollTimer)
    healthPollTimer = null
  }
})

async function refreshAll() {
  await Promise.all([
    loadHealth(),
    loadCircuitBreakers(),
    loadMetrics(),
    loadDegradation(),
  ])
}

async function loadHealth() {
  try {
    const response = await fetch(apiUrl('api/admin/health'))
    healthData.value = await response.json()
    _syncHealthPolling()
  } catch (e) {
    console.error('Load health error:', e)
  }
}

async function loadCircuitBreakers() {
  try {
    const response = await fetch(apiUrl('api/admin/circuit-breakers'))
    circuitBreakers.value = await response.json()
  } catch (e) {
    console.error('Load circuit breakers error:', e)
  }
}

async function loadMetrics() {
  try {
    const response = await fetch(apiUrl('api/admin/metrics'))
    metrics.value = await response.json()
  } catch (e) {
    console.error('Load metrics error:', e)
  }
}

async function loadDegradation() {
  try {
    const response = await fetch(apiUrl('api/admin/degradation'))
    const data = await response.json()
    degradationMode.value = data.mode || 'full'
  } catch (e) {
    console.error('Load degradation error:', e)
  }
}

async function resetCircuitBreaker(name: string | number) {
  const nameStr = String(name)
  try {
    await fetch(apiUrl(`api/admin/circuit-breakers/${nameStr}/reset`), { method: 'POST' })
    await loadCircuitBreakers()
  } catch (e) {
    console.error('Reset circuit breaker error:', e)
  }
}

async function setDegradationMode(mode: string) {
  try {
    await fetch(apiUrl(`api/admin/degradation/mode/${mode}`), { method: 'POST' })
    degradationMode.value = mode
  } catch (e) {
    console.error('Set degradation mode error:', e)
  }
}

function formatServiceName(name: string | number): string {
  const nameStr = String(name)
  const names: Record<string, string> = {
    llm: 'LLM 模型',
    milvus: 'Milvus 数据库',
    redis: 'Redis 缓存',
    embedding: '嵌入模型',
    reranker: '重排模型',
    retriever: '检索器',
  }
  return names[nameStr] || nameStr.toUpperCase()
}

function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    healthy: '正常',
    degraded: '降级',
    unhealthy: '异常',
    ready: '就绪',
    cold: '未加载',
  }
  return labels[status] || status
}

function getStateLabel(state: string): string {
  const labels: Record<string, string> = {
    closed: '关闭',
    open: '打开',
    half_open: '半开',
  }
  return labels[state] || state
}

function getFailureRate(stats: any): string {
  const total = (stats.successful_calls || 0) + (stats.failed_calls || 0)
  if (total === 0) return '0'
  return ((stats.failed_calls || 0) / total * 100).toFixed(1)
}

function formatUptime(seconds: number): string {
  if (!seconds) return '0s'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}
</script>

<style scoped>
.admin-view {
  padding: var(--spacing-lg);
  max-width: 1200px;
  margin: 0 auto;
  overflow-y: auto;
}

/* Page Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-xl);
}

.header-content h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 var(--spacing-xs) 0;
}

.header-content p {
  color: var(--neutral-500);
  margin: 0;
}

.btn-secondary {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  background: white;
  border: 1px solid var(--neutral-200);
  border-radius: var(--radius-md);
  color: var(--neutral-700);
  font-weight: 500;
  transition: all var(--transition-fast);
}

.btn-secondary:hover {
  background: var(--neutral-50);
  border-color: var(--neutral-300);
}

.btn-secondary svg {
  width: 18px;
  height: 18px;
}

/* Section */
.section {
  background: white;
  border-radius: var(--radius-xl);
  padding: var(--spacing-lg);
  margin-bottom: var(--spacing-lg);
  box-shadow: var(--shadow-sm);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-md);
}

.section-header h2 {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.section-header h2 svg {
  width: 20px;
  height: 20px;
  color: var(--neutral-500);
}

.overall-status {
  padding: var(--spacing-xs) var(--spacing-md);
  border-radius: var(--radius-full);
  font-size: 13px;
  font-weight: 500;
}

.overall-status.healthy {
  background: var(--success-100);
  color: var(--success-500);
}

.overall-status.degraded {
  background: var(--warning-100);
  color: var(--warning-500);
}

.overall-status.unhealthy {
  background: var(--error-100);
  color: var(--error-500);
}

/* Health Grid */
.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--spacing-md);
}

.health-card {
  display: flex;
  gap: var(--spacing-md);
  padding: var(--spacing-md);
  background: var(--neutral-50);
  border-radius: var(--radius-lg);
  border-left: 4px solid var(--neutral-300);
}

.health-card.healthy {
  border-left-color: var(--success-500);
}

.health-card.degraded {
  border-left-color: var(--warning-500);
}

.health-card.unhealthy {
  border-left-color: var(--error-500);
}

/* Neutral transient states: model cached-but-not-loaded (ready) or
   not-yet-cached cold start (cold). These are NOT failures — the service is
   operational but the lazy-loaded model has not been resident in memory yet.
   Render grey to distinguish from healthy (green) and degraded/unhealthy. */
.health-card.ready,
.health-card.cold {
  border-left-color: var(--neutral-400);
}

.health-card.ready .health-icon,
.health-card.cold .health-icon {
  background: var(--neutral-100);
  color: var(--neutral-500);
}

.health-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.health-card.healthy .health-icon {
  background: var(--success-100);
  color: var(--success-500);
}

.health-card.degraded .health-icon {
  background: var(--warning-100);
  color: var(--warning-500);
}

.health-card.unhealthy .health-icon {
  background: var(--error-100);
  color: var(--error-500);
}

.health-icon svg {
  width: 20px;
  height: 20px;
}

.service-name {
  font-weight: 600;
  font-size: 14px;
}

.service-status {
  font-size: 13px;
  color: var(--neutral-600);
  margin-top: 2px;
}

.service-circuit {
  font-size: 12px;
  color: var(--neutral-500);
  margin-top: 4px;
}

/* Circuit List */
.circuit-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.circuit-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-lg);
  padding: var(--spacing-md);
  background: var(--neutral-50);
  border-radius: var(--radius-md);
}

.circuit-info {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  min-width: 180px;
}

.circuit-name {
  font-weight: 500;
}

.circuit-state {
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-size: 12px;
  font-weight: 500;
}

.circuit-state.closed {
  background: var(--success-100);
  color: var(--success-500);
}

.circuit-state.open {
  background: var(--error-100);
  color: var(--error-500);
}

.circuit-state.half_open {
  background: var(--warning-100);
  color: var(--warning-500);
}

.circuit-stats {
  display: flex;
  gap: var(--spacing-lg);
  flex: 1;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-item .stat-label {
  font-size: 11px;
  color: var(--neutral-500);
}

.stat-item .stat-value {
  font-size: 16px;
  font-weight: 600;
}

.stat-item .stat-value.success {
  color: var(--success-500);
}

.stat-item .stat-value.error {
  color: var(--error-500);
}

.btn-reset {
  padding: var(--spacing-xs) var(--spacing-md);
  background: var(--primary-500);
  color: white;
  border-radius: var(--radius-md);
  font-weight: 500;
  transition: all var(--transition-fast);
}

.btn-reset:hover:not(:disabled) {
  background: var(--primary-600);
}

.btn-reset:disabled {
  opacity: 0.5;
}

/* Degradation Control */
.degradation-control {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.mode-options {
  display: flex;
  gap: var(--spacing-sm);
  flex-wrap: wrap;
}

.mode-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-xs);
  padding: var(--spacing-md) var(--spacing-lg);
  background: var(--neutral-50);
  border: 2px solid var(--neutral-200);
  border-radius: var(--radius-lg);
  transition: all var(--transition-fast);
}

.mode-btn:hover {
  border-color: var(--primary-200);
  background: var(--primary-50);
}

.mode-btn.active {
  border-color: var(--primary-400);
  background: var(--primary-50);
}

.mode-icon {
  font-size: 24px;
}

.mode-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-700);
}

/* Metrics Grid */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--spacing-md);
}

.metric-card {
  display: flex;
  gap: var(--spacing-md);
  padding: var(--spacing-md);
  background: var(--neutral-50);
  border-radius: var(--radius-lg);
}

.metric-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.metric-icon.memory {
  background: var(--primary-100);
  color: var(--primary-500);
}

.metric-icon.virtual {
  background: var(--info-100);
  color: var(--info-500);
}

.metric-icon.gc {
  background: var(--warning-100);
  color: var(--warning-500);
}

.metric-icon.uptime {
  background: var(--success-100);
  color: var(--success-500);
}

.metric-icon svg {
  width: 24px;
  height: 24px;
}

.metric-info {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.metric-value {
  font-size: 20px;
  font-weight: 700;
}

.metric-label {
  font-size: 12px;
  color: var(--neutral-500);
}

/* No Data */
.no-data {
  text-align: center;
  padding: var(--spacing-xl);
  color: var(--neutral-500);
}

/* Responsive */
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: var(--spacing-md);
  }

  .health-grid,
  .metrics-grid {
    grid-template-columns: 1fr;
  }

  .circuit-item {
    flex-direction: column;
    align-items: flex-start;
  }

  .circuit-stats {
    width: 100%;
    justify-content: space-between;
  }

  .mode-options {
    flex-direction: column;
  }

  .mode-btn {
    flex-direction: row;
    width: 100%;
  }
}
</style>
