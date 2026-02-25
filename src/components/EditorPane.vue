<template>
  <div class="editor">
    <div class="toolbar">
      <div class="title">{{ filePath || '未选择文件' }}</div>
      <div class="actions" v-if="filePath">
        <button class="btn" @click="toggleStructure" :class="{ active: showStructure }" title="Toggle Outline">Structure</button>
        <button class="btn" @click="onSave">保存</button>
        <button class="btn" @click="onDownload">下载</button>
      </div>
    </div>
    <div class="body">
      <div v-if="filePath" class="content-wrap">
        <div v-if="loading" class="loading">加载中...</div>
        <div v-else-if="error" class="error">
          <div class="error-text">{{ error }}</div>
          <button class="btn retry" @click="loadContent">重试</button>
        </div>
        <div v-else-if="unsupported" class="unsupported">当前文件不支持预览</div>
        <div v-else class="editor-layout">
          <div class="main-editor">
            <CodeEditor
              v-model:value="content"
              :language="language"
              @editor-mounted="onEditorMounted"
            />
          </div>
          <div class="side-panel" v-show="showStructure">
            <CodeStructure :editor="editorInstance" />
          </div>
        </div>
      </div>
      <div v-else class="placeholder">选择左侧文件开始编辑</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { watch, ref, computed, shallowRef } from 'vue'
import { getProjectFileContent } from '../api/projects'
import CodeEditor from './CodeEditor.vue'
import CodeStructure from './CodeStructure.vue'
import * as monaco from 'monaco-editor'

const props = defineProps<{ projectId: string; filePath?: string; fileType?: string }>()
const content = ref('')
const loading = ref(false)
const error = ref('')
const unsupported = ref(false)
const showStructure = ref(true)
const editorInstance = shallowRef<monaco.editor.IStandaloneCodeEditor | null>(null)
let requestSeq = 0

const language = computed(() => {
  if (!props.filePath) return 'plaintext'
  const ext = props.filePath.split('.').pop()?.toLowerCase()
  if (ext === 'js' || ext === 'jsx') return 'javascript'
  if (ext === 'ts' || ext === 'tsx') return 'typescript'
  if (ext === 'html') return 'html'
  if (ext === 'css') return 'css'
  if (ext === 'json') return 'json'
  if (ext === 'py') return 'python'
  if (ext === 'vue') return 'html' // Monaco's vue support needs plugins, fallback to html for now
  return 'plaintext'
})

const onEditorMounted = (editor: monaco.editor.IStandaloneCodeEditor) => {
  editorInstance.value = editor
}

const toggleStructure = () => {
  showStructure.value = !showStructure.value
  // Resize editor after layout change
  setTimeout(() => {
    editorInstance.value?.layout()
  }, 50)
}

watch(
  () => props.filePath,
  async (p) => {
    content.value = ''
    error.value = ''
    unsupported.value = false
    if (p) {
      await loadContent()
    }
  },
  { immediate: true }
)

const loadContent = async () => {
  if (!props.filePath) return
  const seq = ++requestSeq
  loading.value = true
  error.value = ''
  unsupported.value = false
  try {
    const res: any = await getProjectFileContent(props.projectId, props.filePath)
    if (seq !== requestSeq) return
    content.value = res.data?.content ?? ''
  } catch (e: any) {
    if (seq !== requestSeq) return
    if (e.code === 415) {
      unsupported.value = true
      return
    }
    error.value = e.message || '加载失败'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

const onSave = () => {
  // TODO: 接入后端保存接口
}

const onDownload = () => {
  if (!props.filePath) return
  const blob = new Blob([content.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = props.filePath.split('/').pop() || 'file.txt'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid #e2e8f0;
  background: #fff;
}
.title {
  font-size: 14px;
  color: #334155;
}
.actions .btn {
  margin-left: 8px;
  padding: 6px 10px;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #0f172a;
}
.actions .btn.active {
  background: #e0e7ff;
  border-color: #a5b4fc;
  color: #4338ca;
}
.actions .btn:hover {
  background: #eff6ff;
  border-color: #bfdbfe;
}
.body {
  flex: 1;
  display: flex;
  overflow: hidden;
  background: #1e1e1e; /* Match editor bg */
}
.content-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.editor-layout {
  flex: 1;
  display: flex;
  height: 100%;
  overflow: hidden;
}
.main-editor {
  flex: 1;
  overflow: hidden;
}
.side-panel {
  width: 250px;
  border-left: 1px solid #333;
  flex-shrink: 0;
}
.placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  background: #fff;
}
.loading,
.unsupported,
.error {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  flex-direction: column;
  gap: 10px;
  background: #fff;
}
.error-text {
  color: #ef4444;
}
.retry {
  padding: 6px 10px;
  font-size: 12px;
}
</style>
