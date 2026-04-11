<template>
  <div class="h-full overflow-y-auto p-8 bg-white">
    <div class="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
      <!-- Left Column: Function Analysis -->
      <div class="space-y-6">
        <div class="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
          <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <h2 class="font-bold text-slate-800 flex items-center gap-2">
              <Code2 class="w-4 h-4 text-primary-600" />
              函数基本信息
            </h2>
            <span class="text-[10px] px-2 py-0.5 bg-primary-100 text-primary-700 rounded-full border border-primary-200 font-bold uppercase tracking-wider">Target</span>
          </div>
          
          <div class="p-6 space-y-4">
            <div v-if="loading" class="animate-pulse space-y-3">
              <div class="h-4 bg-slate-100 rounded w-3/4"></div>
              <div class="h-10 bg-slate-100 rounded"></div>
              <div class="h-32 bg-slate-100 rounded"></div>
            </div>
            
            <template v-else-if="funcDetail">
              <div class="space-y-1">
                <label class="text-[10px] font-bold text-slate-400 uppercase">函数签名</label>
                <div class="font-mono text-sm text-primary-800 bg-slate-50 p-3 rounded border border-slate-200 break-all font-bold">
                  {{ funcDetail.signature }}
                </div>
              </div>

              <div class="grid grid-cols-2 gap-4">
                <div class="space-y-1">
                  <label class="text-[10px] font-bold text-slate-400 uppercase">函数名</label>
                  <p class="text-sm font-bold text-slate-700">{{ funcDetail.name }}</p>
                </div>
                <div class="space-y-1">
                  <label class="text-[10px] font-bold text-slate-400 uppercase">所在行号</label>
                  <p class="text-sm font-bold text-slate-700">L{{ funcDetail.start_line }} - L{{ funcDetail.end_line }}</p>
                </div>
              </div>
            </template>
          </div>
        </div>

        <div class="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
          <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <h2 class="font-bold text-slate-800 flex items-center gap-2">
              <Network class="w-4 h-4 text-primary-600" />
              代码图谱 (Code Graph)
            </h2>
            <div class="flex items-center gap-2">
              <button 
                @click="refreshGraph" 
                class="p-1.5 hover:bg-slate-100 rounded-full text-slate-400 hover:text-primary-600 transition-colors"
                title="重新生成图谱"
                :disabled="graphLoading"
              >
                <RefreshCw class="w-3 h-3" :class="{ 'animate-spin': graphLoading }" />
              </button>
              <span class="text-[10px] text-slate-400 font-bold uppercase">Deep Analysis</span>
              <div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
            </div>
          </div>
          <div class="p-6">
            <div v-if="graphLoading" class="flex flex-col items-center justify-center py-12 space-y-4">
              <div class="w-8 h-8 border-4 border-primary-200 border-t-primary-600 rounded-full animate-spin"></div>
              <p class="text-xs text-slate-400 font-bold animate-pulse uppercase">正在深度分析代码图谱...</p>
            </div>
            <div v-else-if="codeGraph" class="space-y-6">
              <!-- Variables -->
              <div v-if="codeGraph.variables?.length" class="space-y-3">
                <h3 class="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-2">
                  <span class="w-1 h-3 bg-primary-500 rounded-full"></span>
                  内部变量与参数
                </h3>
                <div class="flex flex-wrap gap-2">
                  <span 
                    v-for="v in codeGraph.variables" 
                    :key="v" 
                    class="px-2 py-1 bg-slate-100 text-slate-600 text-[10px] font-mono rounded border border-slate-200 hover:bg-primary-50 hover:border-primary-200 transition-colors"
                  >
                    {{ v }}
                  </span>
                </div>
              </div>

              <!-- Returns -->
              <div v-if="codeGraph.returns?.length" class="space-y-3">
                <h3 class="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-2">
                  <span class="w-1 h-3 bg-primary-500 rounded-full"></span>
                  返回值分析
                </h3>
                <div class="space-y-2">
                  <div 
                    v-for="ret in codeGraph.returns" 
                    :key="ret"
                    class="p-2 bg-slate-50 rounded border border-slate-100 font-mono text-xs text-slate-600 flex items-center gap-2"
                  >
                    <span class="text-primary-500 font-bold">return</span>
                    <span class="text-slate-700 font-medium">{{ ret }}</span>
                  </div>
                </div>
              </div>

              <!-- Graph Image -->
              <div v-if="graphItemReady.call || graphItemLoading.call" class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm relative min-h-[300px] flex items-center justify-center">
                <h3 class="absolute top-4 left-4 font-bold text-slate-700 flex items-center gap-2">
                  <Network class="w-4 h-4 text-primary-500" />
                  Call Graph (调用图)
                </h3>
                <div v-if="graphItemLoading.call" class="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
                   <RefreshCw class="w-8 h-8 animate-spin text-primary-500" />
                </div>
                <img 
                  v-if="codeGraph.graph_image"
                  :src="`/api/project/${store.projectId}/graph/${codeGraph.graph_image}?t=${codeGraph.graph_mtime || 0}`" 
                  class="max-w-full max-h-[600px] object-contain cursor-zoom-in"
                  @click="openImage(`/api/project/${store.projectId}/graph/${codeGraph.graph_image}?t=${codeGraph.graph_mtime || 0}`)"
                />
                <div v-else-if="!graphItemLoading.call" class="text-slate-400 text-sm">暂无数据</div>
              </div>

              <!-- AST Image -->
              <div v-if="graphItemReady.ast || graphItemLoading.ast" class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm relative min-h-[300px] flex items-center justify-center">
                <h3 class="absolute top-4 left-4 font-bold text-slate-700 flex items-center gap-2">
                  <GitBranch class="w-4 h-4 text-purple-500" />
                  抽象语法树 (AST)
                </h3>
                <div v-if="graphItemLoading.ast" class="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
                   <RefreshCw class="w-8 h-8 animate-spin text-purple-500" />
                </div>
                <img 
                  v-if="codeGraph.ast_image"
                  :src="`/api/project/${store.projectId}/graph/${codeGraph.ast_image}?t=${codeGraph.ast_mtime || 0}`" 
                  class="max-w-full max-h-[600px] object-contain cursor-zoom-in"
                  @click="openImage(`/api/project/${store.projectId}/graph/${codeGraph.ast_image}?t=${codeGraph.ast_mtime || 0}`)"
                />
                <div v-else-if="!graphItemLoading.ast" class="text-slate-400 text-sm">暂无数据</div>
              </div>

              <!-- CFG Image -->
              <div v-if="graphItemReady.cfg || graphItemLoading.cfg" class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm relative min-h-[300px] flex items-center justify-center">
                <h3 class="absolute top-4 left-4 font-bold text-slate-700 flex items-center gap-2">
                  <GitCommit class="w-4 h-4 text-blue-500" />
                  控制流图 (CFG)
                </h3>
                <div v-if="graphItemLoading.cfg" class="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
                   <RefreshCw class="w-8 h-8 animate-spin text-blue-500" />
                </div>
                <img 
                  v-if="codeGraph.cfg_image"
                  :src="`/api/project/${store.projectId}/graph/${codeGraph.cfg_image}?t=${codeGraph.cfg_mtime || 0}`" 
                  class="max-w-full max-h-[600px] object-contain cursor-zoom-in"
                  @click="openImage(`/api/project/${store.projectId}/graph/${codeGraph.cfg_image}?t=${codeGraph.cfg_mtime || 0}`)"
                />
                <div v-else-if="!graphItemLoading.cfg" class="text-slate-400 text-sm">暂无数据</div>
              </div>

              <!-- PDG Image -->
              <div v-if="graphItemReady.pdg || graphItemLoading.pdg" class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm relative min-h-[300px] flex items-center justify-center">
                <h3 class="absolute top-4 left-4 font-bold text-slate-700 flex items-center gap-2">
                  <GitMerge class="w-4 h-4 text-green-500" />
                  程序依赖图 (PDG)
                </h3>
                <div v-if="graphItemLoading.pdg" class="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
                   <RefreshCw class="w-8 h-8 animate-spin text-green-500" />
                </div>
                <img 
                  v-if="codeGraph.pdg_image"
                  :src="`/api/project/${store.projectId}/graph/${codeGraph.pdg_image}?t=${codeGraph.pdg_mtime || 0}`" 
                  class="max-w-full max-h-[600px] object-contain cursor-zoom-in"
                  @click="openImage(`/api/project/${store.projectId}/graph/${codeGraph.pdg_image}?t=${codeGraph.pdg_mtime || 0}`)"
                />
                <div v-else-if="!graphItemLoading.pdg" class="text-slate-400 text-sm">暂无数据</div>
              </div>
            </div>
            <div v-else class="text-center py-12 text-slate-300 text-sm font-medium italic">
              暂无图谱数据
            </div>
          </div>
        </div>

        <!-- Function Intent -->
        <div class="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
          <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <h2 class="font-bold text-slate-800 flex items-center gap-2">
              <Sparkles class="w-4 h-4 text-primary-600" />
              函数意图 (Intent)
            </h2>
            <button 
              @click="generateIntent" 
              class="text-[10px] px-2 py-1 bg-primary-600 text-white rounded hover:bg-primary-700 transition-colors flex items-center gap-1"
              :disabled="intentLoading"
            >
              <RefreshCw class="w-3 h-3" :class="{ 'animate-spin': intentLoading }" />
              AI 辅助生成
            </button>
          </div>
          <div class="p-4">
            <textarea 
              v-model="functionIntent"
              placeholder="输入函数的设计意图，或点击 AI 辅助生成。明确的意图有助于生成更准确的测试用例。"
              class="w-full h-24 p-3 text-xs text-slate-600 border border-slate-200 rounded-lg focus:ring-1 focus:ring-primary-500 focus:border-primary-500 resize-none font-medium"
            ></textarea>
            <div class="mt-2 text-[10px] text-slate-500 bg-slate-50 p-2 rounded border border-slate-100">
              <span class="font-bold text-primary-600">提示：</span>
              函数意图需遵循 ISO/IEC/IEEE 29119 三段式结构：
              <ul class="list-disc list-inside mt-1 ml-1 space-y-0.5">
                <li><span class="font-bold">Objective (必需):</span> 测试目标描述</li>
                <li><span class="font-bold">Preconditions (可选):</span> 前置条件</li>
                <li><span class="font-bold">Expected Results (可选):</span> 预期结果</li>
              </ul>
            </div>
          </div>
        </div>

        <!-- Generation Controls -->
        <div class="bg-slate-50 border border-slate-200 rounded-xl p-6 space-y-6">
          <div class="space-y-3">
            <label class="text-sm font-bold text-slate-600 uppercase tracking-wider">测试框架</label>
            <div class="grid grid-cols-3 gap-3">
              <button 
                v-for="framework in ['unity', 'cmockery', 'gtest']" 
                :key="framework"
                @click="selectedFramework = framework"
                class="px-4 py-2 rounded-lg text-xs font-bold uppercase transition-all"
                :class="selectedFramework === framework ? 'bg-primary-900 text-white shadow-md' : 'bg-white text-slate-400 border border-slate-200 hover:bg-slate-100'"
              >
                {{ framework }}
              </button>
            </div>
          </div>

          <button 
            @click="generateTest"
            :disabled="generating || annotating"
            class="w-full py-4 bg-primary-900 hover:bg-primary-800 disabled:bg-slate-200 text-white font-bold rounded-xl transition-all flex items-center justify-center space-x-3 shadow-lg"
          >
            <Zap class="w-5 h-5" :class="{ 'animate-pulse': generating || annotating }" />
            <span>
              {{ generating ? 'AI 正在编写测试代码...' : annotating ? 'AI 正在插入设计文档注释...' : '立即生成测试用例' }}
            </span>
          </button>
        </div>
      </div>

      <!-- Right Column: Generated Code -->
      <div class="flex flex-col h-[calc(100vh-160px)] min-h-[600px] sticky top-8">
        <div class="bg-white border border-slate-200 rounded-xl overflow-hidden flex flex-col h-full shadow-md">
          <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <h2 class="font-bold text-slate-800 flex items-center gap-2">
              <FileCode class="w-4 h-4 text-primary-600" />
              生成的测试代码
            </h2>
            <div v-if="generatedCode" class="flex items-center space-x-2">
              <button @click="copyCode" class="p-2 hover:bg-slate-200 rounded text-slate-500 transition-colors" title="复制代码">
                <Copy class="w-4 h-4" />
              </button>
              <button 
                @click="goToResult"
                class="flex items-center space-x-2 px-3 py-1 bg-green-600 hover:bg-green-700 text-white text-[10px] font-bold uppercase rounded transition-colors shadow-sm"
              >
                <Play class="w-3 h-3" />
                <span>编译并执行</span>
              </button>
            </div>
          </div>
          
          <div class="flex-1 overflow-hidden relative bg-slate-50">
            <div v-if="generating && !generatedCode" class="absolute inset-0 flex flex-col items-center justify-center space-y-4 z-10 backdrop-blur-[2px] bg-white/50">
              <div class="relative w-16 h-16">
                <div class="absolute inset-0 border-4 border-primary-100 rounded-full"></div>
                <div class="absolute inset-0 border-4 border-primary-600 border-t-transparent rounded-full animate-spin"></div>
              </div>
              <p class="text-sm text-primary-700 font-bold">LLM 正在深度分析逻辑并构造用例...</p>
            </div>

            <!-- Small indicator when streaming -->
            <div v-if="generating && generatedCode" class="absolute top-4 right-6 z-10 flex items-center gap-2 px-3 py-1.5 bg-white/90 backdrop-blur border border-primary-100 rounded-full shadow-sm">
              <div class="flex space-x-1">
                <div class="w-1.5 h-1.5 bg-primary-600 rounded-full animate-bounce" style="animation-delay: 0ms"></div>
                <div class="w-1.5 h-1.5 bg-primary-600 rounded-full animate-bounce" style="animation-delay: 150ms"></div>
                <div class="w-1.5 h-1.5 bg-primary-600 rounded-full animate-bounce" style="animation-delay: 300ms"></div>
              </div>
              <span class="text-[10px] font-bold text-primary-700 uppercase tracking-wider">AI Streaming...</span>
            </div>

            <div v-if="!generatedCode && !generating" class="h-full flex flex-col items-center justify-center text-slate-300 space-y-4 p-12 text-center">
              <Sparkles class="w-16 h-16 opacity-20" />
              <p class="text-sm font-medium max-w-xs">点击左侧按钮，由 AI 根据函数语义和图谱分析自动生成高质量单元测试代码</p>
            </div>

            <pre v-if="generatedCode" ref="codeContainer" class="h-full overflow-auto m-0 p-6 font-mono text-sm leading-relaxed scroll-smooth">
              <code class="language-c hljs" v-html="highlightedGeneratedCode"></code>
            </pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'GenerateView'
}
</script>

