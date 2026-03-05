<template>
  <div class="detail-page">
    <div class="top-bar">
      <div class="breadcrumbs">
        <button class="crumb-btn" @click="goBack">项目管理</button>
        <span>/</span>
        <span class="current">{{ itemName }}</span>
      </div>
      <div class="status">{{ selectedFilePath || '未选择文件' }}</div>
    </div>
    <div v-if="notice.visible" class="notice-bar">
      {{ notice.message }}（错误码：{{ notice.code }}）
    </div>

    <div class="split-wrap">
      <div class="left-card" :style="{ width: `${leftWidth}%` }">
        <div class="card-header">文件目录结构</div>
        <div class="tree-toolbar">
          <input v-model="keyword" class="search-input" placeholder="搜索文件或文件夹" />
        </div>
        <ul class="tree-root">
          <SoftwareTreeNode
            v-for="node in filteredNodes"
            :key="node.path"
            :node="node"
            :selected-path="selectedFilePath"
            :expanded-map="expandedMap"
            :keyword="keyword"
            @toggle-dir="toggleDir"
            @open-file="openFile"
            @contextmenu="openContextMenu"
          />
        </ul>
      </div>
      <div class="splitter" @mousedown="startDrag"></div>
      <div class="right-card" :style="{ width: `${100 - leftWidth}%` }">
        <div class="viewer-meta">
          <span>路径：{{ selectedFilePath || '-' }}</span>
          <span>语言：{{ currentMeta.language }}</span>
          <span>体积：{{ formatBytes(currentMeta.size) }}</span>
          <span>修改时间：{{ currentMeta.updated_at || '-' }}</span>
        </div>
        <div class="viewer-body">
          <div v-if="binaryKind === 'image'" class="binary-view">
            <img :src="binarySource" class="preview-image" />
          </div>
          <div v-else-if="binaryKind === 'pdf'" class="binary-view">
            <iframe :src="binarySource" class="preview-pdf"></iframe>
          </div>
          <div v-else-if="binaryKind === 'other'" class="empty-view">该二进制文件暂不支持预览</div>
          <div v-else-if="!selectedFilePath" class="empty-view">请选择左侧文件进行查看</div>
          <CodeEditor
            v-else
            v-model:value="editorContent"
            :language="language"
            :theme="theme"
          />
        </div>
      </div>
    </div>

    <div v-if="menuVisible" class="context-menu" :style="{ left: `${menuX}px`, top: `${menuY}px` }">
      <button @click="handleNodeAction('new_file')">新建文件</button>
      <button @click="handleNodeAction('new_folder')">新建文件夹</button>
      <button @click="handleNodeAction('rename')">重命名</button>
      <button @click="handleNodeAction('delete')">删除</button>
      <button @click="copyRelativePath">复制相对路径</button>
    </div>

    <div v-if="loadingMask" class="loading-mask">处理中...</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CodeEditor from '../../components/CodeEditor.vue'
import SoftwareTreeNode from '../../components/software-detail/SoftwareTreeNode.vue'
import type { FileContentResponse, FileTreeNode } from '../../api/projects'
import { getItemFileContent, getItemStructure, operateItemNode } from '../../api/projects'
import { filterTreeNodes, getLanguageByPath, getThemeBySystem, isBinaryPath } from './softwareDetail.utils'
import { pushFrontLog } from '../../utils/frontLogger'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => route.params.projectId as string)
const itemId = computed(() => route.params.itemId as string)
const itemName = computed(() => (route.query.itemName as string) || '项目详情')

const nodes = ref<FileTreeNode[]>([])
const expandedMap = reactive<Record<string, boolean>>({})
const selectedFilePath = ref('')
const editorContent = ref('')
const keyword = ref('')
const loadingMask = ref(false)
const leftWidth = ref(30)

const language = computed(() => getLanguageByPath(selectedFilePath.value))
const theme = computed(() => getThemeBySystem(window.matchMedia('(prefers-color-scheme: dark)').matches))
const filteredNodes = computed(() => filterTreeNodes(nodes.value, keyword.value))
const currentMeta = reactive<{ language: string; size: number; updated_at: string }>({
  language: '-',
  size: 0,
  updated_at: ''
})

const binarySource = ref('')
const binaryKind = ref<'none' | 'image' | 'pdf' | 'other'>('none')
const notice = reactive({ visible: false, message: '', code: 0 })

