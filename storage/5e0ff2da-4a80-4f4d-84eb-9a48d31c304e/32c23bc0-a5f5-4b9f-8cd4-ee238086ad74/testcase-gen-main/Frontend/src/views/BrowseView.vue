<template>
  <div class="h-full flex overflow-hidden bg-white">
    <!-- Left Sidebar: File Tree -->
    <aside class="w-80 border-r border-slate-200 bg-slate-50 flex flex-col">
      <div class="p-4 border-b border-slate-200 flex items-center justify-between bg-white">
        <h2 class="font-bold text-sm flex items-center gap-2 text-slate-800">
          <FolderTree class="w-4 h-4 text-primary-600" />
          项目结构
        </h2>
        <div class="flex gap-1">
           <button 
            @click="triggerBatchTest" 
            class="p-1 bg-primary-50 text-primary-600 hover:bg-primary-100 rounded transition-colors"
            title="执行全量自动测试"
           >
             <Zap class="w-3.5 h-3.5" />
           </button>
           <button @click="fetchStructure" class="p-1 hover:bg-slate-100 rounded text-slate-500">
             <RotateCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
           </button>
        </div>
      </div>
      
      <div class="flex-1 overflow-y-auto p-2">
        <div v-if="loading && !treeData.length" class="p-4 text-center text-slate-400 text-xs font-medium">
          正在解析项目结构...
        </div>
        
        <div class="space-y-0.5">
          <FileTreeNode 
            v-for="node in treeData" 
            :key="node.id" 
            :node="node" 
            :depth="0"
            :selected-file-id="selectedFileId"
            :selected-function-id="store.functionId"
            @select-file="selectFile"
            @select-function="selectFunction"
          />
        </div>
      </div>
    </aside>

    <!-- Main Content: Code Viewer -->
    <main class="flex-1 flex flex-col bg-white overflow-hidden relative">
      <div class="p-4 border-b border-slate-200 bg-white flex items-center justify-between">
        <div class="flex items-center space-x-3">
          <div v-if="selectedFile" class="flex items-center space-x-2 text-sm">
            <span class="text-slate-400">/</span>
            <span class="text-slate-900 font-bold font-mono">{{ selectedFile.path }}</span>
          </div>
          <div v-if="store.functionName" class="flex items-center space-x-2 text-sm border-l border-slate-200 pl-3">
            <span class="text-primary-700 font-bold font-mono">{{ store.functionName }}()</span>
          </div>
        </div>
      </div>

      <div class="flex-1 overflow-hidden relative" id="code-viewer-container">
        <div v-if="fileLoading" class="absolute inset-0 flex items-center justify-center bg-white/80 z-50 backdrop-blur-[2px]">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
        </div>

        <div v-if="!selectedFileId" class="h-full flex flex-col items-center justify-center text-slate-300 space-y-4">
          <Code2 class="w-16 h-16 opacity-20" />
          <p class="text-sm font-medium">从左侧选择一个文件或函数以查看代码</p>
        </div>

        <pre 
          v-else 
          class="h-full overflow-auto m-0 p-4 font-mono text-sm leading-relaxed scroll-smooth bg-slate-50" 
          ref="codeContainer"
          @click="handleCodeClick"
        >
          <code class="language-c hljs" v-html="highlightedCode"></code>
        </pre>
      </div>
    </main>

    <!-- Floating Generate Button - Use a simpler structure and fixed positioning -->
    <div 
      v-if="store.functionId" 
      class="fixed bottom-10 right-10 z-[9999]"
    >
      <button 
        @click="goToGenerate"
        class="flex items-center gap-3 px-6 py-4 bg-primary-900 text-white font-bold rounded-full shadow-2xl hover:bg-primary-800 transition-all active:scale-95 border-2 border-white/20"
      >
        <div class="bg-primary-700 p-2 rounded-full">
          <Zap class="w-5 h-5 text-yellow-400 fill-current" />
        </div>
        <span class="text-lg">生成测试用例</span>
      </button>
    </div>

    <!-- Batch Test Overlay -->
    <BatchTestOverlay 
      ref="batchTestOverlay" 
      :project-id="store.projectId" 
      :concurrency="16"
    />
  </div>
</template>

<script>
export default {
  name: 'BrowseView'
}
</script>

