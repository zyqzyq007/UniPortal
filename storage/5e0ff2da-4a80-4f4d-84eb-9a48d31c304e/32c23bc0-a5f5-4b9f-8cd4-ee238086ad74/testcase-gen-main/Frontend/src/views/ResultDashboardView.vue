<template>
  <div class="h-full overflow-y-auto p-8 bg-white">
    <div class="max-w-7xl mx-auto space-y-8">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <LayoutDashboard class="w-6 h-6 text-primary-600" />
            测试结果总览
          </h1>
          <p class="text-slate-500 text-sm mt-1">项目: {{ store.projectName }}</p>
        </div>
        <div class="flex gap-2">
          <button @click="fetchSummary" class="p-2 text-slate-500 hover:bg-slate-100 rounded transition-colors" title="刷新">
            <RotateCw class="w-5 h-5" :class="{'animate-spin': loading}" />
          </button>
          <button @click="router.push('/browse')" class="px-4 py-2 bg-blue-700 hover:bg-blue-800 text-white font-bold rounded-lg transition-colors text-sm">
            进入项目浏览
          </button>
        </div>
      </div>

      <!-- Stats Cards -->
      <div class="grid grid-cols-4 gap-4">
        <div class="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
          <div class="text-slate-500 text-xs font-bold uppercase mb-1">总被测函数</div>
          <div class="text-2xl font-bold text-slate-900">{{ stats.total }}</div>
        </div>
        <div class="bg-green-50 border border-green-100 rounded-xl p-4 shadow-sm">
          <div class="text-green-600 text-xs font-bold uppercase mb-1">通过</div>
          <div class="text-2xl font-bold text-green-700">{{ stats.passed }}</div>
        </div>
        <div class="bg-red-50 border border-red-100 rounded-xl p-4 shadow-sm">
          <div class="text-red-600 text-xs font-bold uppercase mb-1">失败</div>
          <div class="text-2xl font-bold text-red-700">{{ stats.failed }}</div>
        </div>
        <div class="bg-orange-50 border border-orange-100 rounded-xl p-4 shadow-sm">
          <div class="text-orange-600 text-xs font-bold uppercase mb-1">编译错误</div>
          <div class="text-2xl font-bold text-orange-700">{{ stats.compileError }}</div>
        </div>
      </div>

      <!-- Main Table -->
      <div class="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="bg-slate-50 border-b border-slate-200 text-xs font-bold text-slate-500 uppercase tracking-wider">
                <th class="p-4 w-16 text-center">#</th>
                <th class="p-4">函数名称</th>
                <th class="p-4 w-48">源文件</th>
                <th class="p-4 w-32">行覆盖率</th>
                <th class="p-4 w-32">分支覆盖率</th>
                <th class="p-4 w-32">状态</th>
                <th class="p-4 w-32 text-right">操作</th>
              </tr>
            </thead>
            <tbody class="text-sm divide-y divide-slate-100">
              <tr v-if="loading && functions.length === 0">
                <td colspan="7" class="p-8 text-center text-slate-400">加载中...</td>
              </tr>
              <tr 
                v-for="(func, idx) in functions" 
                :key="func.function_id" 
                class="hover:bg-slate-50 transition-colors group"
              >
                <td class="p-4 text-center text-slate-400 font-mono">{{ idx + 1 }}</td>
                <td class="p-4 font-bold text-slate-800 font-mono">{{ func.name }}</td>
                <td class="p-4 truncate max-w-[200px]">
                  <button 
                    @click="viewSource(func)" 
                    class="text-slate-500 hover:text-primary-600 hover:underline text-left truncate w-full" 
                    :title="func.source_file"
                  >
                    {{ func.source_file }}
                  </button>
                </td>
                <td class="p-4">
                  <div class="flex items-center gap-2">
                    <div class="w-16 bg-slate-200 rounded-full h-1.5 overflow-hidden">
                      <div 
                        class="h-full rounded-full transition-all"
                        :class="getCoverageColor(func.line_coverage)" 
                        :style="{ width: `${(func.line_coverage || 0) * 100}%` }"
                      ></div>
                    </div>
                    <span class="text-xs font-bold tabular-nums" :class="getCoverageTextColor(func.line_coverage)">
                      {{ ((func.line_coverage || 0) * 100).toFixed(0) }}%
                    </span>
                  </div>
                </td>
                 <td class="p-4">
                  <div class="flex items-center gap-2">
                    <div class="w-16 bg-slate-200 rounded-full h-1.5 overflow-hidden">
                      <div 
                        class="h-full rounded-full transition-all"
                        :class="getCoverageColor(func.branch_coverage)" 
                        :style="{ width: `${(func.branch_coverage || 0) * 100}%` }"
                      ></div>
                    </div>
                    <span class="text-xs font-bold tabular-nums" :class="getCoverageTextColor(func.branch_coverage)">
                      {{ ((func.branch_coverage || 0) * 100).toFixed(0) }}%
                    </span>
                  </div>
                </td>
                <td class="p-4">
                  <span 
                    class="px-2 py-1 rounded text-xs font-bold uppercase inline-flex items-center gap-1"
                    :class="getStatusClass(func.status)"
                  >
                    <CheckCircle2 v-if="func.status === 'passed'" class="w-3 h-3" />
                    <XCircle v-else-if="func.status === 'failed' || func.status === 'ignored'" class="w-3 h-3" />
                    <AlertTriangle v-else-if="func.status === 'compile_error'" class="w-3 h-3" />
                    <Clock v-else class="w-3 h-3" />
                    {{ getStatusLabel(func.status) }}
                  </span>
                </td>
                <td class="p-4 text-right">
                  <button 
                    @click="viewDetail(func)"
                    class="text-primary-600 hover:text-primary-800 font-bold text-xs px-3 py-1 bg-primary-50 hover:bg-primary-100 rounded transition-colors opacity-0 group-hover:opacity-100"
                  >
                    查看详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../store'
