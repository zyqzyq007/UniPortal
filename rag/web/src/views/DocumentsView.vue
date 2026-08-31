<template>
  <div class="documents-view">
    <!-- Page Header -->
    <div class="page-header">
      <div class="header-content">
        <h1>文档管理</h1>
        <p>上传和管理知识库文档，支持 Markdown、文本和 PDF 格式</p>
      </div>
      <div class="header-stats">
        <div class="stat-item">
          <span class="stat-value">{{ documents.length }}</span>
          <span class="stat-label">文档总数</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ totalChunks }}</span>
          <span class="stat-label">分块数量</span>
        </div>
      </div>
    </div>

    <!-- Upload Area -->
    <div
      class="upload-area"
      :class="{ dragging: isDragging }"
      @drop.prevent="handleDrop"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      data-testid="upload-area"
    >
      <input
        type="file"
        ref="fileInput"
        @change="handleFileSelect"
        accept=".md,.txt,.pdf"
        hidden
        multiple
        data-testid="file-input"
      />
      <div class="upload-content" @click="($refs.fileInput as any)?.click()">
        <div class="upload-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
        </div>
        <h3>拖拽文件到此处上传</h3>
        <p>或点击选择文件</p>
        <div class="upload-formats">
          <span class="format-badge">.md</span>
          <span class="format-badge">.txt</span>
          <span class="format-badge">.pdf</span>
        </div>
      </div>
    </div>

    <!-- Upload Progress -->
    <div v-if="uploading" class="upload-progress">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div>
      </div>
      <span class="progress-text">正在上传 ({{ uploadCurrent }}/{{ uploadTotal }})... {{ uploadProgress }}%</span>
    </div>

    <!-- Document List -->
    <div class="document-section">
      <div class="section-header">
        <h2>已上传文档</h2>
        <div class="section-actions">
          <div class="search-box">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"/>
              <path d="M21 21l-4.35-4.35"/>
            </svg>
            <input type="text" v-model="searchQuery" placeholder="搜索文档..." data-testid="doc-search" />
          </div>
        </div>
      </div>

      <div v-if="filteredDocuments.length === 0" class="empty-state" data-testid="doc-empty">
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
        </div>
        <h3>暂无文档</h3>
        <p>上传文档以开始构建知识库</p>
      </div>

      <div v-else class="document-grid" data-testid="doc-grid">
        <div v-for="doc in filteredDocuments" :key="doc.id" class="document-card" data-testid="doc-card">
          <div class="doc-header">
            <div class="doc-icon" :class="getFileType(doc.filename)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
            </div>
            <div class="doc-actions">
              <button class="btn-icon-sm delete" @click="deleteDocument(doc.id)" title="删除" data-testid="doc-delete">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                </svg>
              </button>
            </div>
          </div>
          <div class="doc-body">
            <h4 class="doc-name">{{ doc.filename }}</h4>
            <div class="doc-meta">
              <span class="meta-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                {{ formatSize(doc.size_bytes) }}
              </span>
              <span class="meta-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="3" width="7" height="7"/>
                  <rect x="14" y="3" width="7" height="7"/>
                  <rect x="14" y="14" width="7" height="7"/>
                  <rect x="3" y="14" width="7" height="7"/>
                </svg>
                {{ doc.chunks || 0 }} 分块
              </span>
            </div>
          </div>
          <div class="doc-footer">
            <span class="status-badge" :class="doc.status">{{ getStatusText(doc.status) }}</span>
            <span class="upload-time">{{ formatDate(doc.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useToast } from '@/stores/toast'
import { useUploadStore } from '@/stores/upload'
import { apiUrl } from '@/utils/api'

interface DocumentInfo {
  id: string
  filename: string
  status: string
  chunks: number
  created_at: number
  size_bytes: number
  file_hash: string
}

const toast = useToast()
const uploadStore = useUploadStore()
const documents = ref<DocumentInfo[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadTotal = ref(0)
const uploadCurrent = ref(0)
const searchQuery = ref('')

const totalChunks = computed(() => {
  return documents.value.reduce((sum, doc) => sum + (doc.chunks || 0), 0)
})

const filteredDocuments = computed(() => {
  if (!searchQuery.value) return documents.value
  const query = searchQuery.value.toLowerCase()
  return documents.value.filter(doc =>
    doc.filename?.toLowerCase().includes(query)
  )
})

onMounted(async () => {
  await loadDocuments()
})

async function loadDocuments() {
  try {
    const response = await fetch(apiUrl('api/documents'))
    const data = await response.json()
    documents.value = data.documents || []
  } catch (e) {
    console.error('Load documents error:', e)
  }
}

async function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) {
    await uploadFiles(Array.from(input.files))
  }
}

async function handleDrop(event: DragEvent) {
  isDragging.value = false
  const files = event.dataTransfer?.files
  if (files) {
    await uploadFiles(Array.from(files))
  }
}

async function uploadFiles(files: File[]) {
  uploading.value = true
  uploadStore.setUploading(true)
  uploadTotal.value = files.length
  uploadCurrent.value = 0
  uploadProgress.value = 0

  const failedFiles: string[] = []

  for (const file of files) {
    uploadCurrent.value++
    const ok = await uploadSingleFile(file)
    if (!ok) failedFiles.push(file.name)
  }

  uploading.value = false
  uploadStore.setUploading(false)
  uploadProgress.value = 0

  if (failedFiles.length === 0) {
    toast.show(`${files.length > 1 ? files.length + ' 个文件' : files[0].name} 上传成功，正在建立索引...`, 'success', 4000)
  } else if (failedFiles.length < files.length) {
    toast.show(`${files.length - failedFiles.length} 个上传成功，${failedFiles.length} 个失败`, 'info', 4000)
  }
}

async function uploadSingleFile(file: File): Promise<boolean> {
  try {
    const formData = new FormData()
    formData.append('file', file)

    const xhr = new XMLHttpRequest()
    xhr.timeout = 120000
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const fileProgress = Math.round((e.loaded / e.total) * 100)
        uploadProgress.value = Math.round(((uploadCurrent.value - 1) / uploadTotal.value) * 100 + fileProgress / uploadTotal.value)
      }
    })

    const promise = new Promise((resolve, reject) => {
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(xhr.response)
        } else {
          let message = `上传失败 (${xhr.status || '网络错误'})`
          try {
            const resp = JSON.parse(xhr.responseText)
            message = resp.detail || resp.error?.message || message
          } catch {
            const text = xhr.responseText?.trim()
            if (text) message = text.slice(0, 200)
          }
          reject(new Error(message))
        }
      }
      xhr.onerror = () => reject(new Error('上传失败：无法连接到后端或代理'))
      xhr.ontimeout = () => reject(new Error('上传超时：请检查后端是否仍在处理或代理超时配置'))
    })

    xhr.open('POST', apiUrl('api/documents/upload'))
    xhr.send(formData)

    await promise
    await loadDocuments()
    return true
  } catch (e: any) {
    console.error('Upload error:', e)
    toast.show(e.message || `上传 ${file.name} 失败`, 'error')
    return false
  }
}

