<template>
  <div class="kb-container">
    <div class="page-header">
      <h2>知识库</h2>
      <div class="header-actions">
        <button v-if="!multiSelectMode" class="btn-secondary" @click="enterMultiSelect">多选</button>
        <template v-else>
          <button class="btn-secondary" @click="selectAllDocs">{{ isAllSelected ? '取消全选' : '全选' }}</button>
          <button v-if="selectedDocs.length > 0" class="btn-danger-solid btn-sm" @click="batchDelete">
            删除 ({{ selectedDocs.length }})
          </button>
          <button v-if="selectedDocs.length > 0" class="btn-secondary btn-sm" @click="batchDownload">
            下载 ({{ selectedDocs.length }})
          </button>
          <button class="btn-cancel btn-sm" @click="exitMultiSelect">退出多选</button>
        </template>
        <button class="btn-secondary" @click="fetchDocuments" title="刷新文档列表">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 1 1-3-6.7L21 8"></path>
            <path d="M21 3v5h-5"></path>
          </svg>
          <span>刷新</span>
        </button>
        <button class="btn-primary" @click="openUpload">上传文档</button>
      </div>
    </div>

    <p class="page-desc">
      管理需求文档资产，上传后自动索引，支持全文混合检索。
      <span v-if="processingCount > 0" class="processing-hint">
        · {{ processingCount }} 个文档正在索引中（大文件可能需要数分钟）
      </span>
    </p>

    <!-- Search -->
    <div class="search-bar">
      <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
      <input
        v-model="searchQuery"
        @keyup.enter="doSearch"
        placeholder="输入需求关键词检索..."
        class="search-input"
        :disabled="isSearching"
      />
      <button class="btn-icon-only" @click="showConfig = !showConfig" title="检索配置">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"></circle>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
        </svg>
      </button>
      <button class="btn-primary btn-sm" @click="doSearch" :disabled="!searchQuery.trim() || isSearching">
        {{ isSearching ? `检索中 ${elapsed}s` : '检索' }}
      </button>
    </div>

    <!-- Config Drawer -->
    <div v-if="showConfig" class="config-panel">
      <div class="config-row">
        <label>返回结果数 (Top K)</label>
        <input
          type="number"
          v-model.number="config.topK"
          min="1"
          max="50"
          step="1"
          @blur="validateTopK"
        />
      </div>
      <div class="config-row">
        <label>置信度阈值 <span class="muted">(默认 0.3)</span></label>
        <input
          type="number"
          v-model.number="config.threshold"
          min="0"
          max="1"
          step="0.05"
          @blur="validateThreshold"
        />
      </div>
      <div class="config-row">
        <label>检索模式</label>
        <select v-model="config.mode">
          <option value="hybrid">混合 (推荐)</option>
          <option value="dense">语义检索</option>
          <option value="sparse">关键词 (BM25)</option>
        </select>
      </div>
      <div class="config-row config-row-full">
        <label>目标文档 <span class="muted">(默认全部)</span></label>
        <div class="doc-picker">
          <label class="doc-chip" v-for="doc in indexedDocs" :key="doc.id">
            <input
              type="checkbox"
              :value="doc.filename"
              v-model="config.targetDocs"
              @change="onTargetDocsChange"
            />
            <span>{{ doc.filename }}</span>
          </label>
          <span v-if="indexedDocs.length === 0" class="muted">暂无已索引文档</span>
        </div>
      </div>
      <div class="config-hint">
        已索引 {{ indexedDocs.length }} / {{ documents.length }} 篇 · 选中 {{ config.targetDocs.length }} 篇检索
      </div>
      <div class="config-row config-row-full">
        <label>模型选择 <span class="muted">(来自 <RouterLink to="/settings/models" class="link">模型配置</RouterLink>)</span></label>
        <div class="model-grid">
          <div class="model-select">
            <span class="model-label">Embedding</span>
            <select v-model="config.embeddingModel" :disabled="availableModels.embedding.length === 0">
              <option value="">默认</option>
              <option v-for="m in availableModels.embedding" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
          <div class="model-select">
            <span class="model-label">Reranker</span>
            <select v-model="config.rerankerModel" :disabled="availableModels.reranker.length === 0">
              <option value="">禁用</option>
              <option v-for="m in availableModels.reranker" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
        </div>
        <div class="model-actions">
          <button class="btn-secondary btn-sm" @click="saveModelSelection" :disabled="savingModel">
            {{ savingModel ? '保存中...' : '保存到项目' }}
          </button>
          <button class="btn-primary btn-sm" @click="confirmApply" :disabled="!projectModelConfig.embedding_model && !projectModelConfig.reranker_model">
            应用并重建索引
          </button>
          <span v-if="projectModelConfig.embedding_model || projectModelConfig.reranker_model" class="muted saved-hint">
            已保存: {{ [projectModelConfig.embedding_model, projectModelConfig.reranker_model].filter(Boolean).join(' / ') }}
          </span>
        </div>
        <span v-if="availableModels.embedding.length === 0" class="muted hint">
          尚未配置任何模型服务商，<RouterLink to="/settings/models" class="link">去配置</RouterLink>
        </span>
      </div>
    </div>


    <!-- Search Status -->
    <div v-if="isSearching" class="search-status searching">
      <span class="status-dot"></span>
      正在检索 "{{ lastQuery }}"... <span class="elapsed">{{ elapsed }}s</span>
    </div>
    <div v-else-if="searched && searchResults.length > 0" class="search-status success">
      <span class="status-dot success-dot"></span>
      共检索到符合条件的 <strong>{{ matchedCount }}</strong> 条结果，展示前 <strong>{{ returnedCount }}</strong> 条 · 耗时 {{ (searchTime / 1000).toFixed(2) }}s
      <button class="btn-clear" @click="clearResults">清空</button>
    </div>
    <div v-else-if="searched && searchResults.length === 0" class="search-status empty">
      <span class="status-dot empty-dot"></span>
      未找到符合条件的结果（阈值 {{ config.threshold }}）· 耗时 {{ (searchTime / 1000).toFixed(2) }}s
      <button class="btn-clear" @click="clearResults">清空</button>
    </div>

    <!-- Search Results -->
    <div v-if="searchResults.length > 0" class="search-results">
      <div class="result-card" v-for="(r, i) in searchResults" :key="i">
        <div class="result-header">
          <span class="result-score" :class="{ high: bestScore(r) > 0.8, mid: bestScore(r) > 0.5 && bestScore(r) <= 0.8 }">
            {{ (bestScore(r) * 100).toFixed(1) }}%
          </span>
          <span class="result-source">{{ r.source || r.metadata?.filename || '未知来源' }}</span>
          <span v-if="r.rerank_applied" class="rerank-badge" title="经重排序">RERANK</span>
        </div>
        <p class="result-content">{{ r.content }}</p>
      </div>
    </div>

    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <div v-else-if="documents.length === 0" class="empty-state">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
        <polyline points="13 2 13 9 20 9"></polyline>
      </svg>
      <p>暂无需求文档</p>
      <span class="hint">支持 PDF、Markdown、TXT、DOCX、PPTX、HTML 格式</span>
      <button class="btn-link" @click="openUpload">上传第一篇文档</button>
    </div>

    <div v-else class="doc-table-wrapper">
      <table class="doc-table">
        <thead>
          <tr>
            <th v-if="multiSelectMode" class="check-col"></th>
            <th>文件名</th>
            <th>大小</th>
            <th>状态</th>
            <th>上传时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="doc in documents" :key="doc.id" :class="{ 'row-selected': selectedDocs.includes(doc.id) }">
            <td v-if="multiSelectMode" class="check-col">
              <input type="checkbox" :value="doc.id" v-model="selectedDocs" />
            </td>
            <td class="filename-cell">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="file-icon">
                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                <polyline points="13 2 13 9 20 9"></polyline>
              </svg>
              <span>{{ doc.filename }}</span>
            </td>
            <td>{{ formatSize(doc.file_size) }}</td>
            <td class="status-cell">
              <span class="status-badge" :class="doc.status">
                <span v-if="doc.status === 'processing'" class="status-spinner"></span>
                {{ statusLabel(doc) }}
              </span>
            </td>
            <td>{{ formatDate(doc.created_at) }}</td>
            <td>
              <button class="btn-icon" @click="openPreview(doc)" :title="previewing === doc.id ? '加载中...' : '预览文档'" :disabled="previewing === doc.id">
                <span v-if="previewing === doc.id" class="mini-spinner"></span>
                <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
              </button>
              <button class="btn-icon" @click="reindexDoc(doc)" :title="reindexing === doc.id ? '重建中...' : '重建索引（删除旧索引并重新生成）'" :disabled="reindexing === doc.id">
                <span v-if="reindexing === doc.id" class="mini-spinner"></span>
                <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path>
                  <path d="M21 3v5h-5"></path>
                  <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path>
                  <path d="M8 16H3v5"></path>
                </svg>
              </button>
              <button class="btn-icon danger" @click="confirmDelete(doc)" title="删除文档">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"></polyline>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                </svg>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Upload Modal -->
    <div v-if="showUploadModal" class="modal-overlay" @click.self="cancelUpload">
      <div class="modal-content upload-modal">
        <h3>上传文档</h3>

        <!-- File selection buttons -->
        <div v-if="!isUploading && uploadResults.length === 0" class="upload-source-buttons">
          <button class="source-btn" @click="triggerFileInput('file')">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
              <polyline points="13 2 13 9 20 9"></polyline>
            </svg>
            <span>选择文件</span>
          </button>
          <button class="source-btn" @click="triggerFileInput('folder')">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            </svg>
            <span>选择文件夹</span>
          </button>
        </div>

        <!-- Selected files list -->
        <div v-if="selectedFiles.length > 0 && uploadResults.length === 0" class="file-list-section">
          <div class="file-list-header">
            <span>已选择 {{ selectedFiles.length }} 个文件</span>
            <button class="btn-link btn-sm" @click="clearSelection">清空</button>
          </div>
          <div class="file-list">
            <div v-for="(f, i) in selectedFiles" :key="i" class="file-list-item" :class="fileSupportClass(f)">
              <span class="file-status-icon">{{ fileSupportIcon(f) }}</span>
              <span class="file-list-name">{{ f.name }}</span>
              <span class="file-list-size">{{ formatSize(f.size) }}</span>
              <span v-if="!isSupportedFile(f)" class="file-reason">{{ supportReason(f) }}</span>
            </div>
          </div>
          <div class="upload-summary-bar">
            <span class="ok-count">{{ supportedCount }} 个可索引</span>
            <span v-if="unsupportedCount > 0" class="bad-count">{{ unsupportedCount }} 个不支持</span>
          </div>
        </div>

        <!-- Upload progress -->
        <div v-if="isUploading" class="upload-progress-section">
          <div class="progress-bar-container">
            <div class="progress-bar" :style="{ width: uploadProgress + '%' }"></div>
            <span class="progress-text">{{ uploadProgress }}% ({{ uploadedCount }}/{{ supportedCount }})</span>
          </div>
        </div>

        <!-- Upload results -->
        <div v-if="uploadResults.length > 0" class="results-section">
          <div class="file-list">
            <div v-for="(r, i) in uploadResults" :key="i" class="file-list-item" :class="r.status">
              <span class="file-status-icon">{{ r.status === 'ok' ? '✓' : '✕' }}</span>
              <span class="file-list-name">{{ r.filename }}</span>
              <span class="file-reason">{{ r.message }}</span>
            </div>
          </div>
          <div class="upload-summary-bar">
            <span class="ok-count">{{ uploadResults.filter(r => r.status === 'ok').length }} 个成功</span>
            <span v-if="uploadResults.filter(r => r.status !== 'ok').length" class="bad-count">
              {{ uploadResults.filter(r => r.status !== 'ok').length }} 个失败
            </span>
          </div>
        </div>

        <input ref="fileInputFile" type="file" accept=".pdf,.md,.txt,.docx,.pptx,.html,.htm" multiple style="display:none" @change="handleFileChange" />
        <input ref="fileInputFolder" type="file" webkitdirectory directory multiple style="display:none" @change="handleFileChange" />

        <div v-if="uploadError" class="error-msg">{{ uploadError }}</div>

        <div class="modal-actions">
          <button v-if="uploadResults.length > 0" class="btn-primary" @click="closeUploadModal">完成</button>
          <template v-else>
            <button class="btn-cancel" @click="cancelUpload" :disabled="isUploading">取消</button>
            <button class="btn-primary" @click="handleUpload" :disabled="supportedCount === 0 || isUploading">
              {{ isUploading ? '上传中...' : `上传 ${supportedCount} 个文件` }}
            </button>
          </template>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation -->
    <div v-if="showDeleteModal" class="modal-overlay">
      <div class="modal-content">
        <h3>确认删除</h3>
        <p>确定要删除 "{{ docToDelete?.filename }}" 吗？此操作不可撤销。</p>
        <div class="modal-actions">
          <button class="btn-cancel" @click="cancelDelete">取消</button>
          <button class="btn-danger-solid" @click="executeDelete" :disabled="isDeleting">
            {{ isDeleting ? '删除中...' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Preview Modal -->
    <div v-if="showPreviewModal" class="modal-overlay" @click.self="closePreview">
      <div class="modal-content preview-modal">
        <div class="preview-header">
          <h3>{{ previewData?.filename }}</h3>
          <button class="btn-icon" @click="closePreview" title="关闭">✕</button>
        </div>
        <div class="preview-body">
          <pre v-if="previewData?.type === 'text'">{{ previewData.content }}</pre>
          <div v-else-if="previewData?.type === 'html'" class="html-preview" v-html="previewData.content"></div>
          <div v-else-if="previewData?.type === 'image'" class="image-preview">
            <img :src="previewData.src" :alt="previewData.filename" />
          </div>
          <div v-else-if="previewData?.type === 'pdf' && pdfObjectUrl" class="pdf-embed-container">
            <embed :src="pdfObjectUrl" type="application/pdf" width="100%" height="560px" />
          </div>
          <div v-else-if="previewData?.type === 'pdf' && !pdfObjectUrl" class="binary-preview">
            <div class="mini-spinner"></div>
            <p>正在获取 PDF 数据...</p>
          </div>
          <div v-else-if="previewData?.type === 'binary'" class="binary-preview">
            <p v-if="previewData.ext === 'pdf'">PDF 数据获取失败</p>
            <p v-else>{{ previewData.ext || '该' }} 格式暂不支持在线预览</p>
            <a v-if="previewData.download_url" :href="previewData.download_url + '?mode=inline'" target="_blank" class="btn-primary">下载文件</a>
          </div>
        </div>
      </div>
    </div>

    <!-- Apply Progress Modal -->
    <div v-if="showApplyModal" class="modal-overlay">
      <div class="modal-content apply-modal">
        <h3>应用模型配置</h3>
        <div class="apply-steps">
          <div v-for="s in applySteps" :key="s.step" class="step-row" :class="s.status">
            <span class="step-icon">
              <span v-if="s.status === 'done'">✓</span>
              <span v-else-if="s.status === 'failed' || s.status === 'timeout'">✕</span>
              <span v-else>○</span>
            </span>
            <span class="step-name">{{ stepLabel(s.step) }}</span>
            <span v-if="s.detail" class="step-detail">{{ s.detail }}</span>
          </div>
        </div>
        <div v-if="applyDone" class="apply-summary">
          重建索引: {{ applyResult?.reindexed }}/{{ applyResult?.total }} 成功
          <span v-if="applyResult?.failed" class="failed-count">（{{ applyResult.failed }} 失败）</span>
        </div>
        <div class="modal-actions">
          <button v-if="applyDone" class="btn-primary" @click="closeApplyModal">完成</button>
          <span v-else class="muted">请勿关闭页面，操作进行中...</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { getDocuments, uploadDocument, deleteDocument, retrieval, previewDocument, reindexDocument } from '../../api/knowledge'
import type { KnowledgeDocument, RetrievalResult, PreviewResponse } from '../../api/knowledge'
import request from '../../utils/request'
import { getToken } from '../../utils/auth'
import { listAvailableModels } from '../../api/modelProvider'
import type { AvailableModels } from '../../api/modelProvider'
import { getModelConfig, saveModelConfig, applyModelConfig } from '../../api/modelConfig'
import type { ApplyStep, ApplyResult } from '../../api/modelConfig'

const route = useRoute()
const projectId = route.params.projectId as string

const documents = ref<KnowledgeDocument[]>([])
const loading = ref(true)

// Upload state
const showUploadModal = ref(false)
const isUploading = ref(false)
const uploadProgress = ref(0)
const uploadError = ref('')
const selectedFiles = ref<File[]>([])
const uploadResults = ref<Array<{ filename: string; status: 'ok' | 'fail'; message: string }>>([])
const uploadedCount = ref(0)

const SUPPORTED_EXTS = ['pdf', 'md', 'markdown', 'txt', 'docx', 'pptx', 'html', 'htm']
const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB

const fileInputFile = ref<HTMLInputElement>()
const fileInputFolder = ref<HTMLInputElement>()

const supportedCount = computed(() => selectedFiles.value.filter(isSupportedFile).length)
const unsupportedCount = computed(() => selectedFiles.value.length - supportedCount.value)

function isSupportedFile(f: File): boolean {
  const ext = f.name.split('.').pop()?.toLowerCase() || ''
  return SUPPORTED_EXTS.includes(ext) && f.size <= MAX_FILE_SIZE
}

function supportReason(f: File): string {
  const ext = f.name.split('.').pop()?.toLowerCase() || ''
  if (!SUPPORTED_EXTS.includes(ext)) return `不支持的格式 (.${ext})`
  if (f.size > MAX_FILE_SIZE) return `文件过大 (${(f.size / 1024 / 1024).toFixed(1)}MB > 50MB)`
  return ''
}

function fileSupportClass(f: File): string {
  return isSupportedFile(f) ? 'supported' : 'unsupported'
}

function fileSupportIcon(f: File): string {
  return isSupportedFile(f) ? '✓' : '✕'
}
const isDragging = ref(false)

// Delete state
const showDeleteModal = ref(false)
const docToDelete = ref<KnowledgeDocument | null>(null)
const isDeleting = ref(false)

// Preview state
const showPreviewModal = ref(false)
const previewData = ref<PreviewResponse | null>(null)
const previewing = ref<string | null>(null)
const reindexing = ref<string | null>(null)
const pdfObjectUrl = ref('')

// Multi-select
const multiSelectMode = ref(false)
const selectedDocs = ref<string[]>([])
const isAllSelected = computed(() => documents.value.length > 0 && selectedDocs.value.length === documents.value.length)

function enterMultiSelect() {
  multiSelectMode.value = true
  selectedDocs.value = []
}

function exitMultiSelect() {
  multiSelectMode.value = false
  selectedDocs.value = []
}

function selectAllDocs() {
  if (isAllSelected.value) {
    selectedDocs.value = []
  } else {
    selectedDocs.value = documents.value.map((d) => d.id)
  }
}

async function batchDelete() {
  if (!confirm(`确认删除 ${selectedDocs.value.length} 个文档？此操作不可撤销。`)) return
  for (const docId of [...selectedDocs.value]) {
    try {
      await deleteDocument(projectId, docId)
      selectedDocs.value = selectedDocs.value.filter((id) => id !== docId)
    } catch { /* continue */ }
  }
  await fetchDocuments()
  if (selectedDocs.value.length === 0) exitMultiSelect()
}

function batchDownload() {
  for (const docId of selectedDocs.value) {
    const doc = documents.value.find((d) => d.id === docId)
    if (!doc) continue
    const token = getToken()
    // Trigger download via hidden link
    const a = document.createElement('a')
    a.href = `/api/knowledge/${projectId}/documents/${docId}/download?mode=attachment`
    a.download = doc.filename
    // For auth, we need cookie-based. Top-level navigation sends SameSite=Lax cookies.
    a.target = '_blank'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }
}

async function openPreview(doc: KnowledgeDocument) {
  previewing.value = doc.id
  pdfObjectUrl.value = ''
  try {
    const res = await previewDocument(projectId, doc.id)
    previewData.value = res.data
    showPreviewModal.value = true

    // For PDF: fetch via XHR → Blob → Object URL → <embed>
    if (res.data.type === 'pdf' && res.data.download_url) {
      try {
        const pdfUrl = res.data.download_url + '?mode=inline'
        const token = getToken()
        const blob = await new Promise<Blob>((resolve, reject) => {
          const xhr = new XMLHttpRequest()
          xhr.open('GET', pdfUrl)
          xhr.responseType = 'blob'
          if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
          xhr.onload = () => {
            if (xhr.status === 200) resolve(xhr.response as Blob)
            else reject(new Error(`HTTP ${xhr.status}`))
          }
          xhr.onerror = () => reject(new Error('Network error'))
          xhr.send()
        })
        pdfObjectUrl.value = URL.createObjectURL(blob)
      } catch (e: any) {
        console.error('PDF blob fetch failed:', e)
        if (previewData.value) previewData.value.type = 'binary'
      }
    }
  } catch (e: any) {
    alert(`预览失败: ${e?.message || '文件不可用'}`)
  } finally {
    previewing.value = null
  }
}

function closePreview() {
  showPreviewModal.value = false
  previewData.value = null
  if (pdfObjectUrl.value) {
    URL.revokeObjectURL(pdfObjectUrl.value)
    pdfObjectUrl.value = ''
  }
}

async function reindexDoc(doc: KnowledgeDocument) {
  reindexing.value = doc.id
  try {
    await reindexDocument(projectId, doc.id)
    // Immediately set local status to "processing" so UI reflects the change
    const idx = documents.value.findIndex((d) => d.id === doc.id)
    if (idx >= 0) {
      documents.value[idx] = { ...documents.value[idx], status: 'processing', status_label: '正在处理中...' }
    }
    // Start polling for the final status
    pollDocumentStatus(doc.id)
  } catch (e: any) {
    alert(`重建索引失败: ${e?.message || '未知错误'}`)
  } finally {
    reindexing.value = null
  }
}

// Search state
const searchQuery = ref('')
const isSearching = ref(false)
const searched = ref(false)
const lastQuery = ref('')
const searchTime = ref(0)
const searchResults = ref<RetrievalResult[]>([])
const elapsed = ref(0)
const showConfig = ref(false)
const config = ref({
  topK: 5,
  threshold: 0.3,
  mode: 'hybrid' as 'hybrid' | 'dense' | 'sparse',
  targetDocs: [] as string[],
  embeddingModel: '',
  rerankerModel: '',
})

const availableModels = ref<AvailableModels>({ embedding: [], llm: [], reranker: [] })

// Project-level model config (persisted)
const projectModelConfig = ref<{ embedding_model: string | null; reranker_model: string | null }>({ embedding_model: null, reranker_model: null })
const savingModel = ref(false)
const showApplyModal = ref(false)
const applySteps = ref<ApplyStep[]>([])
const applyResult = ref<ApplyResult | null>(null)
const applyDone = ref(false)

function stepLabel(step: string): string {
  const map: Record<string, string> = {
    resolve_embedding: '解析 Embedding 配置',
    generate_env: '生成环境变量',
    write_env: '写入 RAG 配置文件',
    restart_rag: '重启 RAG 服务',
    reindex: '重建索引',
  }
  return map[step] || step
}

const matchedCount = ref(0)
const returnedCount = ref(0)

const indexedDocs = computed(() => documents.value.filter((d) => d.status === 'indexed'))
const processingCount = computed(() => documents.value.filter((d) => d.status === 'processing').length)

// Initialize targetDocs to all indexed docs (default: select all)
function syncTargetDocsDefault() {
  const indexedNames = indexedDocs.value.map((d) => d.filename)
  // Only auto-select-all if user hasn't picked anything yet
  if (config.value.targetDocs.length === 0) {
    config.value.targetDocs = [...indexedNames]
  }
}

// Prevent user from unchecking all docs
function onTargetDocsChange() {
  if (config.value.targetDocs.length === 0) {
    alert('至少需要选择一个文档进行检索，已默认勾选所有文档')
    config.value.targetDocs = indexedDocs.value.map((d) => d.filename)
  }
}

function validateTopK() {
  const v = config.value.topK
  if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0 || !Number.isInteger(v)) {
    alert('Top K 必须是 1-50 之间的正整数，已重置为 5')
    config.value.topK = 5
    return
  }
  if (v > 50) {
    alert('Top K 最大为 50，已重置为 50')
    config.value.topK = 50
  }
}

function validateThreshold() {
  const v = config.value.threshold
  if (typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 1) {
    alert('置信度阈值必须是 0-1 之间的小数，已重置为 0.3')
    config.value.threshold = 0.3
  }
}

// Track active polling timers for cleanup
const pollTimers = new Set<ReturnType<typeof setInterval>>()
let elapsedTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  fetchDocuments()
  fetchAvailableModels()
  fetchProjectModelConfig()
})

