<template>
  <div class="items-container">
    <div class="page-header">
        <h2>项目管理</h2>
        <div class="actions">
            <button class="btn-danger" v-if="selectedItems.length > 0" @click="confirmBatchDelete">批量删除</button>
            <button class="btn-primary" @click="openUploadModal">上传软件项目</button>
        </div>
    </div>

    <div class="filters">
        <div class="search-wrapper">
            <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input 
                v-model="searchQuery" 
                @input="handleSearch" 
                placeholder="搜索项目名称..." 
                class="search-input" 
            />
        </div>
    </div>

    <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <p>加载中...</p>
    </div>

    <div v-else-if="items.length === 0" class="empty-state">
        <p>暂无软件项目</p>
        <button class="btn-link" @click="openUploadModal">点击上传</button>
    </div>

    <div v-else class="items-grid">
        <div class="items-card" v-for="item in items" :key="item.item_id" @click="goToDetail(item)">
            <div class="card-header">
                <div class="card-title">
                    <div class="file-icon">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                            <polyline points="13 2 13 9 20 9"></polyline>
                        </svg>
                    </div>
                    <div class="title-text">
                        <h4>{{ item.name }}</h4>
                        <span class="version-tag" v-if="item.version">{{ item.version }}</span>
                    </div>
                </div>
                <div class="card-actions">
                    <button class="btn-icon" @click.stop="handleDownload(item)" title="下载">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                        </svg>
                    </button>
                    <button class="btn-icon danger" @click.stop="confirmDelete(item)" title="删除">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            </div>
            
            <div class="card-body">
                <p class="description">{{ item.description || '暂无描述' }}</p>
                <div class="meta-info">
                    <div class="meta-item">
                        <span class="label">大小:</span>
                        <span class="value">{{ formatSize(item.file_size) }}</span>
                    </div>
                    <div class="meta-item">
                        <span class="label">上传时间:</span>
                        <span class="value">{{ formatDate(item.uploaded_at) }}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Pagination -->
        <div v-if="totalPages > 1" class="pagination">
            <button :disabled="currentPage === 1" @click="changePage(currentPage - 1)">上一页</button>
            <span>{{ currentPage }} / {{ totalPages }}</span>
            <button :disabled="currentPage === totalPages" @click="changePage(currentPage + 1)">下一页</button>
        </div>
    </div>

    <!-- Upload Modal -->
    <div v-if="showUploadModal" class="modal-overlay">
        <div class="modal-content upload-modal">
            <h3>上传软件项目</h3>
            <form @submit.prevent="handleUpload">
                <div class="upload-tabs">
                    <div class="tab" :class="{ active: uploadMode === 'folder' }" @click="uploadMode = 'folder'">
                        上传文件夹
                    </div>
                    <div class="tab" :class="{ active: uploadMode === 'archive' }" @click="uploadMode = 'archive'">
                        上传压缩包
                    </div>
                </div>

                <div class="form-group">
                    <label>项目名称 <span class="required">*</span></label>
                    <input v-model="uploadForm.name" type="text" placeholder="请输入名称" required />
                </div>
                <div class="form-group">
                    <label>版本号</label>
                    <input v-model="uploadForm.version" type="text" placeholder="例如 1.0.0" />
                </div>
                <div class="form-group">
                    <label>项目描述 <span class="char-count">{{ descriptionLength }}/500</span></label>
                    <textarea 
                        v-model="uploadForm.description" 
                        placeholder="请输入项目描述（选填）" 
                        rows="4" 
                        maxlength="500"
                        class="description-input"
                    ></textarea>
                </div>
                
                <div class="form-group" v-if="uploadMode === 'folder'">
                    <label>选择文件夹 <span class="required">*</span></label>
                    <div class="file-input-wrapper">
                        <!-- webkitdirectory attribute enables folder selection -->
                        <input type="file" @change="handleFolderChange" required webkitdirectory directory />
                        <div class="file-custom-label" v-if="uploadFiles.length === 0">点击或拖拽选择文件夹</div>
                        <div class="file-name" v-else>已选择 {{ uploadFiles.length }} 个文件</div>
                    </div>
                </div>

                <div class="form-group" v-if="uploadMode === 'archive'">
                    <label>选择压缩包 (.zip, .rar, .7z) <span class="required">*</span></label>
                    <div class="file-input-wrapper">
                        <input type="file" @change="handleArchiveChange" required accept=".zip,.rar,.7z" />
                        <div class="file-custom-label" v-if="!uploadArchive">点击选择压缩包</div>
                        <div class="file-name" v-else>{{ uploadArchive.name }}</div>
                    </div>
                </div>
                
                <div class="modal-actions">
                    <div v-if="isUploading" class="progress-bar-container">
                        <div class="progress-bar" :style="{ width: uploadProgress + '%' }"></div>
                        <span class="progress-text">{{ uploadProgress }}%</span>
                    </div>
                    <button type="button" class="btn-cancel" @click="closeUploadModal" :disabled="isUploading">取消</button>
                    <button type="submit" class="btn-primary" :disabled="isUploading">
                        {{ isUploading ? (uploadProgress === 100 ? '处理中...' : '上传中...') : '开始上传' }}
                    </button>
                </div>
            </form>
        </div>
    </div>

    <!-- Delete Confirmation -->
    <div v-if="showDeleteModal" class="modal-overlay">
        <div class="modal-content">
            <h3>确认删除</h3>
            <p v-if="itemToDelete">确定要删除 "{{ itemToDelete.name }}" 吗？</p>
            <p v-else>确定要删除选中的 {{ selectedItems.length }} 个项目吗？</p>
            <div class="modal-actions">
                <button class="btn-cancel" @click="cancelDelete">取消</button>
                <button class="btn-danger-solid" @click="executeDelete" :disabled="isDeleting">
                    {{ isDeleting ? '删除中...' : '确认删除' }}
                </button>
            </div>
        </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSoftwareItems, deleteSoftwareItem, uploadSoftwareItem, downloadSoftwareItem } from '../../api/projects'
