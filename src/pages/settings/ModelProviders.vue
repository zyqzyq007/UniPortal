<template>
  <div class="mp-container">
    <div class="page-header">
      <div class="title-row">
        <button class="back-btn" @click="goBack" title="返回上一页">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="19" y1="12" x2="5" y2="12"></line>
            <polyline points="12 19 5 12 12 5"></polyline>
          </svg>
        </button>
        <h2>模型 API 资产配置</h2>
      </div>
      <button class="btn-primary" @click="openCreate">+ 添加服务商</button>
    </div>
    <p class="page-desc">管理 LLM / Embedding / Reranker 的 API 端点和密钥，配置后可在知识库检索中自动选择可用模型。</p>

    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <div v-else-if="providers.length === 0" class="empty-state">
      <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2L2 7l10 5 10-5-10-5z"></path>
        <path d="M2 17l10 5 10-5"></path>
        <path d="M2 12l10 5 10-5"></path>
      </svg>
      <p>暂无配置的服务商</p>
      <span class="hint">添加 DashScope / OpenAI / vLLM / Ollama 等服务商</span>
      <button class="btn-link" @click="openCreate">添加第一个服务商</button>
    </div>

    <div v-else class="provider-list">
      <div v-for="p in providers" :key="p.id" class="provider-card">
        <div class="provider-header">
          <div class="provider-title">
            <span class="provider-name">{{ p.name }}</span>
            <span class="type-tag">{{ p.provider_type }}</span>
            <span v-if="p.is_active" class="status-tag active">启用</span>
            <span v-else class="status-tag inactive">已禁用</span>
            <span v-if="p.last_test_ok === true" class="status-tag ok">● 已连通</span>
            <span v-else-if="p.last_test_ok === false" class="status-tag fail">● 连接失败</span>
          </div>
          <div class="provider-actions">
            <button class="btn-icon" @click="handleTest(p)" :disabled="testing === p.id" title="测试连接">
              <span v-if="testing === p.id" class="mini-spinner"></span>
              <span v-else>测试</span>
            </button>
            <button class="btn-icon" @click="openEdit(p)" title="编辑">编辑</button>
            <button class="btn-icon danger" @click="confirmDelete(p)" title="删除">删除</button>
          </div>
        </div>
        <div class="provider-body">
          <div class="meta-row">
            <span class="meta-label">Base URL:</span>
            <code>{{ p.base_url }}</code>
          </div>
          <div class="meta-row">
            <span class="meta-label">API Key:</span>
            <code>{{ p.api_key }}</code>
          </div>
          <div v-if="parseModels(p.available_models)" class="models-section">
            <div class="meta-label">可用模型:</div>
            <div class="model-groups">
              <template v-for="cap in ['llm', 'embedding', 'reranker']" :key="cap">
                <div v-if="parseModels(p.available_models)?.[cap as 'llm'|'embedding'|'reranker']?.length" class="model-group">
                  <span class="cap-tag">{{ capLabel(cap) }}</span>
                  <span class="model-list">{{ parseModels(p.available_models)?.[cap as 'llm'|'embedding'|'reranker']?.join(' · ') }}</span>
                </div>
              </template>
            </div>
          </div>
          <div v-if="p.last_tested_at" class="meta-row muted">
            最近测试: {{ formatDate(p.last_tested_at) }}
          </div>
        </div>
      </div>
    </div>

    <!-- Create / Edit Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="cancelForm">
      <div class="modal-content wide">
        <h3>{{ editing ? '编辑服务商' : '添加服务商' }}</h3>
        <div class="form-group">
          <label>显示名称 <span class="required">*</span></label>
          <input v-model="form.name" placeholder="例如: DashScope 生产环境" />
        </div>
        <div class="form-group">
          <label>服务商类型 <span class="required">*</span></label>
          <select v-model="form.provider_type" @change="onTypeChange">
            <option value="dashscope">DashScope (阿里云百炼)</option>
            <option value="openai">OpenAI</option>
            <option value="vllm">vLLM (本地推理)</option>
            <option value="ollama">Ollama (本地)</option>
            <option value="custom">自定义 OpenAI 兼容</option>
          </select>
        </div>
        <div class="form-group">
          <label>Base URL <span class="required">*</span></label>
          <input v-model="form.base_url" placeholder="https://..." />
          <span class="hint">OpenAI 兼容的 API 根路径 (会自动拼接 /models 探测可用模型)</span>
        </div>
        <div class="form-group">
          <label>API Key</label>
          <input v-model="form.api_key" type="password" :placeholder="editing ? '留空则不修改' : 'sk-...'" />
          <span class="hint">Ollama 等本地服务通常无需 Key</span>
        </div>
        <div class="form-group">
          <label>能力</label>
          <div class="checkbox-row">
            <label class="checkbox"><input type="checkbox" value="embedding" v-model="form.capabilities" /> Embedding</label>
            <label class="checkbox"><input type="checkbox" value="llm" v-model="form.capabilities" /> LLM</label>
            <label class="checkbox"><input type="checkbox" value="reranker" v-model="form.capabilities" /> Reranker</label>
          </div>
        </div>
        <div v-if="formError" class="error-msg">{{ formError }}</div>
        <div class="modal-actions">
          <button class="btn-cancel" @click="cancelForm" :disabled="saving">取消</button>
          <button class="btn-primary" @click="saveForm" :disabled="saving">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation -->
    <div v-if="showDeleteModal" class="modal-overlay">
      <div class="modal-content">
        <h3>确认删除</h3>
        <p>确定要删除服务商 "{{ toDelete?.name }}" 吗？此操作不可撤销。</p>
        <div class="modal-actions">
          <button class="btn-cancel" @click="showDeleteModal = false">取消</button>
          <button class="btn-danger-solid" @click="executeDelete" :disabled="deleting">
            {{ deleting ? '删除中...' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  listProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  testProvider,
} from '../../api/modelProvider'
import type { ModelProvider, ProviderInput } from '../../api/modelProvider'

const router = useRouter()

function goBack() {
  // Prefer history back; fall back to project list if no history
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/projects')
  }
}