async function fetchAvailableModels() {
  try {
    const res = await listAvailableModels()
    availableModels.value = res.data
  } catch { /* ignore — models optional */ }
}

async function fetchProjectModelConfig() {
  try {
    const res = await getModelConfig(projectId)
    projectModelConfig.value = res.data
    // Sync the selection dropdowns with saved config
    if (res.data.embedding_model) config.value.embeddingModel = res.data.embedding_model
    if (res.data.reranker_model) config.value.rerankerModel = res.data.reranker_model
  } catch { /* ignore */ }
}

async function saveModelSelection() {
  savingModel.value = true
  try {
    const res = await saveModelConfig(projectId, {
      embedding_model: config.value.embeddingModel || null,
      reranker_model: config.value.rerankerModel || null,
    })
    projectModelConfig.value = res.data
    alert('已保存到项目配置')
  } catch (e: any) {
    alert(`保存失败: ${e?.message}`)
  } finally {
    savingModel.value = false
  }
}

function confirmApply() {
  if (!confirm('确认应用模型配置？这将重启 RAG 服务并用新模型重建所有索引（耗时较长）。')) return
  runApply()
}

async function runApply() {
  showApplyModal.value = true
  applyDone.value = false
  applySteps.value = []
  applyResult.value = null
  try {
    const res = await applyModelConfig(projectId)
    applySteps.value = res.data.steps
    applyResult.value = res.data
    applyDone.value = true
  } catch (e: any) {
    applySteps.value.push({ step: 'error', status: 'failed', detail: e?.message || 'Request failed' })
    applyDone.value = true
  }
}

