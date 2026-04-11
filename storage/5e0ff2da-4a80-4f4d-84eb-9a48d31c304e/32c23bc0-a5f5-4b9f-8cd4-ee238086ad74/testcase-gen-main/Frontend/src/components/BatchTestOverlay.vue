<template>
  <div v-if="visible" class="fixed inset-0 bg-slate-900/50 flex items-center justify-center z-50 backdrop-blur-sm">
    <div class="bg-white rounded-xl shadow-2xl w-full max-w-2xl p-6 space-y-6">
      <div class="flex justify-between items-center">
        <h3 class="font-bold text-slate-800 text-lg flex items-center gap-2">
          <Zap class="w-5 h-5 text-yellow-500" />
          全量自动测试进度
        </h3>
        <button @click="handleClose" class="p-1 hover:bg-slate-100 rounded-full transition-colors">
          <X class="w-5 h-5 text-slate-400" />
        </button>
      </div>

      <!-- Main Progress Bar -->
      <div class="space-y-2">
         <div class="flex justify-between text-sm text-slate-600 font-bold">
            <span>{{ isCancelled ? '测试已停止' : '总进度' }}</span>
            <span>{{ totalProgress }}%</span>
         </div>
         <div class="w-full bg-slate-200 rounded-full h-3 overflow-hidden">
            <div 
              class="h-full transition-all duration-500 ease-out" 
              :class="isCancelled ? 'bg-slate-400' : 'bg-primary-600'"
              :style="{ width: totalProgress + '%' }"
            ></div>
         </div>
         <div class="text-xs text-slate-400 text-right font-mono">{{ batchStatus.completed }}/{{ batchStatus.total }} 任务</div>
      </div>
      
      <!-- Stages -->
      <div class="grid grid-cols-3 gap-3 text-sm">
        <div class="p-3 bg-slate-50 rounded-lg border border-slate-200 transition-colors" :class="{'border-primary-500 bg-primary-50': batchStage >= 1}">
          <div class="font-bold text-slate-700 mb-1">1. 解析</div>
          <div class="text-slate-500 text-xs" v-if="batchStage === 0">等待中...</div>
          <div class="text-primary-600 text-xs font-bold animate-pulse" v-if="batchStage === 1">正在解析函数列表...</div>
          <div class="text-green-600 text-xs font-bold" v-if="batchStage > 1">完成 ({{ batchStatus.total }}个必测函数)</div>
        </div>
         <div class="p-3 bg-slate-50 rounded-lg border border-slate-200 transition-colors" :class="{'border-primary-500 bg-primary-50': batchStage >= 2}">
          <div class="font-bold text-slate-700 mb-1">2. 生成</div>
           <div class="text-slate-500 text-xs" v-if="batchStage < 2">等待中...</div>
           <div class="text-primary-600 text-xs font-bold" v-if="batchStage === 2">生成中 {{ batchStatus.generated }}/{{ batchStatus.total }}</div>
           <div class="text-green-600 text-xs font-bold" v-if="batchStage > 2">完成</div>
        </div>
         <div class="p-3 bg-slate-50 rounded-lg border border-slate-200 transition-colors" :class="{'border-primary-500 bg-primary-50': batchStage >= 2}">
          <div class="font-bold text-slate-700 mb-1">3. 执行</div>
           <div class="text-slate-500 text-xs" v-if="batchStage < 2">等待中...</div>
           <div class="text-primary-600 text-xs font-bold" v-if="batchStage === 2">执行中 {{ batchStatus.executed }}/{{ batchStatus.total }}</div>
           <div class="text-green-600 text-xs font-bold" v-if="batchStage > 2">完成</div>
        </div>
      </div>
      
      <!-- Stats -->
      <div class="flex items-center justify-between text-sm bg-slate-50 p-4 rounded-lg border border-slate-200">
         <div class="flex gap-4">
           <span class="text-green-600 font-bold flex items-center gap-1"><CheckCircle2 class="w-4 h-4"/> 成功: {{ batchStatus.success }}</span>
           <span class="text-red-500 font-bold flex items-center gap-1"><XCircle class="w-4 h-4"/> 失败: {{ batchStatus.failed }}</span>
           <span class="text-orange-500 font-bold flex items-center gap-1"><AlertTriangle class="w-4 h-4"/> 编译错: {{ batchStatus.compileError }}</span>
         </div>
         <div class="text-slate-400 font-mono text-xs">并发度: {{ concurrency }}</div>
      </div>

      <!-- Warning -->
       <div v-if="isCancelled" class="p-3 bg-slate-100 border border-slate-300 rounded-lg text-sm text-slate-700 flex items-start gap-2">
          <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" />
          <span>测试已手动停止。已完成的 {{ batchStatus.completed }} 个测试结果已保存。</span>
       </div>
       <div v-else-if="batchStatus.compileError > (batchStatus.total * 0.3) && batchStatus.total > 5" class="p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-xs text-yellow-700 flex items-start gap-2">
          <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" />
          <span>检测到较多编译/链接失败 (>30%)，建议检查项目是否缺少依赖（如 zlib/openssl）。</span>
       </div>

       <!-- Actions -->
       <div class="flex justify-end gap-3 pt-2">
          <button 
            v-if="!isFinished && batchStage > 0" 
            @click="cancelTest" 
            class="px-4 py-2 text-red-600 hover:bg-red-50 font-bold rounded-lg transition-colors border border-red-200"
          >
            停止测试
          </button>
          <button 
            v-if="isFinished || isCancelled" 
            @click="close" 
            class="px-4 py-2 text-slate-600 hover:bg-slate-100 font-bold rounded-lg transition-colors"
          >
            关闭
          </button>
          <button 
            v-if="isFinished" 
            @click="goToDashboard" 
            class="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white font-bold rounded-lg transition-colors shadow-lg flex items-center gap-2"
          >
            <LayoutDashboard class="w-4 h-4" />
            前往结果总览
          </button>
       </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { Zap, X, CheckCircle2, XCircle, AlertTriangle, LayoutDashboard } from 'lucide-vue-next'