const providers = ref<ModelProvider[]>([])
const loading = ref(true)
const showModal = ref(false)
const editing = ref<ModelProvider | null>(null)
const saving = ref(false)
const formError = ref('')
const showDeleteModal = ref(false)
const toDelete = ref<ModelProvider | null>(null)
const deleting = ref(false)
const testing = ref<string | null>(null)

const form = ref<ProviderInput>({
  name: '',
  provider_type: 'dashscope',
  base_url: '',
  api_key: '',
  capabilities: ['embedding', 'llm'],
})

const TYPE_DEFAULTS: Record<string, { base_url: string; capabilities: string[] }> = {
  dashscope: { base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', capabilities: ['embedding', 'llm'] },
  openai: { base_url: 'https://api.openai.com/v1', capabilities: ['embedding', 'llm'] },
  vllm: { base_url: 'http://localhost:8000/v1', capabilities: ['embedding', 'llm'] },
  ollama: { base_url: 'http://localhost:11434/v1', capabilities: ['embedding', 'llm'] },
  custom: { base_url: '', capabilities: ['embedding', 'llm'] },
}

function onTypeChange() {
  const def = TYPE_DEFAULTS[form.value.provider_type]
  if (def && !editing.value) {
    form.value.base_url = def.base_url
    form.value.capabilities = [...def.capabilities]
  }
}

onMounted(fetch)

async function fetch() {
  loading.value = true
  try {
    const res = await listProviders()
    providers.value = res.data
  } catch { /* interceptor */ } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = { ...TYPE_DEFAULTS.dashscope, api_key: '' } as ProviderInput
  formError.value = ''
  showModal.value = true
}

function openEdit(p: ModelProvider) {
  editing.value = p
  let caps: string[] = []
  try { caps = JSON.parse(p.capabilities || '[]') } catch { /* ignore */ }
  form.value = {
    name: p.name,
    provider_type: p.provider_type,
    base_url: p.base_url,
    api_key: '',  // leave empty — backend keeps existing if masked
    capabilities: caps,
    is_active: p.is_active,
  }
  formError.value = ''
  showModal.value = true
}

function cancelForm() {
  if (saving.value) return
  showModal.value = false
}

async function saveForm() {
  if (!form.value.name.trim() || !form.value.base_url.trim()) {
    formError.value = '名称和 Base URL 不能为空'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    if (editing.value) {
      const update: Partial<ProviderInput> = { ...form.value }
      if (!update.api_key) delete update.api_key
      await updateProvider(editing.value.id, update)
    } else {
      if (!form.value.api_key) form.value.api_key = ''
      await createProvider(form.value)
    }
    showModal.value = false
    await fetch()
  } catch (e: any) {
    formError.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

function confirmDelete(p: ModelProvider) {
  toDelete.value = p
  showDeleteModal.value = true
}

async function executeDelete() {
  if (!toDelete.value) return
  deleting.value = true
  try {
    await deleteProvider(toDelete.value.id)
    showDeleteModal.value = false
    toDelete.value = null
    await fetch()
  } catch { /* interceptor */ } finally {
    deleting.value = false
  }
}

async function handleTest(p: ModelProvider) {
  testing.value = p.id
  try {
    const res = await testProvider(p.id)
    if (res.data.ok) {
      alert(`连接成功！发现 ${res.data.models.llm.length} 个 LLM、${res.data.models.embedding.length} 个 Embedding、${res.data.models.reranker.length} 个 Reranker 模型`)
    } else {
      alert(`连接失败: ${res.data.error || '未知错误'}`)
    }
    await fetch()
  } catch (e: any) {
    alert(`测试失败: ${e?.message || '网络错误'}`)
  } finally {
    testing.value = null
  }
}

type ModelMap = { embedding: string[]; llm: string[]; reranker: string[] }

function parseModels(json: string): ModelMap | null {
  try {
    const parsed = JSON.parse(json || '{}')
    if (!parsed || typeof parsed !== 'object') return null
    const result: ModelMap = { embedding: [], llm: [], reranker: [] }
    for (const k of ['embedding', 'llm', 'reranker'] as const) {
      if (Array.isArray(parsed[k])) result[k] = parsed[k]
    }
    // Return null if all empty
    if (!result.embedding.length && !result.llm.length && !result.reranker.length) return null
    return result
  } catch { return null }
}

function capLabel(cap: string): string {
  return { llm: 'LLM', embedding: 'Embedding', reranker: 'Reranker' }[cap] || cap
}

function formatDate(s: string): string {
  return new Date(s).toLocaleString('zh-CN')
}
</script>

<style scoped>
.mp-container { padding: 32px; max-width: 1100px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.title-row { display: flex; align-items: center; gap: 12px; }
.back-btn {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #475569;
  transition: all 0.2s;
}
.back-btn:hover {
  background: #e2e8f0;
  color: #1e40af;
  border-color: #cbd5e1;
}
.page-header h2 { font-size: 22px; font-weight: 600; color: #1e293b; }
.page-desc { color: #64748b; font-size: 14px; margin-bottom: 24px; }

.loading-state { text-align: center; padding: 60px 0; color: #64748b; }
.spinner { width: 32px; height: 32px; border: 3px solid #e2e8f0; border-top-color: #1e40af; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 12px; }
@keyframes spin { to { transform: rotate(360deg); } }

.empty-state { text-align: center; padding: 60px 0; color: #64748b; }
.empty-state p { font-size: 16px; margin: 16px 0 8px; }
.empty-state .hint { display: block; font-size: 13px; color: #94a3b8; margin-bottom: 16px; }
.btn-link { background: none; border: none; color: #1e40af; cursor: pointer; font-size: 14px; font-weight: 500; }
.btn-link:hover { text-decoration: underline; }

.provider-list { display: flex; flex-direction: column; gap: 12px; }
.provider-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px 20px; }
.provider-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.provider-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.provider-name { font-size: 16px; font-weight: 600; color: #1e293b; }
.type-tag { background: #e0e7ff; color: #4338ca; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
.status-tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 500; }
.status-tag.active { background: #dcfce7; color: #16a34a; }
.status-tag.inactive { background: #f1f5f9; color: #64748b; }
.status-tag.ok { background: #dcfce7; color: #16a34a; }
.status-tag.fail { background: #fee2e2; color: #dc2626; }

.provider-actions { display: flex; gap: 6px; }
.btn-icon { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 4px; padding: 4px 12px; cursor: pointer; color: #475569; font-size: 13px; display: inline-flex; align-items: center; gap: 4px; }
.btn-icon:hover { background: #e2e8f0; }
.btn-icon.danger:hover { background: #fee2e2; color: #dc2626; border-color: #fecaca; }
.btn-icon:disabled { opacity: 0.6; cursor: not-allowed; }

.mini-spinner { width: 10px; height: 10px; border: 2px solid #cbd5e1; border-top-color: #1e40af; border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }

.provider-body { display: flex; flex-direction: column; gap: 6px; }
.meta-row { font-size: 13px; color: #475569; display: flex; gap: 8px; align-items: baseline; }
.meta-row.muted { color: #94a3b8; font-size: 12px; margin-top: 4px; }
.meta-label { color: #64748b; min-width: 70px; }
.meta-row code, .provider-body code { background: #f1f5f9; padding: 2px 6px; border-radius: 3px; font-size: 12px; color: #334155; word-break: break-all; }

.models-section { margin-top: 8px; padding-top: 8px; border-top: 1px dashed #e2e8f0; }
.model-groups { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.model-group { display: flex; gap: 8px; align-items: baseline; font-size: 12px; }
.cap-tag { background: #fef3c7; color: #92400e; padding: 1px 6px; border-radius: 3px; font-weight: 600; min-width: 70px; text-align: center; }
.model-list { color: #475569; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal-content { background: white; border-radius: 12px; padding: 24px; width: 440px; box-shadow: 0 4px 24px rgba(0,0,0,0.12); }
.modal-content.wide { width: 540px; }
.modal-content h3 { font-size: 18px; font-weight: 600; color: #1e293b; margin-bottom: 16px; }
.modal-content p { font-size: 14px; color: #475569; margin-bottom: 20px; }

.form-group { margin-bottom: 14px; }
.form-group label { display: block; font-size: 13px; color: #334155; margin-bottom: 4px; font-weight: 500; }
.form-group input, .form-group select { width: 100%; padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 14px; }
.form-group .hint { display: block; font-size: 11px; color: #94a3b8; margin-top: 4px; }
.required { color: #dc2626; }
.checkbox-row { display: flex; gap: 16px; }
.checkbox { display: inline-flex; align-items: center; gap: 4px; font-size: 14px; cursor: pointer; }
.checkbox input { accent-color: #1e40af; }

.error-msg { background: #fee2e2; color: #dc2626; padding: 8px 12px; border-radius: 4px; font-size: 13px; margin-bottom: 12px; }

.modal-actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 16px; }
.btn-primary { background: #1e40af; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-size: 14px; cursor: pointer; }
.btn-primary:hover { background: #1e3a8a; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-cancel { background: #f1f5f9; color: #475569; border: 1px solid #e2e8f0; padding: 8px 16px; border-radius: 6px; font-size: 14px; cursor: pointer; }
.btn-cancel:hover { background: #e2e8f0; }
.btn-danger-solid { background: #dc2626; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-size: 14px; cursor: pointer; }
.btn-danger-solid:hover { background: #b91c1c; }
</style>