function closeApplyModal() {
  showApplyModal.value = false
}

onUnmounted(() => {
  pollTimers.forEach((t) => clearInterval(t))
  pollTimers.clear()
  if (elapsedTimer) clearInterval(elapsedTimer)
})

// Pick the most accurate score: rerank_score (cross-encoder) > retrieval_score > raw score
// Cap at 1.0 so the percentage display never exceeds 100% (BM25 scores can be > 1.0)
function bestScore(r: RetrievalResult): number {
  let s: number
  if (r.rerank_applied && r.rerank_score != null) s = r.rerank_score
  else s = r.retrieval_score ?? r.score
  return Math.min(Math.max(s, 0), 1)
}

function clearResults() {
  searchResults.value = []
  searched.value = false
  searchQuery.value = ''
}

async function fetchDocuments() {
  loading.value = true
  try {
    const res = await getDocuments(projectId)
    documents.value = res.data.documents
    syncTargetDocsDefault()
  } catch {
    // Error handled by interceptor
  } finally {
    loading.value = false
  }
}

function openUpload() {
  selectedFiles.value = []
  uploadProgress.value = 0
  uploadError.value = ''
  uploadResults.value = []
  uploadedCount.value = 0
  showUploadModal.value = true
}

function cancelUpload() {
  if (isUploading.value) return
  closeUploadModal()
}