<script setup>
import { ref, onMounted, onActivated, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../store'
import axios from 'axios'
import hljs from 'highlight.js'
import { 
  Code2, Network, Zap, FileCode, Sparkles, 
  Copy, Play, RefreshCw
} from 'lucide-vue-next'

const router = useRouter()
const store = useAppStore()

const codeContainer = ref(null)
const loading = ref(false)
const graphLoading = ref(false)
const graphItemLoading = ref({
  call: false,
  ast: false,
  cfg: false,
  pdg: false
})
const graphItemReady = ref({
  call: false,
  ast: false,
  cfg: false,
  pdg: false
})
const generating = ref(false)
const annotating = ref(false)  // 第二步：插入设计文档注释中
const funcDetail = ref(null)
const codeGraph = ref({
  variables: [],
  calls: [],
  returns: [],
  graph_image: null,
  ast_image: null,
  cfg_image: null,
  pdg_image: null
})

const selectedFramework = ref('unity')
const generatedCode = ref('')
const functionIntent = ref('')
const intentLoading = ref(false)
// We don't need a global graphTimestamp anymore, as each image will have its own mtime
// const graphTimestamp = ref(Date.now())

const highlightedGeneratedCode = computed(() => {
  if (!generatedCode.value) return ''
  return hljs.highlight(generatedCode.value, { language: 'c' }).value
})

watch(generatedCode, () => {
  if (generating.value && codeContainer.value) {
    nextTick(() => {
      codeContainer.value.scrollTop = codeContainer.value.scrollHeight
    })
  }
})

const generateIntent = async () => {
  if (!store.functionId) return
  intentLoading.value = true
  functionIntent.value = ''
  try {
    const response = await fetch('/api/testcase/intent/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        project_id: store.projectId,
        function_id: store.functionId
      })
    })

    if (!response.ok) throw new Error('Network response was not ok')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      functionIntent.value += decoder.decode(value, { stream: true })
    }
  } catch (error) {
    console.error('Generate intent failed:', error)
  } finally {
    intentLoading.value = false
  }
}

