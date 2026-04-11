<template>
  <div class="h-full overflow-y-auto p-8 bg-white">
    <div class="max-w-5xl mx-auto space-y-8">
      <!-- Status Header -->
      <div class="bg-white border border-slate-200 rounded-xl p-6 flex items-center justify-between shadow-sm">
        <div class="flex items-center space-x-6">
          <div class="relative w-16 h-16">
            <svg class="w-full h-full transform -rotate-90">
              <circle cx="32" cy="32" r="28" fill="transparent" stroke="currentColor" stroke-width="4" class="text-slate-100" />
              <circle cx="32" cy="32" r="28" fill="transparent" stroke="currentColor" stroke-width="4" 
                class="text-primary-600 transition-all duration-1000" 
                :stroke-dasharray="175.9" 
                :stroke-dashoffset="175.9 * (1 - progress / 100)" 
              />
            </svg>
            <div class="absolute inset-0 flex items-center justify-center font-bold text-sm text-slate-800">
              {{ progress }}%
            </div>
          </div>
          <div class="space-y-1">
            <h2 class="text-xl font-bold text-slate-800">{{ statusTitle }}</h2>
            <p class="text-sm font-medium text-slate-500">{{ statusDescription }}</p>
          </div>
        </div>

        <div v-if="result?.test_result" class="flex items-center space-x-8 px-8 border-l border-slate-100">
          <div class="text-center">
            <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Passed</p>
            <p class="text-2xl font-bold text-green-600">{{ result.test_result.passed }}</p>
          </div>
          <div class="text-center">
            <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Failed</p>
            <p class="text-2xl font-bold text-red-600">{{ result.test_result.failed }}</p>
          </div>
          <div class="text-center">
            <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Total</p>
            <p class="text-2xl font-bold text-slate-900">{{ result.test_result.total }}</p>
          </div>
        </div>

        <div class="flex items-center gap-3" v-if="progress === 100">
          <button 
            v-if="canFix"
            @click="fixTestCase"
            :disabled="fixing"
            class="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-200 text-white text-xs font-bold uppercase rounded flex items-center gap-2 transition-all shadow-sm"
          >
            <Zap class="w-3.5 h-3.5" :class="{ 'animate-pulse': fixing }" />
            {{ fixing ? '正在修复...' : '修复测试用例' }}
          </button>
          
          <button 
            @click="startExecution"
            :disabled="executing || fixing"
            class="px-4 py-2 bg-slate-100 hover:bg-slate-200 disabled:bg-slate-50 disabled:text-slate-300 text-slate-700 text-xs font-bold uppercase rounded flex items-center gap-2 transition-colors"
          >
            <RotateCw class="w-3.5 h-3.5" :class="{ 'animate-spin': executing && progress === 100 }" />
            重新执行
          </button>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <!-- Console Output -->
        <div class="lg:col-span-2 space-y-4">
          <h3 class="text-sm font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
            <Terminal class="w-4 h-4" />
            控制台输出 (Console)
          </h3>
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 font-mono text-xs h-[450px] overflow-auto shadow-inner">
            <div v-if="result?.stdout" class="space-y-1">
              <div v-for="(line, idx) in result.stdout.split('\n')" :key="idx" class="flex">
                <span class="text-slate-600 mr-4 select-none w-8 text-right">{{ idx + 1 }}</span>
                <span :class="{ 'text-green-400 font-bold': line.includes('PASS'), 'text-red-400 font-bold': line.includes('FAIL'), 'text-slate-300': !line.includes('PASS') && !line.includes('FAIL') }">{{ line }}</span>
              </div>
            </div>
            <div v-if="result?.stderr" class="mt-4 p-3 bg-red-950/30 border border-red-900/30 rounded text-red-200">
              <p class="font-bold mb-1 uppercase text-[10px] tracking-wider">Error Logs:</p>
              {{ result.stderr }}
            </div>
            <div v-if="executing" class="flex items-center space-x-2 text-primary-400 animate-pulse mt-2">
              <span class="font-bold">> 正在运行测试...</span>
              <span class="w-1.5 h-4 bg-primary-400"></span>
            </div>
          </div>
        </div>

        <!-- Coverage Card -->
        <div class="space-y-4">
          <h3 class="text-sm font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
            <ShieldCheck class="w-4 h-4" />
            覆盖率分析 (Coverage)
          </h3>
          <div class="bg-white border border-slate-200 rounded-xl p-6 space-y-6 shadow-sm">
            <div v-if="executing || fixing" class="flex flex-col items-center justify-center py-12 space-y-4">
              <div class="w-8 h-8 border-4 border-primary-100 border-t-primary-600 rounded-full animate-spin"></div>
              <p class="text-xs text-slate-400 font-bold animate-pulse uppercase tracking-wider">正在分析覆盖率...</p>
            </div>
            <div v-else-if="!result?.coverage" class="text-center py-12 text-slate-300 font-medium italic text-sm">
              执行完成后将显示覆盖率
            </div>
            <template v-else>
              <div v-for="metric in coverageMetrics" :key="metric.label" class="space-y-3">
                <div class="flex justify-between text-xs">
                  <span class="text-slate-600 font-bold uppercase tracking-tighter">{{ metric.label }}</span>
                  <span class="font-black text-slate-900">{{ metric.value }}%</span>
                </div>
                <div class="w-full bg-slate-100 h-2 rounded-full overflow-hidden border border-slate-50">
                  <div 
                    class="h-full transition-all duration-1000 shadow-sm" 
                    :class="metric.value > 80 ? 'bg-green-500' : metric.value > 50 ? 'bg-yellow-500' : 'bg-red-500'"
                    :style="{ width: metric.value + '%' }"
                  ></div>
                </div>
                <p class="text-[10px] font-bold text-slate-400 text-right">{{ metric.covered }}/{{ metric.total }} lines</p>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- Source Code Coverage -->
      <div v-if="result?.source_code" class="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm mt-8">
        <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
          <h3 class="font-semibold text-slate-800 flex items-center gap-2">
            <FileText class="w-5 h-5 text-indigo-600" />
            被测函数详情 (Target Function Coverage)
          </h3>
        </div>
        <div class="p-0 overflow-x-auto">
          <table class="w-full text-sm font-mono border-collapse">
            <tbody>
              <tr v-for="line in visibleLines" :key="line.lineNumber" 
                  :class="getLineCoverageClass(line.lineNumber)">
                <td class="w-12 px-3 py-1 text-right text-slate-400 select-none border-r border-slate-100 bg-slate-50">
                  {{ line.lineNumber }}
                </td>
                <td class="px-4 py-1 whitespace-pre">{{ line.content }}</td>
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
import { Terminal, ShieldCheck, RotateCw, Zap, FileText } from 'lucide-vue-next'