function closeUploadModal() {
  showUploadModal.value = false
  selectedFiles.value = []
  uploadResults.value = []
  uploadError.value = ''
  uploadedCount.value = 0
  uploadProgress.value = 0
}

function clearSelection() {
  selectedFiles.value = []
}

function triggerFileInput(mode: 'file' | 'folder') {
  if (mode === 'folder') {
    fileInputFolder.value?.click()
  } else {
    fileInputFile.value?.click()
  }
}

function handleFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.length) {
    selectedFiles.value = Array.from(input.files)
  }
  // Reset input so selecting the same file again triggers change
  input.value = ''
}

function handleDrop(e: DragEvent) {
  isDragging.value = false
  if (e.dataTransfer?.files?.length) {
    selectedFiles.value = Array.from(e.dataTransfer.files)
  }
}

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  isSearching.value = true
  searched.value = true
  lastQuery.value = q
  elapsed.value = 0

  // Start elapsed timer
  const startTime = Date.now()
  elapsedTimer = setInterval(() => {
    elapsed.value = Math.floor((Date.now() - startTime) / 100) / 10
  }, 100)

  try {
    const docs = config.value.targetDocs.length > 0 ? config.value.targetDocs : undefined
    const res = await retrieval(projectId, q, config.value.topK, config.value.mode, docs, config.value.threshold)
    searchResults.value = res.data.results
    searchTime.value = res.data.retrieval_time_ms
    matchedCount.value = res.data.matched_count ?? res.data.results.length
    returnedCount.value = res.data.returned_count ?? res.data.results.length
  } catch {
    searchResults.value = []
  } finally {
    if (elapsedTimer) {
      clearInterval(elapsedTimer)
      elapsedTimer = null
    }
    isSearching.value = false
  }
}