const fetchFunctionDetail = async () => {
  if (!store.functionId) return
  loading.value = true
  // Reset state
  codeGraph.value = {
    variables: [],
    calls: [],
    returns: [],
    graph_image: null,
    ast_image: null,
    cfg_image: null,
    pdg_image: null
  }
  try {
    const response = await axios.get(`/api/project/${store.projectId}/function/${store.functionId}`)
    funcDetail.value = response.data
    // After basic info, fetch graph
    fetchCodeGraph()
    // Fetch history (intent, test case)
    fetchHistory()
  } catch (error) {
    console.error('Fetch function detail failed:', error)
  } finally {
    loading.value = false
  }
}

const fetchCodeGraph = async (refresh = false) => {
  graphLoading.value = true
  // Reset individual loading and ready states
  Object.keys(graphItemLoading.value).forEach(key => {
    graphItemLoading.value[key] = true
    graphItemReady.value[key] = false
  })
  
  try {
    // 1. Fetch metadata first (fast)
    const metaResponse = await axios.get(`/api/project/${store.projectId}/function/${store.functionId}/graph`, {
      params: { use_joern: true, refresh: refresh }
    })
    
    const { graph_image, ast_image, cfg_image, pdg_image, ...metadata } = metaResponse.data
    codeGraph.value = { ...codeGraph.value, ...metadata }
    
    if (refresh) {
      // graphTimestamp.value = Date.now()
    }

    // 2. Fetch specific graphs in parallel
    const graphTypes = ['call', 'ast', 'cfg', 'pdg']
    graphTypes.forEach(type => {
      graphItemLoading.value[type] = true
      axios.get(`/api/project/${store.projectId}/function/${store.functionId}/graph/${type}`, {
        params: { refresh: refresh }
      }).then(res => {
        const key = type === 'call' ? 'graph_image' : `${type}_image`
        const mtimeKey = type === 'call' ? 'graph_mtime' : `${type}_mtime`
        
        codeGraph.value[key] = res.data.image
        codeGraph.value[mtimeKey] = res.data.mtime // Use mtime from backend
        
        graphItemReady.value[type] = true
      }).catch(err => {
        console.error(`Failed to fetch ${type} graph:`, err)
      }).finally(() => {
        graphItemLoading.value[type] = false
      })
    })
    
  } catch (error) {
    console.error('Fetch code graph failed:', error)
  } finally {
    graphLoading.value = false
  }
}