const menuVisible = ref(false)
const menuX = ref(0)
const menuY = ref(0)
const activeNode = ref<FileTreeNode | null>(null)

const formatBytes = (bytes: number) => {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

const showError = (error: any, fallback: string) => {
  const code = Number(error?.code || 500)
  const message = error?.message || fallback
  notice.visible = true
  notice.message = message
  notice.code = code
  pushFrontLog({ level: 'error', message, code, detail: JSON.stringify(error?.data || {}) })
}

const fetchRoot = async () => {
  loadingMask.value = true
  try {
    const res: any = await getItemStructure(projectId.value, itemId.value, '')
    nodes.value = res.data.children || []
    expandedMap[''] = true
    const readme = nodes.value.find((n) => n.type === 'file' && n.name.toLowerCase() === 'readme.md')
    if (readme) {
      await openFile(readme)
    }
  } catch (error: any) {
    console.error('load tree failed', error)
    showError(error, '目录加载失败')
  } finally {
    loadingMask.value = false
  }
}

const fetchChildren = async (node: FileTreeNode) => {
  const res: any = await getItemStructure(projectId.value, itemId.value, node.path)
  node.children = res.data.children || []
}

const toggleDir = async (node: FileTreeNode) => {
  if (node.type !== 'dir') return
  const next = !expandedMap[node.path]
  expandedMap[node.path] = next
  if (next && (!node.children || node.children.length === 0)) {
    try {
      loadingMask.value = true
      await fetchChildren(node)
    } catch (error: any) {
      console.error('load children failed', error)
      showError(error, '目录加载失败')
    } finally {
      loadingMask.value = false
    }
  }
}

const applyFileData = (data: FileContentResponse) => {
  currentMeta.language = data.language || '-'
  currentMeta.size = data.size || 0
  currentMeta.updated_at = data.updated_at || ''
  if (data.kind === 'binary') {
    const mime = data.mime_type || 'application/octet-stream'
    const src = `data:${mime};base64,${data.content_base64 || ''}`
    binarySource.value = src
    if (mime.startsWith('image/')) binaryKind.value = 'image'
    else if (mime === 'application/pdf') binaryKind.value = 'pdf'
    else binaryKind.value = 'other'
    editorContent.value = ''
    return
  }
  binaryKind.value = 'none'
  binarySource.value = ''
  editorContent.value = data.content || ''
}

const openFile = async (node: FileTreeNode) => {
  selectedFilePath.value = node.path
  menuVisible.value = false
  try {
    loadingMask.value = true
    if (isBinaryPath(node.path)) {
      const res: any = await getItemFileContent(projectId.value, itemId.value, node.path)
      applyFileData(res.data)
      return
    }
    let res: any
    try {
      res = await getItemFileContent(projectId.value, itemId.value, node.path)
    } catch (error: any) {
      if (error.code === 413) {
        const ok = window.confirm('文件超过 1 MB，是否继续分片加载？')
        if (!ok) return
        let offset = 0
        const chunk = 256 * 1024
        let content = ''
        while (true) {
          const chunkRes: any = await getItemFileContent(projectId.value, itemId.value, node.path, {
            allowLarge: true,
            offset,
            limit: chunk
          })
          content += chunkRes.data.content || ''
          if (chunkRes.data.eof) {
            res = { data: { ...chunkRes.data, content } }
            break
          }
          offset += chunkRes.data.limit
        }
      } else {
        throw error
      }
    }
    applyFileData(res.data)
  } catch (error: any) {
    console.error('open file failed', error)
    showError(error, '文件打开失败')
  } finally {
    loadingMask.value = false
  }
}

const goBack = () => {
  router.push({
    name: 'ProjectItems',
    params: { projectId: projectId.value },
    query: route.query
  })
}

const openContextMenu = (event: MouseEvent, node: FileTreeNode) => {
  activeNode.value = node
  menuX.value = event.clientX
  menuY.value = event.clientY
  menuVisible.value = true
}

const refreshNode = async () => {
  if (!activeNode.value) {
    await fetchRoot()
    return
  }
  const p = activeNode.value.type === 'dir' ? activeNode.value.path : activeNode.value.path.split('/').slice(0, -1).join('/')
  if (!p) {
    await fetchRoot()
    return
  }
  const res: any = await getItemStructure(projectId.value, itemId.value, p)
  const walk = (list: FileTreeNode[]) => {
    for (const n of list) {
      if (n.path === p) {
        n.children = res.data.children || []
        return true
      }
      if (n.children?.length && walk(n.children)) return true
    }
    return false
  }
  walk(nodes.value)
}

const handleNodeAction = async (action: 'new_file' | 'new_folder' | 'rename' | 'delete') => {
  if (!activeNode.value) return
  let payload: { action: 'new_file' | 'new_folder' | 'rename' | 'delete'; path: string; newName?: string } = {
    action,
    path: activeNode.value.path
  }
  if (action === 'new_file' || action === 'new_folder') {
    const name = window.prompt(action === 'new_file' ? '请输入文件名' : '请输入文件夹名')
    if (!name) return
    payload.path = `${activeNode.value.type === 'dir' ? activeNode.value.path : activeNode.value.path.split('/').slice(0, -1).join('/')}/${name}`.replace(/^\/+/, '')
  }
  if (action === 'rename') {
    const name = window.prompt('请输入新名称', activeNode.value.name)
    if (!name) return
    payload.newName = name
  }
  if (action === 'delete') {
    const ok = window.confirm(`确认删除 ${activeNode.value.name} 吗？`)
    if (!ok) return
  }
  try {
    loadingMask.value = true
    await operateItemNode(projectId.value, itemId.value, payload)
    await refreshNode()
  } catch (error: any) {
    console.error('node operation failed', error)
    showError(error, '文件操作失败')
  } finally {
    loadingMask.value = false
    menuVisible.value = false
  }
}

const copyRelativePath = async () => {
  if (!activeNode.value) return
  await navigator.clipboard.writeText(activeNode.value.path)
  menuVisible.value = false
}

const onDocClick = () => {
  menuVisible.value = false
}

const startDrag = (event: MouseEvent) => {
  const startX = event.clientX
  const start = leftWidth.value
  const onMove = (e: MouseEvent) => {
    const delta = e.clientX - startX
    const percent = start + (delta / window.innerWidth) * 100
    leftWidth.value = Math.min(60, Math.max(20, percent))
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  fetchRoot()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
})
</script>

<style scoped>
.detail-page { padding: 16px; height: calc(100vh - 64px); position: relative; }
.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.notice-bar {
  margin-bottom: 10px;
  padding: 8px 12px;
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #b91c1c;
  border-radius: 6px;
  font-size: 13px;
}
.breadcrumbs { display: flex; align-items: center; gap: 8px; color: #64748b; }
.crumb-btn { background: none; border: none; color: #2563eb; cursor: pointer; padding: 0; }
.current { color: #1e293b; font-weight: 600; }
.status { color: #64748b; font-size: 12px; }
.split-wrap {
  display: flex;
  height: calc(100% - 40px);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}
.left-card, .right-card { background: #fff; height: 100%; overflow: hidden; display: flex; flex-direction: column; }
.card-header {
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
  font-size: 14px;
  font-weight: 600;
}
.tree-toolbar { padding: 8px; border-bottom: 1px solid #e2e8f0; }
.search-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 6px 10px;
}
.tree-root {
  margin: 0;
  padding: 8px;
  list-style: none;
  overflow: auto;
  flex: 1;
}
.splitter {
  width: 6px;
  cursor: col-resize;
  background: #e2e8f0;
  flex-shrink: 0;
}
.viewer-meta {
  display: flex;
  gap: 16px;
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
  overflow: auto;
}
.viewer-body { flex: 1; min-height: 0; }
.empty-view {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
}
.binary-view {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
}
.preview-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.preview-pdf {
  width: 100%;
  height: 100%;
  border: none;
}
.context-menu {
  position: fixed;
  z-index: 150;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.15);
  min-width: 140px;
  overflow: hidden;
}
.context-menu button {
  width: 100%;
  text-align: left;
  border: none;
  background: white;
  padding: 8px 10px;
  cursor: pointer;
}
.context-menu button:hover { background: #f1f5f9; }
.loading-mask {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 120;
  color: #1e3a8a;
  font-weight: 600;
}
@media (max-width: 1366px) {
  .viewer-meta { gap: 10px; }
}
</style>