async function handleUpload() {
  const filesToUpload = selectedFiles.value.filter(isSupportedFile)
  if (filesToUpload.length === 0) return

  isUploading.value = true
  uploadProgress.value = 0
  uploadedCount.value = 0
  uploadResults.value = []
  uploadError.value = ''

  for (let i = 0; i < filesToUpload.length; i++) {
    const file = filesToUpload[i]
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await uploadDocument(projectId, formData)
      uploadResults.value.push({
        filename: file.name,
        status: 'ok',
        message: `已上传 (${formatSize(file.size)})`,
      })
      pollDocumentStatus(res.data.id)
    } catch (e: any) {
      const msg = e?.message || '上传失败'
      uploadResults.value.push({
        filename: file.name,
        status: 'fail',
        message: msg.includes('RAG service unavailable') ? 'RAG 服务不可用' : msg,
      })
    }
    uploadedCount.value = i + 1
    uploadProgress.value = Math.round(((i + 1) / filesToUpload.length) * 100)
  }

  // Also record unsupported files in results
  for (const f of selectedFiles.value.filter(x => !isSupportedFile(x))) {
    uploadResults.value.push({ filename: f.name, status: 'fail', message: supportReason(f) })
  }

  isUploading.value = false
  await fetchDocuments()
}

// Poll for document indexing status (processing → indexed/failed)
function pollDocumentStatus(localDocId: string) {
  let attempts = 0
  const maxAttempts = 50  // 50 * 6s = 5 min max (large docs can take 30+ min on CPU)
  const timer = setInterval(async () => {
    attempts++
    try {
      const res = await getDocuments(projectId)
      const doc = res.data.documents.find((d: KnowledgeDocument) => d.id === localDocId)
      if (!doc) {
        stopPoll()
        return
      }
      const idx = documents.value.findIndex((d) => d.id === localDocId)
      if (idx >= 0) documents.value[idx] = doc
      if (doc.status !== 'processing') {
        stopPoll()
      }
    } catch { /* ignore poll errors */ }
    if (attempts >= maxAttempts) stopPoll()
  }, 6000)

  function stopPoll() {
    clearInterval(timer)
    pollTimers.delete(timer)
  }
  pollTimers.add(timer)
}

