<template>
  <div class="container">
    <div class="page-title">
      <h2>上传项目/仓库</h2>
      <button class="btn btn-light" @click="goBack">返回项目列表</button>
    </div>
    <div class="card">
      <form class="form" @submit.prevent="handleSubmit">
        <!-- 项目名称 -->
        <div :class="{ 'has-error': errors.name }">
          <label>项目名称 <span class="required">*</span></label>
          <input 
            v-model="name" 
            type="text" 
            placeholder="请输入项目名称" 
            :class="{ 'input-error': errors.name }"
            @input="clearError('name')"
          />
          <p v-if="errors.name" class="error-msg">请填写项目名称</p>
        </div>

        <!-- 项目描述 -->
        <div>
          <label>项目描述</label>
          <textarea v-model="description" placeholder="请输入项目描述" />
        </div>

        <div class="divider">仓库信息（以下三项必填且仅填一项）</div>

        <!-- 仓库地址 -->
        <div :class="{ 'has-error': errors.repoSource }">
          <label>仓库地址</label>
          <input 
            v-model="repoUrl" 
            type="text" 
            placeholder="例如：https://github.com/org/repo.git" 
            :class="{ 'input-error': errors.repoSource && repoUrl }"
            @input="onRepoUrlInput"
          />
        </div>

        <!-- 上传压缩包 -->
        <div :class="{ 'has-error': errors.repoSource }">
          <label>上传压缩包</label>
          <div class="file-input-wrapper">
            <input 
              type="file" 
              accept=".zip,.tar,.tar.gz" 
              @change="onFileChange" 
              :class="{ 'input-error': errors.repoSource && fileName }"
            />
          </div>
          <small v-if="fileName">已选择：{{ fileName }}</small>
        </div>

        <!-- 上传文件夹 -->
        <div :class="{ 'has-error': errors.repoSource }">
          <label>上传文件夹</label>
          <div class="custom-file-input">
            <input
              type="file"
              webkitdirectory
              directory
              @change="onFolderChange"
              id="folder-input"
              class="hidden-input"
            />
            <label 
              for="folder-input" 
              class="btn btn-secondary"
              :class="{ 'btn-error': errors.repoSource && folderName }"
            >选择文件夹</label>
            <span class="file-name" v-if="folderName">已选择：{{ folderName }}</span>
          </div>
          <p v-if="errors.repoSource" class="error-msg">请选择且仅选择一种仓库提交方式</p>
        </div>

        <div v-if="showInlineError" class="inline-error">
          <span class="inline-icon">⚠️</span>
          <span class="inline-text">{{ inlineErrorMessage }}</span>
        </div>

        <div class="actions">
          <button class="btn" type="submit" :disabled="isSubmitting">{{ isSubmitting ? '提交中...' : '提交' }}</button>
          <button v-if="canRetry && !isSubmitting" class="btn btn-secondary" type="button" @click="handleRetry">重试</button>
          <button v-if="isSubmitting" class="btn btn-light" type="button" @click="handleCancel">取消</button>
        </div>
        <p class="success" v-if="successMessage">{{ successMessage }}</p>
      </form>
    </div>

    <!-- 错误提示弹框 -->
    <Transition name="fade">
      <div v-if="showErrorModal" class="modal-overlay">
        <div class="modal-content">
          <h3 class="modal-title">提交失败</h3>
          <p class="modal-message">{{ errorMessage }}</p>
          <button class="btn btn-primary" @click="closeErrorModal">知道了</button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { createProject } from '../../api/projects'

const router = useRouter()
const name = ref('')
const description = ref('')
const repoUrl = ref('')
const fileName = ref('')
const folderName = ref('')
const selectedFile = ref<File | null>(null)
const selectedFolderFiles = ref<File[]>([])
const successMessage = ref('')
const isSubmitting = ref(false)
const showInlineError = ref(false)
const inlineErrorMessage = ref('')
const canRetry = ref(false)
const abortController = ref<AbortController | null>(null)

// 验证状态
const errors = reactive({
  name: false,
  repoSource: false
})
const showErrorModal = ref(false)
const errorMessage = ref('')

const clearError = (field: 'name' | 'repoSource') => {
  errors[field] = false
}

const onRepoUrlInput = () => {
  clearError('repoSource')
  if (repoUrl.value.trim()) {
    selectedFile.value = null
    fileName.value = ''
    selectedFolderFiles.value = []
    folderName.value = ''
  }
}

const onFileChange = (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files && target.files[0]
  selectedFile.value = file || null
  fileName.value = file ? file.name : ''
  selectedFolderFiles.value = []
  folderName.value = ''
  if (file) {
    repoUrl.value = ''
  }
  clearError('repoSource')
}