import type { SoftwareItem } from '../../api/projects'
import { debounce } from 'lodash-es'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const items = ref<SoftwareItem[]>([])
const loading = ref(true)
const searchQuery = ref('')
const currentPage = ref(1)
const totalPages = ref(1)
const PAGE_SIZE = 10
const selectedItems = ref<string[]>([])

// Upload state
const showUploadModal = ref(false)
const isUploading = ref(false)
const uploadProgress = ref(0)
const uploadMode = ref<'folder' | 'archive'>('folder')
const uploadFiles = ref<File[]>([])
const uploadArchive = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const uploadForm = reactive({
    name: '',
    version: '',
    description: ''
})

const descriptionLength = computed(() => uploadForm.description.length)

// Delete state
const showDeleteModal = ref(false)
const itemToDelete = ref<SoftwareItem | null>(null)
const isDeleting = ref(false)

const isAllSelected = computed(() => {
    return items.value.length > 0 && selectedItems.value.length === items.value.length
})

const fetchItems = async () => {
    try {
        loading.value = true
        const res: any = await getSoftwareItems(projectId, {
            search: searchQuery.value,
            page: currentPage.value,
            limit: PAGE_SIZE
        })
        if (res.code === 200) {
            items.value = res.data.items
            totalPages.value = res.data.totalPages
            currentPage.value = res.data.page
            selectedItems.value = [] // Reset selection
        }
    } catch (error) {
        console.error('Failed to fetch items', error)
    } finally {
        loading.value = false
    }
}

const handleSearch = debounce(() => {
    currentPage.value = 1
    fetchItems()
}, 300)

const changePage = (page: number) => {
    currentPage.value = page
    fetchItems()
}

const goToDetail = (item: SoftwareItem) => {
    router.push({
        name: 'SoftwareItemDetail',
        params: { projectId, itemId: item.item_id },
        query: { ...route.query, itemName: item.name }
    })
}