const store = useAppStore()
const router = useRouter()

const progress = ref(0)
const executing = ref(false)
const fixing = ref(false)
const result = ref(null)
const errorMessage = ref(null)

const canFix = computed(() => {
  if (!result.value) return false
  return !result.value.compile_success || (result.value.test_result && result.value.test_result.failed > 0)
})

const visibleLines = computed(() => {
  if (!result.value?.source_code) return []
  const lines = result.value.source_code.split('\n')
  
  // Ensure we have valid numbers
  const start = parseInt(result.value.function_start_line) || 1
  const end = parseInt(result.value.function_end_line) || lines.length
  
  // Return array of { content: string, lineNumber: int }
  return lines
      .map((content, idx) => ({ content, lineNumber: idx + 1 }))
      .filter(item => item.lineNumber >= start && item.lineNumber <= end)
})

const getLineCoverageClass = (lineNumber) => {
  if (!result.value?.coverage?.files?.length) return ''
  
  // Find the file coverage that matches the source code
  // Assuming the first file in the coverage report corresponds to the source code being displayed
  const fileCov = result.value.coverage.files[0]
  
  if (!fileCov?.lines) return ''
  
  const count = fileCov.lines[lineNumber]
  if (count === undefined) return '' // Not instrumented
  
  return count > 0 ? 'bg-emerald-100' : 'bg-rose-100'
}