function confirmDelete(doc: KnowledgeDocument) {
  docToDelete.value = doc
  showDeleteModal.value = true
}

function cancelDelete() {
  showDeleteModal.value = false
  docToDelete.value = null
}

async function executeDelete() {
  if (!docToDelete.value) return
  isDeleting.value = true
  try {
    await deleteDocument(projectId, docToDelete.value.id)
    showDeleteModal.value = false
    docToDelete.value = null
    await fetchDocuments()
  } catch {
    // Error handled by interceptor
  } finally {
    isDeleting.value = false
  }
}

function formatSize(bytes: string | number): string {
  const n = Number(bytes)
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / (1024 * 1024)).toFixed(1) + ' MB'
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function statusLabel(doc: { status?: string; status_label?: string }): string {
  // Always prefer backend's status_label (consistent, context-aware)
  if (doc.status_label) return doc.status_label
  if (!doc.status) return '未知'
  if (doc.status === 'indexed') return '已索引'
  if (doc.status === 'processing') return '处理中'
  return '需处理'
}
</script>

<style scoped>
.kb-container {
  padding: 32px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.page-header h2 {
  font-size: 22px;
  font-weight: 600;
  color: #1e293b;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.processing-hint {
  color: #d97706;
  font-weight: 500;
}

.page-desc {
  color: #64748b;
  font-size: 14px;
  margin-bottom: 16px;
}

/* Search */
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 6px 12px;
  margin-bottom: 24px;
}