const toggleSelectAll = () => {
    if (isAllSelected.value) {
        selectedItems.value = []
    } else {
        selectedItems.value = items.value.map(item => item.item_id)
    }
}

const formatSize = (bytes: string | number) => {
    const size = Number(bytes)
    if (isNaN(size)) return '-'
    if (size < 1024) return size + ' B'
    if (size < 1024 * 1024) return (size / 1024).toFixed(2) + ' KB'
    if (size < 1024 * 1024 * 1024) return (size / 1024 / 1024).toFixed(2) + ' MB'
    return (size / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}

const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    })
}

const closeUploadModal = () => {
    showUploadModal.value = false
}

// Upload Logic
const openUploadModal = () => {
    uploadForm.name = ''
    uploadForm.version = ''
    uploadForm.description = ''
    uploadMode.value = 'folder'
    uploadFiles.value = []
    uploadArchive.value = null
    uploadProgress.value = 0
    if (fileInput.value) fileInput.value.value = ''
    showUploadModal.value = true
}

const handleFolderChange = (e: Event) => {
    const target = e.target as HTMLInputElement
    if (target.files && target.files.length > 0) {
        uploadFiles.value = Array.from(target.files)
        // Auto-fill name from folder name (first file's path usually starts with folder name)
        if (!uploadForm.name && uploadFiles.value.length > 0) {
            const path = uploadFiles.value[0].webkitRelativePath
            if (path) {
                uploadForm.name = path.split('/')[0]
            }
        }
    }
}

const handleArchiveChange = (e: Event) => {
    const target = e.target as HTMLInputElement
    if (target.files && target.files[0]) {
        uploadArchive.value = target.files[0]
        if (!uploadForm.name) {
            // Remove extension
            const name = uploadArchive.value.name
            uploadForm.name = name.substring(0, name.lastIndexOf('.')) || name
        }
    }
}

const handleUpload = async () => {
    if (!uploadForm.name) return
    if (uploadMode.value === 'folder' && uploadFiles.value.length === 0) return
    if (uploadMode.value === 'archive' && !uploadArchive.value) return
    
    try {
        isUploading.value = true
        uploadProgress.value = 0
        const formData = new FormData()
        formData.append('name', uploadForm.name)
        if (uploadForm.version) formData.append('version', uploadForm.version)
        if (uploadForm.description) formData.append('description', uploadForm.description)
        
        if (uploadMode.value === 'folder') {
            uploadFiles.value.forEach(file => {
                formData.append('files', file)
                formData.append('paths[]', file.webkitRelativePath)
            })
        } else {
            if (uploadArchive.value) {
                formData.append('archive', uploadArchive.value)
            }
        }

        const res: any = await uploadSoftwareItem(projectId, formData, {
            onUploadProgress: (progressEvent) => {
                if (progressEvent.total) {
                    const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
                    uploadProgress.value = percentCompleted
                }
            }
        })
        if (res.code === 201) {
            closeUploadModal()
            fetchItems()
        } else {
            alert(res.message || '上传失败')
        }
    } catch (error) {
        console.error('Upload failed', error)
        alert('上传失败，请重试')
    } finally {
        isUploading.value = false
    }
}

// Download Logic
const handleDownload = (item: SoftwareItem) => {
    const url = downloadSoftwareItem(projectId, item.item_id)
    // Create a temporary link to trigger download with auth token if needed
    // However, download link is usually protected. If we use window.open, we might miss the Auth header.
    // So we should use fetch with blob, or ensure the download endpoint accepts token in query param.
    // For now, let's assume cookie auth or similar, or try direct link.
    // Actually, `downloadSoftwareItem` function in api returns a string URL.
    // But our backend expects Bearer token.
    // We need to fetch the blob.
    
    // Better implementation:
    // Use axios to get blob, then create object URL.
    import('../../utils/request').then(({ default: request }) => {
        request({
            url: `/projects/${projectId}/items/${item.item_id}/download`,
            method: 'get',
            responseType: 'blob'
        }).then((response: any) => { // response is the blob directly if interceptor handles it, or check your request util
             // Check if response is Blob
             const blob = new Blob([response], { type: 'application/octet-stream' });
             const downloadUrl = window.URL.createObjectURL(blob);
             const link = document.createElement('a');
             link.href = downloadUrl;
             link.download = item.name; // or get filename from header
             document.body.appendChild(link);
             link.click();
             document.body.removeChild(link);
             window.URL.revokeObjectURL(downloadUrl);
        }).catch(err => {
            console.error('Download error', err)
            alert('下载失败')
        })
    })
}