const props = defineProps({
  projectId: String,
  concurrency: {
    type: Number,
    default: 16
  }
})

const emit = defineEmits(['close'])
const router = useRouter()

const visible = ref(false)
const isCancelled = ref(false)
const batchStage = ref(0) // 0: Idle, 1: Parsing, 2: Running
const batchStatus = ref({
  total: 0,
  generated: 0,
  executed: 0,
  completed: 0,
  success: 0,
  failed: 0,
  compileError: 0
})

const isFinished = computed(() => batchStage.value > 2 || (batchStage.value === 2 && batchStatus.value.completed === batchStatus.value.total && batchStatus.value.total > 0))

const totalProgress = computed(() => {
  if (batchStage.value === 0) return 0
  if (batchStage.value === 1) return 10
  if (batchStatus.value.total === 0) return 10
  
  // Parse: 10%
  // Generate + Execute: 90%
  const processed = batchStatus.value.completed
  const progress = 10 + Math.floor((processed / batchStatus.value.total) * 90)
  return Math.min(progress, 100)
})

// Task Queue Logic
class TaskQueue {
  constructor(concurrency) {
    this.concurrency = concurrency
    this.running = 0
    this.queue = []
    this.cancelled = false
    this.abortControllers = new Set() // Track all active requests
  }

  cancel() {
    this.cancelled = true
    this.queue = [] // Clear pending tasks
    // Abort all active HTTP requests
    this.abortControllers.forEach(controller => {
      try {
        controller.abort()
      } catch (e) {
        console.log('Abort controller already aborted', e)
      }
    })
    this.abortControllers.clear()
  }

  createAbortController() {
    const controller = new AbortController()
    this.abortControllers.add(controller)
    return controller
  }

  removeAbortController(controller) {
    this.abortControllers.delete(controller)
  }

  add(task) {
    return new Promise((resolve, reject) => {
      if (this.cancelled) {
        reject(new Error('Task cancelled'))
        return
      }
      this.queue.push({ task, resolve, reject })
      this.process()
    })
  }

  async process() {
    if (this.cancelled || this.running >= this.concurrency || this.queue.length === 0) return
    
    this.running++
    const { task, resolve, reject } = this.queue.shift()
    
    try {
      if (this.cancelled) {
        reject(new Error('Task cancelled'))
      } else {
        const result = await task()
        resolve(result)
      }
    } catch (e) {
      reject(e)
    } finally {
      this.running--
      this.process()
    }
  }
}

let currentQueue = null