const statusTitle = computed(() => {
  if (errorMessage.value) return '执行出错'
  if (executing.value) return progress.value < 50 ? '正在编译测试用例' : '正在执行测试并收集数据'
  if (result.value?.compile_success === false) return '编译失败'
  if (result.value?.test_result) return '执行完成'
  return '准备就绪'
})

const statusDescription = computed(() => {
  if (errorMessage.value) return errorMessage.value
  if (executing.value) return '正在使用 Unity 框架构建二进制并执行符号分析'
  if (result.value?.compile_success === false) return '生成的代码可能存在语法错误或缺少头文件依赖'
  if (result.value?.test_result) return `成功通过 ${result.value.test_result.passed} 个用例，共计 ${result.value.test_result.total} 个`
  return '点击开始按钮执行生成的测试用例'
})

const coverageMetrics = computed(() => {
  if (!result.value?.coverage?.files?.[0]) return []
  const cov = result.value.coverage.files[0]
  
  // 如果是函数级测试，且存在函数详情，则优先显示函数级覆盖率
  if (result.value.coverage.scope === 'function' && cov.functions && cov.functions.length > 0) {
    // 寻找覆盖率最高的函数或者第一个函数（通常测试生成是针对单个函数的）
    const func = cov.functions.find(f => f.line.covered > 0) || cov.functions[0]
    return [
      { label: '行覆盖率 (Line)', value: func.line.total === 0 ? 100 : Math.round(func.line.rate * 100), covered: func.line.covered, total: func.line.total },
      { label: '函数覆盖率 (Function)', value: 100, covered: 1, total: 1 },
      { label: '分支覆盖率 (Branch)', value: func.branch.total === 0 ? 100 : Math.round(func.branch.rate * 100), covered: func.branch.covered, total: func.branch.total },
    ]
  }

  return [
    { label: '行覆盖率 (Line)', value: cov.line.total === 0 ? 100 : Math.round(cov.line.rate * 100), covered: cov.line.covered, total: cov.line.total },
    { label: '函数覆盖率 (Function)', value: cov.function.total === 0 ? 100 : Math.round(cov.function.rate * 100), covered: cov.function.covered, total: cov.function.total },
    { label: '分支覆盖率 (Branch)', value: cov.branch.total === 0 ? 100 : Math.round(cov.branch.rate * 100), covered: cov.branch.covered, total: cov.branch.total },
  ]
})

const startExecution = async () => {
  if (executing.value || fixing.value) return
  result.value = null // Reset previous results
  errorMessage.value = null
  executing.value = true
  progress.value = 10
  
  // Fake progress animation
  const interval = setInterval(() => {
    if (progress.value < 90) progress.value += 5
  }, 500)

  try {
    const response = await axios.post('/api/testcase/execute', {
      task_id: store.taskId
    })
    result.value = response.data
    progress.value = 100
  } catch (error) {
    console.error('Execution failed:', error)
    errorMessage.value = error.response?.data?.detail || error.message || '执行请求失败'
    progress.value = 0
  } finally {
    clearInterval(interval)
    executing.value = false
  }
}

const fixTestCase = async () => {
  if (!canFix.value || fixing.value || executing.value) return
  
  // 1. Get failure info
  let failureInfo = ""
  if (result.value.compile_success === false) {
    failureInfo = result.value.stderr || "Compilation failed."
  } else if (result.value.test_result && result.value.test_result.failed > 0) {
    failureInfo = result.value.stdout || "Test cases failed."
  }

  // 2. Store failure context and navigate back to generate page
  store.setFailureContext(failureInfo, store.taskId)
  router.push('/generate')
}

onMounted(() => {
  startExecution()
})
</script>