// Delete Logic
const confirmDelete = (item: SoftwareItem) => {
    itemToDelete.value = item
    showDeleteModal.value = true
}

const confirmBatchDelete = () => {
    itemToDelete.value = null
    showDeleteModal.value = true
}

const cancelDelete = () => {
    showDeleteModal.value = false
    itemToDelete.value = null
}

const executeDelete = async () => {
    try {
        isDeleting.value = true
        if (itemToDelete.value) {
            await deleteSoftwareItem(projectId, itemToDelete.value.item_id)
        } else {
            // Batch delete
            // Since we don't have batch API yet, we loop.
            await Promise.all(selectedItems.value.map(id => deleteSoftwareItem(projectId, id)))
        }
        showDeleteModal.value = false
        itemToDelete.value = null
        selectedItems.value = []
        fetchItems()
    } catch (error) {
        console.error('Delete failed', error)
        alert('删除失败，部分项目可能未删除')
        fetchItems()
    } finally {
        isDeleting.value = false
    }
}

onMounted(() => {
    if (route.query.search) {
        searchQuery.value = String(route.query.search)
    }
    if (route.query.page) {
        currentPage.value = Number(route.query.page) || 1
    }
    fetchItems()
    if (route.query.action === 'upload') {
        openUploadModal()
    }
})

watch([searchQuery, currentPage], () => {
    router.replace({
        query: {
            ...route.query,
            search: searchQuery.value || undefined,
            page: String(currentPage.value)
        }
    })
})
</script>

<style scoped>
.items-container {
    padding: 24px;
    max-width: 1000px;
    margin: 0 auto;
}

.page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
}

.page-header h2 {
    font-size: 24px;
    font-weight: 600;
    color: #1e293b;
    margin: 0;
}

.actions {
    display: flex;
    gap: 12px;
}

.btn-primary {
    background: #1e40af;
    color: white;
    padding: 8px 16px;
    border-radius: 6px;
    border: none;
    font-weight: 500;
    cursor: pointer;
}

.btn-danger {
    background: #fee2e2;
    color: #ef4444;
    padding: 8px 16px;
    border-radius: 6px;
    border: none;
    font-weight: 500;
    cursor: pointer;
}

.btn-danger-solid {
    background: #ef4444;
    color: white;
    padding: 8px 16px;
    border-radius: 6px;
    border: none;
    cursor: pointer;
}

.filters {
    margin-bottom: 24px;
}

.search-wrapper {
    position: relative;
    max-width: 300px;
}

.search-icon {
    position: absolute;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    color: #94a3b8;
}

.search-input {
    width: 100%;
    padding: 8px 12px 8px 36px;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    font-size: 14px;
    outline: none;
}

.items-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 20px;
}

.items-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 20px;
    transition: all 0.2s;
    display: flex;
    flex-direction: column;
    cursor: pointer;
}

.items-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    border-color: #cbd5e1;
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 16px;
}

.card-title {
    display: flex;
    gap: 12px;
    flex: 1;
    overflow: hidden;
}

.title-text {
    flex: 1;
    overflow: hidden;
}

.title-text h4 {
    margin: 0 0 4px 0;
    font-size: 16px;
    font-weight: 600;
    color: #1e293b;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.version-tag {
    display: inline-block;
    padding: 2px 8px;
    background: #f1f5f9;
    color: #64748b;
    border-radius: 4px;
    font-size: 12px;
}