const start = async () => {
  if (!props.projectId) return
  visible.value = true
  batchStage.value = 1
  isCancelled.value = false
  
  // Reset stats
  batchStatus.value = {
    total: 0, generated: 0, executed: 0, completed: 0,
    success: 0, failed: 0, compileError: 0
  }

  try {
    // 1. Get Test Targets
    const targetsRes = await axios.get(`/api/project/${props.projectId}/test-targets`)
    const mustTest = targetsRes.data.must_test || []
    
    batchStatus.value.total = mustTest.length
    if (mustTest.length === 0) {
      alert('未找到必测函数（外部接口）。')
      visible.value = false
      return
    }

    // 检查项目是否有设计文档（只查一次）
    let hasDesignDoc = false
    try {
      const hdRes = await axios.get(`/api/project/${props.projectId}/has-design-doc`)
      hasDesignDoc = hdRes.data.has_design_doc === true
    } catch (e) { /* 忽略，不影响主流程 */ }

    batchStage.value = 2 // Running
    const queue = new TaskQueue(props.concurrency)
    currentQueue = queue
    const promises = []

    // 2. Queue Generate & Execute Tasks
    for (const func of mustTest) {
      const p = queue.add(async () => {
         const abortController = queue.createAbortController()
         try {
            // ── 第一步：生成测试用例 ──
            const genRes = await axios.post('/api/testcase/generate', {
              project_id: props.projectId,
              function_id: func.function_id,
              test_framework: 'unity'
            }, {
              signal: abortController.signal
            })
            batchStatus.value.generated++
            
            let taskId = genRes.data.task_id

            // ── 第二步：若有设计文档，插入中文注释（非流式，不阻塞进度展示） ──
            if (hasDesignDoc) {
              try {
                const annotateRes = await axios.post('/api/testcase/annotate', {
                  project_id: props.projectId,
                  function_id: func.function_id,
                  task_id: taskId
                }, { signal: abortController.signal })
                // annotate 接口返回同一个 task_id，代码已覆盖写入
                taskId = annotateRes.data.task_id
              } catch (e) {
                // 第二步失败不中断整体流程（可能该函数无设计文档）
                console.warn(`Annotate skipped for ${func.name}:`, e?.response?.data?.detail || e.message)
              }
            }

            // ── 第三步：执行测试 ──
            const execRes = await axios.post('/api/testcase/execute', { 
              task_id: taskId 
            }, {
              signal: abortController.signal
            })
            batchStatus.value.executed++
            
            const result = execRes.data
            if (result.compile_success) {
               if (result.test_result && result.test_result.failed === 0) {
                 batchStatus.value.success++
               } else {
                 batchStatus.value.failed++
               }
            } else {
               batchStatus.value.compileError++
            }
         } catch (e) {
            if (e.name === 'CanceledError' || e.message === 'Task cancelled' || e.code === 'ERR_CANCELED') {
              // Request was cancelled, don't count as failure
              console.log(`Task cancelled for ${func.name}`)
            } else {
              console.error(`Task failed for ${func.name}:`, e)
              batchStatus.value.failed++
            }
         } finally {
            queue.removeAbortController(abortController)
            batchStatus.value.completed++
         }
      })
      promises.push(p)
    }

    await Promise.allSettled(promises) // Use allSettled to handle cancellations
    
    if (!isCancelled.value) {
      batchStage.value = 3 // Done
    }

  } catch (e) {
    console.error('Batch testing error:', e)
    if (!isCancelled.value) {
      alert('全量测试过程中发生错误')
    }
  } finally {
    currentQueue = null
  }
}

const cancelTest = () => {
  if (confirm('确定要停止全量测试吗？已完成的测试结果将被保留。')) {
    isCancelled.value = true
    if (currentQueue) {
      currentQueue.cancel()
    }
    batchStage.value = 3 // Mark as finished
  }
}

const handleClose = () => {
  if (!isFinished.value && !isCancelled.value && batchStage.value > 0) {
    if (confirm('测试正在进行中，确定要关闭吗？已完成的测试结果将被保留。')) {
      cancelTest()
      close()
    }
  } else {
    close()
  }
}

const close = () => {
  visible.value = false
  emit('close')
}

const goToDashboard = () => {
  close()
  router.push('/dashboard')
}

defineExpose({ start })
</script>