async function deleteDocument(docId: string) {
  if (!confirm('确定删除此文档？此操作不可撤销。')) return

  try {
    const resp = await fetch(apiUrl(`api/documents/${docId}`), { method: 'DELETE' })
    if (resp.ok) {
      toast.show('文档删除成功', 'success')
    } else {
      toast.show('删除失败', 'error')
    }
    await loadDocuments()
  } catch (e) {
    console.error('Delete error:', e)
    toast.show('删除失败', 'error')
  }
}

function formatSize(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i]
}

function formatDate(date: number | string): string {
  if (!date) return ''
  const d = typeof date === 'number' ? new Date(date * 1000) : new Date(date)
  return d.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getFileType(filename: string): string {
  const ext = filename?.split('.').pop()?.toLowerCase() || ''
  if (ext === 'md') return 'markdown'
  if (ext === 'pdf') return 'pdf'
  return 'text'
}

function getStatusText(status: string): string {
  const statusMap: Record<string, string> = {
    processing: '处理中',
    indexed: '已索引',
    failed: '处理失败',
    pending: '处理中',
    processed: '已处理',
    error: '处理失败',
  }
  return statusMap[status] || status || '已上传'
}
</script>

<style scoped>
.documents-view {
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

.header-stats {
  display: flex;
  gap: var(--spacing-lg);
}

.stat-item {
  text-align: center;
  padding: var(--spacing-md) var(--spacing-lg);
  background: white;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.stat-value {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: var(--primary-500);
}

.stat-label {
  font-size: 12px;
  color: var(--neutral-500);
}

/* Upload Area */
.upload-area {
  border: 2px dashed var(--neutral-300);
  border-radius: var(--radius-xl);
  padding: var(--spacing-2xl);
  text-align: center;
  cursor: pointer;
  transition: all var(--transition-normal);
  background: white;
  margin-bottom: var(--spacing-xl);
}

.upload-area:hover,
.upload-area.dragging {
  border-color: var(--primary-400);
  background: var(--primary-50);
}

.upload-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto var(--spacing-md);
  background: var(--primary-100);
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
}

.upload-icon svg {
  width: 32px;
  height: 32px;
  color: var(--primary-500);
}

.upload-content h3 {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 var(--spacing-xs) 0;
}

.upload-content p {
  color: var(--neutral-500);
  margin: 0 0 var(--spacing-md) 0;
}

.upload-formats {
  display: flex;
  gap: var(--spacing-sm);
  justify-content: center;
}

.format-badge {
  padding: var(--spacing-xs) var(--spacing-sm);
  background: var(--neutral-100);
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--neutral-600);
}

/* Upload Progress */
.upload-progress {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-md);
  background: var(--primary-50);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-lg);
}