.card-actions {
    display: flex;
    gap: 4px;
}

.card-body {
    flex: 1;
    display: flex;
    flex-direction: column;
}

.description {
    color: #64748b;
    font-size: 14px;
    line-height: 1.5;
    margin: 0 0 16px 0;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    flex: 1;
    min-height: 63px; /* 3 lines height */
}

.meta-info {
    display: flex;
    justify-content: space-between;
    border-top: 1px solid #f1f5f9;
    padding-top: 12px;
    font-size: 12px;
    color: #94a3b8;
}

.meta-item {
    display: flex;
    gap: 4px;
}

.file-icon {
    color: #3b82f6;
}

/* List Styles */
/* Removed old list styles */

/* Form Styles Update */
.description-input {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    font-size: 14px;
    outline: none;
    resize: vertical;
    box-sizing: border-box;
}

.description-input:focus {
    border-color: #3b82f6;
}

.char-count {
    float: right;
    font-size: 12px;
    color: #94a3b8;
    font-weight: normal;
}

.pagination {
    display: flex;
    justify-content: center;
    gap: 16px;
    padding: 16px;
    align-items: center;
}

.pagination button {
    padding: 6px 12px;
    border: 1px solid #e2e8f0;
    background: white;
    border-radius: 4px;
    cursor: pointer;
}

.pagination button:disabled {
    background: #f1f5f9;
    color: #94a3b8;
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
    justify-content: center;
    align-items: center;
    z-index: 100;
}

.modal-content {
    background: white;
    padding: 24px;
    border-radius: 12px;
    width: 90%;
    max-width: 400px;
}

.upload-modal {
    max-width: 500px;
}

.upload-tabs {
    display: flex;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 20px;
}

.tab {
    padding: 10px 20px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    color: #64748b;
    border-bottom: 2px solid transparent;
}

.tab:hover {
    color: #1e40af;
}

.tab.active {
    color: #1e40af;
    border-bottom-color: #1e40af;
}

.modal-content h3 {
    margin: 0 0 20px 0;
    font-size: 18px;
    color: #1e293b;
}

.form-group {
    margin-bottom: 20px;
}

.form-group label {
    display: block;
    margin-bottom: 8px;
    font-size: 14px;
    font-weight: 500;
}

.form-group input[type="text"] {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    box-sizing: border-box;
}

.file-input-wrapper {
    position: relative;
    height: 40px;
    border: 1px dashed #cbd5e1;
    border-radius: 6px;
    display: flex;
    align-items: center;
    padding: 0 12px;
    cursor: pointer;
}

.file-input-wrapper input[type="file"] {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    opacity: 0;
    cursor: pointer;
}

.file-custom-label {
    color: #94a3b8;
    font-size: 14px;
}

.file-name {
    color: #334155;
    font-size: 14px;
}

.modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    margin-top: 24px;
    align-items: center;
}

.progress-bar-container {
    flex: 1;
    height: 8px;
    background: #f1f5f9;
    border-radius: 4px;
    overflow: hidden;
    margin-right: 12px;
    position: relative;
    display: flex;
    align-items: center;
}

.progress-bar {
    height: 100%;
    background: #3b82f6;
    transition: width 0.2s;
}

.progress-text {
    position: absolute;
    right: 0;
    top: -16px;
    font-size: 12px;
    color: #64748b;
}

.btn-cancel {
    padding: 8px 16px;
    border: 1px solid #cbd5e1;
    background: white;
    border-radius: 6px;
    cursor: pointer;
}

.required { color: #ef4444; }
.empty-state { text-align: center; padding: 40px; color: #64748b; }
.btn-link { background: none; border: none; color: #3b82f6; cursor: pointer; text-decoration: underline; }
.loading-state { text-align: center; padding: 40px; color: #64748b; }
.spinner { margin: 0 auto 10px; width: 30px; height: 30px; border: 2px solid #e2e8f0; border-top-color: #3b82f6; border-radius: 50%; animation: spin 1s linear infinite; }
</style>