.search-icon {
  color: #94a3b8;
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 14px;
  color: #334155;
  background: transparent;
  padding: 8px 0;
}

.search-input::placeholder {
  color: #94a3b8;
}

.btn-sm {
  padding: 6px 14px;
  font-size: 13px;
  flex-shrink: 0;
}

.btn-icon-only {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 8px;
  cursor: pointer;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.2s;
}

.btn-icon-only:hover {
  background: #e2e8f0;
  color: #1e40af;
}

.btn-icon-only.active {
  background: #1e40af;
  color: white;
  border-color: #1e40af;
}

/* Config Drawer */
.config-panel {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: flex-end;
}

.config-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-row label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.config-row input,
.config-row select {
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 13px;
  background: white;
  min-width: 140px;
}

.config-hint {
  font-size: 12px;
  color: #64748b;
  margin-left: auto;
  align-self: center;
}

.model-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  width: 100%;
}

.model-select {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.model-label {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
}

.model-select select {
  padding: 5px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 12px;
  background: white;
  min-width: 0;
}

.model-select select:disabled {
  background: #f1f5f9;
  color: #94a3b8;
  cursor: not-allowed;
}

.link {
  color: #1e40af;
  text-decoration: underline;
}

.model-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.btn-secondary {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
}

.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-secondary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.saved-hint {
  font-size: 12px;
}

/* Apply Modal */
.apply-modal {
  width: 500px;
}

.apply-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 16px 0;
}

.step-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  background: #f8fafc;
  font-size: 14px;
}

.step-row.done {
  background: #f0fdf4;
}

.step-row.failed,
.step-row.timeout {
  background: #fef2f2;
}

.step-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  flex-shrink: 0;
}

.step-row.done .step-icon {
  color: #16a34a;
}

.step-row.failed .step-icon,
.step-row.timeout .step-icon {
  color: #dc2626;
}

.step-name {
  font-weight: 500;
  color: #334155;
}

.step-detail {
  margin-left: auto;
  font-size: 12px;
  color: #64748b;
}

.apply-summary {
  text-align: center;
  padding: 12px;
  background: #f8fafc;
  border-radius: 6px;
  font-size: 14px;
  color: #334155;
}

.failed-count {
  color: #dc2626;
}

.config-row-full {
  flex-basis: 100%;
}

.muted {
  color: #94a3b8;
  font-weight: 400;
}

.doc-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 120px;
  overflow-y: auto;
  padding: 4px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  min-width: 280px;
}

.doc-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 3px 10px;
  font-size: 12px;
  color: #475569;
  cursor: pointer;
  user-select: none;
  transition: all 0.15s;
}

.doc-chip:hover {
  background: #e0e7ff;
  border-color: #c7d2fe;
}

.doc-chip input {
  margin: 0;
  accent-color: #1e40af;
}

.doc-chip:has(input:checked) {
  background: #1e40af;
  color: white;
  border-color: #1e40af;
}

/* Search Status */
.search-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 14px;
}

.search-status.searching {
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fcd34d;
}

.search-status.success {
  background: #dcfce7;
  color: #166534;
  border: 1px solid #86efac;
}

.search-status.empty {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
}

.empty-dot {
  background: #94a3b8;
  animation: none;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d97706;
  animation: pulse 1.5s infinite;
}