<script setup>
import { ref, onMounted, computed, nextTick, h, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '../store'
import axios from 'axios'
import BatchTestOverlay from '../components/BatchTestOverlay.vue'
import hljs from 'highlight.js'
import { 
  FolderTree, FileCode, FileJson, RotateCw, ChevronRight, 
  Zap, Code2, Folder
} from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()
const store = useAppStore()

const batchTestOverlay = ref(null)

const loading = ref(false)
const structure = ref(null)
const treeData = ref([])
const selectedFileId = ref(null)
const selectedFile = ref(null)
const fileLoading = ref(false)
const fileContent = ref('')
const codeContainer = ref(null)

const triggerBatchTest = () => {
  if (batchTestOverlay.value) {
    batchTestOverlay.value.start()
  }
}

// FileTreeNode Component (Internal)
const FileTreeNode = {
  name: 'FileTreeNode',
  props: ['node', 'depth', 'selectedFileId', 'selectedFunctionId'],
  emits: ['select-file', 'select-function'],
  setup(props, { emit }) {
    const expanded = ref(props.depth === 0)
    
    const toggle = () => {
      expanded.value = !expanded.value
    }
    
    const handleClick = () => {
      if (props.node.type === 'file') {
        emit('select-file', props.node.data)
        expanded.value = !expanded.value
      } else {
        toggle()
      }
    }

    return () => {
      const isSelected = props.node.type === 'file' && props.selectedFileId === props.node.id
      const isJson = props.node.type === 'file' && props.node.data?.file_type === 'json'
      
      return h('div', { class: 'select-none' }, [
        h('div', {
          class: [
            'flex items-center space-x-2 px-2 py-1.5 rounded cursor-pointer transition-colors text-xs font-medium',
            isSelected
              ? (isJson ? 'bg-amber-100 text-amber-900' : 'bg-primary-100 text-primary-900')
              : 'hover:bg-slate-200 text-slate-600'
          ],
          style: { paddingLeft: `${props.depth * 12 + 8}px` },
          onClick: handleClick
        }, [
          props.node.type === 'directory' ? h(ChevronRight, {
            class: ['w-3.5 h-3.5 transition-transform text-slate-400', expanded.value ? 'rotate-90' : ''],
            onClick: (e) => { e.stopPropagation(); toggle(); }
          }) : null,
          h(
            props.node.type === 'directory' ? Folder : (isJson ? FileJson : FileCode),
            { class: ['w-4 h-4', props.node.type === 'directory' ? 'text-primary-600' : (isJson ? 'text-amber-500' : 'text-slate-400')] }
          ),
          h('span', { class: 'truncate' }, props.node.name),
          // Badge for JSON design docs
          isJson ? h('span', {
            class: 'ml-1 px-1 py-0 rounded text-[9px] font-bold bg-amber-200 text-amber-700 leading-tight shrink-0'
          }, '设计文档') : null
        ]),
        
        expanded.value && props.node.children ? h('div', { class: 'mt-0.5' }, 
          props.node.children.map(child => h(FileTreeNode, {
            node: child,
            depth: props.depth + 1,
            selectedFileId: props.selectedFileId,
            selectedFunctionId: props.selectedFunctionId,
            onSelectFile: (f) => emit('select-file', f),
            onSelectFunction: (f, func) => emit('select-function', f, func)
          }))
        ) : null,
        
        expanded.value && props.node.type === 'file' && !isJson && props.node.data.functions.length > 0 ? h('div', { class: 'mt-0.5' },
          props.node.data.functions.map(func => {
            const isFuncSelected = props.selectedFunctionId === func.function_id
            return h('div', {
              class: [
                'flex items-center space-x-2 px-2 py-1 cursor-pointer transition-colors text-[11px] font-bold group',
                isFuncSelected ? 'text-primary-700 bg-primary-50/50' : 'text-slate-500 hover:text-primary-600 hover:bg-slate-100'
              ],
              style: { paddingLeft: `${(props.depth + 1) * 12 + 24}px` },
              onClick: () => emit('select-function', props.node.data, func)
            }, [
              h('div', { 
                class: [
                  'w-1.5 h-1.5 rounded-full transition-colors',
                  isFuncSelected ? 'bg-primary-600' : 'bg-slate-300 group-hover:bg-primary-400'
                ] 
              }),
              h('span', { class: 'truncate' }, func.name)
            ])
          })
        ) : null
      ])
    }
  }
}

const highlightedCode = computed(() => {
  if (!fileContent.value) return ''
  const lang = selectedFile.value?.file_type === 'json' ? 'json' : 'c'
  const result = hljs.highlight(fileContent.value, { language: lang }).value
  const highlightedLines = result.split('\n')
  
  return highlightedLines.map((line, idx) => {
    const lineNum = idx + 1
    const func = lang === 'c'
      ? selectedFile.value?.functions.find(f => lineNum >= f.start_line && lineNum <= f.end_line)
      : null
    const isTarget = store.functionId && func?.function_id === store.functionId
    const isInFunction = !!func
    
    return `<div class="flex group ${isTarget ? 'bg-primary-100/50' : ''} ${isInFunction ? 'cursor-pointer hover:bg-slate-200/50' : ''}" id="line-${lineNum}">
      <span class="w-12 inline-block text-slate-300 text-right select-none pr-4 group-hover:text-slate-400 font-bold">${lineNum}</span>
      <span class="flex-1">${line || ' '}</span>
    </div>`
  }).join('')
})

const buildTree = (files) => {
  const root = []
  const map = {}

  files.forEach(file => {
    const parts = file.path.split('/')
    let currentLevel = root
    let pathAcc = ''

    parts.forEach((part, index) => {
      pathAcc = pathAcc ? `${pathAcc}/${part}` : part
      const isLast = index === parts.length - 1
      
      if (!map[pathAcc]) {
        const node = {
          id: pathAcc,
          name: part,
          type: isLast ? 'file' : 'directory',
          path: pathAcc,
          data: isLast ? file : null,
          children: isLast ? null : []
        }
        map[pathAcc] = node
        currentLevel.push(node)
      }
      
      if (!isLast) {
        currentLevel = map[pathAcc].children
      }
    })
  })

  // Sort: directories first, then files
  const sortNodes = (nodes) => {
    nodes.sort((a, b) => {
      if (a.type !== b.type) {
        return a.type === 'directory' ? -1 : 1
      }
      return a.name.localeCompare(b.name)
    })
    nodes.forEach(node => {
      if (node.children) sortNodes(node.children)
    })
  }
  
  sortNodes(root)
  return root
}

const fetchStructure = async () => {
  loading.value = true
  try {
    const response = await axios.get(`/api/project/${store.projectId}/structure`)
    structure.value = response.data
    treeData.value = buildTree(structure.value.files)
    
    // Check for query params to auto-select
    const targetPath = route.query.file
    if (targetPath) {
       // Need to find the node with this path.
       // The path in query might be relative "klib-master/kmath.c" or similar.
       // structure.files contains objects with { path: "..." }
       // Let's try to match it.
       const targetFile = structure.value.files.find(f => f.path === targetPath || f.path.endsWith(`/${targetPath}`))
       
       if (targetFile) {
           await selectFile(targetFile)
           
           // If we also have a functionId (from store or query?), we can highlight it.
           // store.functionId is already set by ResultDashboardView before navigation.
           if (store.functionId) {
               const func = targetFile.functions.find(f => f.function_id === store.functionId)
               if (func) {
                   nextTick(() => {
                        const el = document.getElementById(`line-${func.start_line}`)
                        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
                   })
               }
           }
       }
    }
  } catch (error) {
    console.error('Fetch structure failed:', error)
  } finally {
    loading.value = false
  }
}

const selectFile = async (file) => {
  if (selectedFileId.value === file.file_id) return
  
  selectedFileId.value = file.file_id
  selectedFile.value = file
  fileLoading.value = true
  
  try {
    const response = await axios.get(`/api/project/${store.projectId}/file`, {
      params: { file_id: file.file_id }
    })
    fileContent.value = response.data.content
  } catch (error) {
    console.error('Fetch file content failed:', error)
    fileContent.value = '无法加载文件内容'
  } finally {
    fileLoading.value = false
  }
}

const selectFunction = async (file, func) => {
  console.log('Selecting function:', func.name, func.function_id)
  await selectFile(file)
  store.setFunction(func.function_id, func.name)
  console.log('Store functionId after set:', store.functionId)
  
  nextTick(() => {
    const el = document.getElementById(`line-${func.start_line}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  })
}

const handleCodeClick = (event) => {
  const lineEl = event.target.closest('.group')
  if (!lineEl || !selectedFile.value) return
  
  const lineId = lineEl.id
  if (!lineId) return
  
  const lineNum = parseInt(lineId.replace('line-', ''))
  if (isNaN(lineNum)) return
  
  // Find if this line belongs to a function
  const func = selectedFile.value.functions.find(f => lineNum >= f.start_line && lineNum <= f.end_line)
  if (func) {
    selectFunction(selectedFile.value, func)
  }
}

const goToGenerate = () => {
  router.push('/generate')
}

// Watch for project change to reset view
watch(() => store.projectId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    structure.value = null
    treeData.value = []
    selectedFileId.value = null
    selectedFile.value = null
    fileContent.value = ''
    fetchStructure()
  }
})

onMounted(() => {
  fetchStructure()
})
</script>

<style scoped>
pre {
  background: transparent !important;
}
:deep(.hljs) {
  background: transparent !important;
  padding: 0 !important;
  color: #334155;
}
:deep(.hljs-keyword), :deep(.hljs-selector-tag) { color: #1e40af; font-weight: bold; }
:deep(.hljs-title), :deep(.hljs-section) { color: #1d4ed8; font-weight: bold; }
:deep(.hljs-string) { color: #059669; }
:deep(.hljs-comment) { color: #94a3b8; font-style: italic; }
:deep(.hljs-number) { color: #d97706; }
:deep(.hljs-type) { color: #7c3aed; }

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
</style>