const onFolderChange = (e: Event) => {
  const target = e.target as HTMLInputElement
  const files = target.files
  selectedFolderFiles.value = files ? Array.from(files) : []
  folderName.value = files && files.length > 0 ? `${files.length} 个文件` : ''
  selectedFile.value = null
  fileName.value = ''
  if (files && files.length > 0) {
    repoUrl.value = ''
  }
  clearError('repoSource')
}

const validateForm = () => {
  let isValid = true
  
  // 1. 验证项目名称
  if (!name.value.trim()) {
    errors.name = true
    isValid = false
  }

  // 2. 验证仓库信息（三选一）
  const sources = [
    repoUrl.value.trim().length > 0,
    !!selectedFile.value,
    selectedFolderFiles.value.length > 0
  ].filter(Boolean)

  if (sources.length !== 1) {
    errors.repoSource = true
    isValid = false
  }

  return isValid
}

const handleSubmit = async () => {
  // 重置错误
  errors.name = false
  errors.repoSource = false
  showInlineError.value = false
  inlineErrorMessage.value = ''
  canRetry.value = false

  if (!validateForm()) {
    // 设置错误信息并弹框
    const msgs = []
    if (errors.name) msgs.push('请填写项目名称')
    if (errors.repoSource) msgs.push('请选择且仅选择一种仓库提交方式')
    
    errorMessage.value = msgs.join('\n')
    showErrorModal.value = true
    return
  }

  try {
    isSubmitting.value = true
    const formData = new FormData()
    formData.append('name', name.value)
    if (description.value.trim()) formData.append('description', description.value)
    if (repoUrl.value.trim()) {
      formData.append('repoUrl', repoUrl.value.trim())
    } else if (selectedFile.value) {
      formData.append('archive', selectedFile.value)
    } else if (selectedFolderFiles.value.length > 0) {
      selectedFolderFiles.value.forEach((file) => {
        const filePath = (file as any).webkitRelativePath || file.name
        formData.append('folder', file) // Send file
        formData.append('folderPaths', filePath) // Send explicit path
      })
    }
    const controller = new AbortController()
    abortController.value = controller
    await createProject(formData, { signal: controller.signal })
    successMessage.value = '提交成功'
    router.back()
  } catch (err: any) {
    const msg = err?.message || '创建失败'
    inlineErrorMessage.value = msg
    showInlineError.value = true
    canRetry.value = true
  } finally {
    isSubmitting.value = false
    abortController.value = null
  }
}

const closeErrorModal = () => {
  showErrorModal.value = false
}

const handleRetry = () => {
  handleSubmit()
}

const handleCancel = () => {
  if (abortController.value) {
    abortController.value.abort()
  }
  isSubmitting.value = false
  showInlineError.value = true
  inlineErrorMessage.value = '已取消提交'
  canRetry.value = true
}

const goBack = () => {
  if (window.history.state && window.history.state.back) {
    router.back()
  } else {
    router.push('/projects')
  }
}
</script>

<style scoped>
.required {
  color: #ef4444;
  margin-left: 4px;
}

.divider {
  font-size: 14px;
  color: #64748b;
  margin: 16px 0 8px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #e2e8f0;
  font-weight: 500;
}

.input-error {
  border-color: #ef4444 !important;
  background-color: #fef2f2;
}

.btn-error {
  border-color: #ef4444 !important;
  color: #ef4444 !important;
  background-color: #fef2f2 !important;
}

.error-msg {
  color: #ef4444;
  font-size: 12px;
  margin-top: 4px;
}

.actions {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-top: 24px;
}
.inline-error {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
  padding: 10px 12px;
  border-radius: 8px;
  margin-top: 16px;
  font-size: 13px;
}
.inline-icon {
  font-size: 14px;
}
.inline-text {
  line-height: 1.4;
}
.success {
  color: #15803d;
  font-weight: 600;
  margin-top: 12px;
}
small {
  color: #64748b;
}
.hidden-input {
  display: none;
}
.custom-file-input {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}
.custom-file-input label {
  margin: 0 !important;
  min-width: auto !important;
}
.file-name {
  font-size: 13px;
  color: #64748b;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  padding: 24px;
  border-radius: 12px;
  width: 320px;
  text-align: center;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
}

.modal-title {
  margin: 0 0 12px;
  color: #ef4444;
  font-size: 18px;
}

.modal-message {
  white-space: pre-line;
  color: #334155;
  margin-bottom: 20px;
  line-height: 1.5;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