.progress-bar {
  flex: 1;
  height: 4px;
  background: var(--neutral-200);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary-400), var(--primary-500));
  transition: width var(--transition-fast);
}

.progress-text {
  font-size: 13px;
  color: var(--primary-600);
  font-weight: 500;
}

/* Document Section */
.document-section {
  background: white;
  border-radius: var(--radius-xl);
  padding: var(--spacing-lg);
  box-shadow: var(--shadow-sm);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-lg);
}

.section-header h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.search-box {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--neutral-50);
  border: 1px solid var(--neutral-200);
  border-radius: var(--radius-md);
}

.search-box svg {
  width: 18px;
  height: 18px;
  color: var(--neutral-400);
}

.search-box input {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 14px;
  width: 200px;
}

.search-box input:focus {
  outline: none;
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: var(--spacing-2xl);
}

.empty-icon {
  width: 80px;
  height: 80px;
  margin: 0 auto var(--spacing-md);
  background: var(--neutral-100);
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-icon svg {
  width: 40px;
  height: 40px;
  color: var(--neutral-400);
}

.empty-state h3 {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 var(--spacing-xs) 0;
}

.empty-state p {
  color: var(--neutral-500);
  margin: 0;
}

/* Document Grid */
.document-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--spacing-md);
}

.document-card {
  background: var(--neutral-50);
  border-radius: var(--radius-lg);
  padding: var(--spacing-md);
  border: 1px solid var(--neutral-200);
  transition: all var(--transition-fast);
}

.document-card:hover {
  border-color: var(--primary-200);
  box-shadow: var(--shadow-md);
}

.doc-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-sm);
}

.doc-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
}

.doc-icon.markdown {
  background: var(--primary-100);
  color: var(--primary-600);
}

.doc-icon.pdf {
  background: var(--error-100);
  color: var(--error-500);
}

.doc-icon.text {
  background: var(--neutral-200);
  color: var(--neutral-600);
}

.doc-icon svg {
  width: 20px;
  height: 20px;
}

.doc-actions {
  display: flex;
  gap: var(--spacing-xs);
}

.btn-icon-sm {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neutral-500);
  transition: all var(--transition-fast);
}

.btn-icon-sm:hover {
  background: var(--neutral-200);
  color: var(--neutral-700);
}

.btn-icon-sm.delete:hover {
  background: var(--error-100);
  color: var(--error-500);
}

.btn-icon-sm svg {
  width: 16px;
  height: 16px;
}

.doc-body {
  margin-bottom: var(--spacing-sm);
}

.doc-name {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 var(--spacing-xs) 0;
  word-break: break-word;
}

.doc-meta {
  display: flex;
  gap: var(--spacing-md);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  font-size: 12px;
  color: var(--neutral-500);
}

.meta-item svg {
  width: 12px;
  height: 12px;
}

.doc-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--neutral-200);
}

.status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-weight: 500;
}

.status-badge.processed {
  background: var(--success-100);
  color: var(--success-500);
}

.status-badge.pending {
  background: var(--warning-100);
  color: var(--warning-500);
}

.status-badge.error {
  background: var(--error-100);
  color: var(--error-500);
}

.upload-time {
  font-size: 11px;
  color: var(--neutral-400);
}

/* Responsive */
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: var(--spacing-md);
  }

  .header-stats {
    width: 100%;
  }

  .stat-item {
    flex: 1;
  }

  .document-grid {
    grid-template-columns: 1fr;
  }
}
</style>