.success-dot {
  background: #16a34a;
  animation: none;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.elapsed {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.btn-clear {
  margin-left: auto;
  background: transparent;
  border: 1px solid #86efac;
  color: #166534;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}

.btn-clear:hover {
  background: #bbf7d0;
}

/* Search Results */
.search-results {
  margin-bottom: 24px;
}

.result-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 8px;
  transition: box-shadow 0.2s;
}

.result-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.result-score {
  background: #dcfce7;
  color: #16a34a;
  font-size: 13px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 4px;
  font-variant-numeric: tabular-nums;
}

.result-score.mid {
  background: #fef3c7;
  color: #d97706;
}

.result-score.high {
  background: #dcfce7;
  color: #16a34a;
}

.result-source {
  font-size: 12px;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 4px;
}

.rerank-badge {
  font-size: 10px;
  color: #6366f1;
  background: #e0e7ff;
  padding: 2px 6px;
  border-radius: 3px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.result-content {
  font-size: 14px;
  color: #334155;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-search {
  text-align: center;
  padding: 32px;
  color: #94a3b8;
  font-size: 14px;
  margin-bottom: 24px;
}

.btn-primary {
  background: #1e40af;
  color: white;
  border: none;
  padding: 8px 20px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: #1e3a8a;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Loading */
.loading-state {
  text-align: center;
  padding: 60px 0;
  color: #64748b;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e2e8f0;
  border-top-color: #1e40af;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 12px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Empty */
.empty-state {
  text-align: center;
  padding: 60px 0;
  color: #64748b;
}

.empty-state p {
  font-size: 16px;
  margin: 16px 0 8px;
}

.empty-state .hint {
  display: block;
  font-size: 13px;
  color: #94a3b8;
  margin-bottom: 16px;
}

.btn-link {
  background: none;
  border: none;
  color: #1e40af;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  padding: 4px 8px;
}

.btn-link:hover {
  text-decoration: underline;
}

/* Table */
.doc-table-wrapper {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.doc-table {
  width: 100%;
  border-collapse: collapse;
}

.doc-table th {
  text-align: left;
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.doc-table td {
  padding: 12px 16px;
  font-size: 14px;
  color: #334155;
  border-bottom: 1px solid #f1f5f9;
}

.doc-table tr:last-child td {
  border-bottom: none;
}

.doc-table tr:hover td {
  background: #f8fafc;
}

.filename-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-icon {
  color: #64748b;
  flex-shrink: 0;
}

.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
}

.check-col {
  width: 40px;
  text-align: center;
}

.check-col input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: #1e40af;
  cursor: pointer;
}

tr.row-selected {
  background: #eff6ff !important;
}

tr.row-selected:hover td {
  background: #dbeafe !important;
}

.status-cell {
  max-width: 320px;
}

.status-badge.indexed {
  background: #dcfce7;
  color: #16a34a;
}

.status-badge.processing {
  background: #fef3c7;
  color: #d97706;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.status-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid #fcd34d;
  border-top-color: #d97706;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

.status-badge.failed {
  background: #fee2e2;
  color: #dc2626;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
  white-space: normal;
}

.status-badge.unknown {
  background: #f1f5f9;
  color: #64748b;
}

.btn-icon {
  background: none;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 4px 8px;
  cursor: pointer;
  color: #64748b;
  transition: all 0.2s;
}

.btn-icon.danger:hover {
  border-color: #dc2626;
  color: #dc2626;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-content {
  background: white;
  border-radius: 12px;
  padding: 24px;
  width: 440px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.12);
}

.upload-modal {
  width: 560px;
  max-height: 85vh;
  overflow-y: auto;
}

.upload-source-buttons {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.source-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px;
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  cursor: pointer;
  color: #475569;
  transition: all 0.2s;
}

.source-btn:hover {
  border-color: #1e40af;
  background: #eff6ff;
  color: #1e40af;
}

.source-btn span {
  font-size: 14px;
  font-weight: 500;
}

.file-list-section,
.results-section,
.upload-progress-section {
  margin-bottom: 12px;
}

.file-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
  color: #64748b;
}

.file-list {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.file-list-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 13px;
}

.file-list-item:last-child {
  border-bottom: none;
}

.file-list-item.supported {
  background: #f0fdf4;
}

.file-list-item.unsupported {
  background: #fef2f2;
}

.file-list-item.ok {
  background: #f0fdf4;
}

.file-list-item.fail {
  background: #fef2f2;
}

.file-status-icon {
  width: 16px;
  text-align: center;
  font-weight: 700;
  flex-shrink: 0;
}

.supported .file-status-icon,
.ok .file-status-icon {
  color: #16a34a;
}

.unsupported .file-status-icon,
.fail .file-status-icon {
  color: #dc2626;
}

.file-list-name {
  flex: 1;
  color: #334155;
  word-break: break-all;
}

.file-list-size {
  color: #94a3b8;
  font-size: 12px;
  flex-shrink: 0;
}

.file-reason {
  color: #dc2626;
  font-size: 12px;
  flex-shrink: 0;
}

.upload-summary-bar {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 4px;
  font-size: 13px;
}

.ok-count {
  color: #16a34a;
  font-weight: 500;
}

.bad-count {
  color: #dc2626;
  font-weight: 500;
}

.modal-content h3 {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 16px;
}

.modal-content p {
  font-size: 14px;
  color: #475569;
  margin-bottom: 20px;
}

/* Drop zone */
.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  padding: 40px 24px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  margin-bottom: 16px;
}

.drop-zone:hover,
.drop-zone.dragging {
  border-color: #1e40af;
  background: #f0f4ff;
}

.drop-zone p {
  font-size: 14px;
  color: #475569;
  margin: 12px 0 4px;
}

.drop-zone .file-name {
  color: #1e40af;
  font-weight: 600;
}

.drop-zone .hint {
  display: block;
  font-size: 12px;
  color: #94a3b8;
}

/* Progress bar */
.progress-bar-container {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  margin-bottom: 16px;
  position: relative;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: #1e40af;
  border-radius: 3px;
  transition: width 0.3s;
}

.progress-text {
  position: absolute;
  right: 0;
  top: -18px;
  font-size: 12px;
  color: #64748b;
}

/* Modal actions */
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-cancel {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
}

.btn-cancel:hover {
  background: #e2e8f0;
}

.btn-danger-solid {
  background: #dc2626;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-danger-solid:hover {
  background: #b91c1c;
}

.preview-modal {
  width: 800px;
  max-width: 90vw;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.preview-header h3 {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
  word-break: break-all;
}

.preview-body {
  overflow: auto;
  flex: 1;
}

.preview-body pre {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 16px;
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 60vh;
  overflow-y: auto;
  margin: 0;
}

.pdf-embed-container {
  width: 100%;
  min-height: 560px;
}

.pdf-embed-container embed {
  border: none;
  border-radius: 4px;
}

.binary-preview {
  text-align: center;
  padding: 32px;
  color: #64748b;
}

.html-preview {
  padding: 16px 24px;
  font-size: 14px;
  line-height: 1.8;
  color: #334155;
  max-height: 60vh;
  overflow-y: auto;
}

.html-preview :deep(h1),
.html-preview :deep(h2),
.html-preview :deep(h3) {
  margin: 16px 0 8px;
  color: #1e293b;
}

.html-preview :deep(p) {
  margin: 8px 0;
}

.html-preview :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
}

.html-preview :deep(td),
.html-preview :deep(th) {
  border: 1px solid #e2e8f0;
  padding: 6px 10px;
  font-size: 13px;
}

.image-preview {
  text-align: center;
  padding: 16px;
}

.image-preview img {
  max-width: 100%;
  max-height: 60vh;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.binary-preview p {
  margin-bottom: 16px;
  font-size: 14px;
}

.binary-preview .btn-primary {
  display: inline-block;
  text-decoration: none;
  padding: 8px 20px;
}

.error-msg {
  background: #fee2e2;
  color: #dc2626;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
  margin-bottom: 12px;
}

.btn-danger-solid:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