import axios from 'axios'
import { LayoutDashboard, RotateCw, CheckCircle2, XCircle, AlertTriangle, Clock, Ban } from 'lucide-vue-next'

const router = useRouter()
const store = useAppStore()

const loading = ref(false)
const functions = ref([])

const stats = computed(() => {
  const total = functions.value.length
  const passed = functions.value.filter(f => f.status === 'passed').length
  const ignored = functions.value.filter(f => f.status === 'ignored').length
  const failed = functions.value.filter(f => f.status === 'failed').length + ignored
  const compileError = functions.value.filter(f => f.status === 'compile_error').length
  return { total, passed, failed, compileError }
})

const fetchSummary = async () => {
  if (!store.projectId) return
  loading.value = true
  try {
    // Add timestamp to prevent browser caching
    const res = await axios.get(`/api/project/${store.projectId}/test-summary?t=${Date.now()}`)
    functions.value = res.data.functions
  } catch (e) {
    console.error('Fetch summary failed:', e)
  } finally {
    loading.value = false
  }
}

const getCoverageColor = (rate) => {
  if (!rate) return 'bg-slate-300'
  if (rate >= 0.8) return 'bg-green-500'
  if (rate >= 0.5) return 'bg-yellow-500'
  return 'bg-red-500'
}

const getCoverageTextColor = (rate) => {
  if (!rate) return 'text-slate-400'
  if (rate >= 0.8) return 'text-green-600'
  if (rate >= 0.5) return 'text-yellow-600'
  return 'text-red-600'
}

const getStatusClass = (status) => {
  const map = {
    passed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    ignored: 'bg-red-100 text-red-700',
    compile_error: 'bg-orange-100 text-orange-700',
    pending: 'bg-slate-100 text-slate-500',
    no_tests: 'bg-slate-100 text-slate-500',
    unknown: 'bg-slate-100 text-slate-500'
  }
  return map[status] || map.unknown
}

const getStatusLabel = (status) => {
  const map = {
    passed: '通过',
    failed: '失败',
    ignored: '失败',
    compile_error: '编译错误',
    pending: '等待中',
    no_tests: '无测试',
    unknown: '未知'
  }
  return map[status] || status
}

const viewDetail = (func) => {
  // Set function context
  store.setFunction(func.function_id, func.name)
  // If task exists, set it to view result
  if (func.task_id) {
    store.setTask(func.task_id)
    router.push('/result')
  } else {
    // Otherwise go to generate
    router.push('/generate')
  }
}

const viewSource = (func) => {
  store.setFunction(func.function_id, func.name)
  router.push({ 
    path: '/browse', 
    query: { file: func.source_file } 
  })
}

onMounted(() => {
  fetchSummary()
})
</script>