const fetchHistory = async () => {
  try {
    const response = await axios.get('/api/testcase/history', {
      params: {
        project_id: store.projectId,
        function_id: store.functionId
      }
    })
    
    if (response.data) {
      if (response.data.intent) {
        functionIntent.value = response.data.intent
      }
      if (response.data.test_code) {
        generatedCode.value = response.data.test_code
      }
      if (response.data.latest_task_id) {
        store.setTask(response.data.latest_task_id)
      }
    }
  } catch (error) {
    // Ignore 404 or other errors if history doesn't exist
    console.log('No history found or error fetching history:', error)
  }
}

const refreshGraph = () => {
  fetchCodeGraph(true)
}

const openImage = (url) => {
  window.open(url, '_blank')
}

const generateTest = async () => {
  generating.value = true
  annotating.value = false
  generatedCode.value = ''
  
  // Use failure context if available in store
  const failureContext = store.failureContext
  const failedTaskId = store.failedTaskId
  
  // Clear it immediately so it's not reused unintentionally
  if (failureContext) {
    store.setFailureContext(null)
  }

  let currentTaskId = null

  try {
    // ── 第一步：基于代码生成测试用例 ──
    const response = await fetch('/api/testcase/generate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: store.projectId,
        function_id: store.functionId,
        test_framework: selectedFramework.value,
        function_intent: functionIntent.value,
        failure_context: failureContext,
        failed_task_id: failedTaskId
      })
    })

    if (!response.ok) throw new Error('Network response was not ok')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const data = JSON.parse(line)
          if (data.type === 'content') {
            generatedCode.value += data.content
          } else if (data.type === 'task_id') {
            currentTaskId = data.task_id
            store.setTask(data.task_id)
          }
        } catch (e) {
          console.error('Parse error:', e, line)
        }
      }
    }

    // ── 第二步：若项目有设计文档，插入中文注释 ──
    if (currentTaskId) {
      try {
        const hdRes = await axios.get(`/api/project/${store.projectId}/has-design-doc`)
        if (hdRes.data.has_design_doc) {
          generating.value = false
          annotating.value = true
          generatedCode.value = ''  // 清空，流式展示带注释的版本

          const annotateRes = await fetch('/api/testcase/annotate/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              project_id: store.projectId,
              function_id: store.functionId,
              task_id: currentTaskId
            })
          })

          if (annotateRes.ok) {
            const ar = annotateRes.body.getReader()
            const ad = new TextDecoder()
            let ab = ''
            while (true) {
              const { done, value } = await ar.read()
              if (done) break
              ab += ad.decode(value, { stream: true })
              const lines = ab.split('\n')
              ab = lines.pop()
              for (const line of lines) {
                if (!line.trim()) continue
                try {
                  const data = JSON.parse(line)
                  if (data.type === 'content') {
                    generatedCode.value += data.content
                  }
                  // type === 'done' 不需要额外处理，task_id 不变
                } catch (e) { /* ignore */ }
              }
            }
          }
        }
      } catch (e) {
        // 第二步失败不影响结果，忽略即可
        console.warn('Annotate step skipped or failed:', e)
      }
    }

  } catch (error) {
    console.error('Generation failed:', error)
    alert('生成失败，请检查后端 LLM 配置')
  } finally {
    generating.value = false
    annotating.value = false
  }
}

const copyCode = () => {
  navigator.clipboard.writeText(generatedCode.value)
  alert('代码已复制到剪贴板')
}

const goToResult = () => {
  router.push('/result')
}

// Watch for function change to refresh data
watch(() => store.functionId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    // Reset state for new function
    funcDetail.value = null
    codeGraph.value = null
    generatedCode.value = ''
    fetchFunctionDetail()
  }
})

const checkFailureAndGenerate = () => {
  if (store.failureContext) {
    generateTest()
  }
}

onMounted(() => {
  fetchFunctionDetail()
  checkFailureAndGenerate()
})

onActivated(() => {
  checkFailureAndGenerate()
})
</script>

<style scoped>
pre {
  background: transparent !important;
}
:deep(.hljs) {
  background: transparent !important;
  padding: 0 !important;
}
</style>
