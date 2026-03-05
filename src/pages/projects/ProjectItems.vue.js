/// <reference types="../../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { ref, reactive, computed, onMounted, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getSoftwareItems, deleteSoftwareItem, uploadSoftwareItem, downloadSoftwareItem } from '../../api/projects';
import { debounce } from 'lodash-es';
const route = useRoute();
const router = useRouter();
const projectId = route.params.projectId;
const items = ref([]);
const loading = ref(true);
const searchQuery = ref('');
const currentPage = ref(1);
const totalPages = ref(1);
const PAGE_SIZE = 10;
const selectedItems = ref([]);
// Upload state
const showUploadModal = ref(false);
const isUploading = ref(false);
const uploadProgress = ref(0);
const uploadMode = ref('folder');
const uploadFiles = ref([]);
const uploadArchive = ref(null);
const fileInput = ref(null);
const uploadForm = reactive({
    name: '',
    version: '',
    description: ''
});
const descriptionLength = computed(() => uploadForm.description.length);
// Delete state
const showDeleteModal = ref(false);
const itemToDelete = ref(null);
const isDeleting = ref(false);
const isAllSelected = computed(() => {
    return items.value.length > 0 && selectedItems.value.length === items.value.length;
});
const fetchItems = async () => {
    try {
        loading.value = true;
        const res = await getSoftwareItems(projectId, {
            search: searchQuery.value,
            page: currentPage.value,
            limit: PAGE_SIZE
        });
        if (res.code === 200) {
            items.value = res.data.items;
            totalPages.value = res.data.totalPages;
            currentPage.value = res.data.page;
            selectedItems.value = []; // Reset selection
        }
    }
    catch (error) {
        console.error('Failed to fetch items', error);
    }
    finally {
        loading.value = false;
    }
};
const handleSearch = debounce(() => {
    currentPage.value = 1;
    fetchItems();
}, 300);
const changePage = (page) => {
    currentPage.value = page;
    fetchItems();
};
const goToDetail = (item) => {
    router.push({
        name: 'SoftwareItemDetail',
        params: { projectId, itemId: item.item_id },
        query: { ...route.query, itemName: item.name }
    });
};
const toggleSelectAll = () => {
    if (isAllSelected.value) {
        selectedItems.value = [];
    }
    else {
        selectedItems.value = items.value.map(item => item.item_id);
    }
};
const formatSize = (bytes) => {
    const size = Number(bytes);
    if (isNaN(size))
        return '-';
    if (size < 1024)
        return size + ' B';
    if (size < 1024 * 1024)
        return (size / 1024).toFixed(2) + ' KB';
    if (size < 1024 * 1024 * 1024)
        return (size / 1024 / 1024).toFixed(2) + ' MB';
    return (size / 1024 / 1024 / 1024).toFixed(2) + ' GB';
};
const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
};
const closeUploadModal = () => {
    showUploadModal.value = false;
};
// Upload Logic
const openUploadModal = () => {
    uploadForm.name = '';
    uploadForm.version = '';
    uploadForm.description = '';
    uploadMode.value = 'folder';
    uploadFiles.value = [];
    uploadArchive.value = null;
    uploadProgress.value = 0;
    if (fileInput.value)
        fileInput.value.value = '';
    showUploadModal.value = true;
};
const handleFolderChange = (e) => {
    const target = e.target;
    if (target.files && target.files.length > 0) {
        uploadFiles.value = Array.from(target.files);
        // Auto-fill name from folder name (first file's path usually starts with folder name)
        if (!uploadForm.name && uploadFiles.value.length > 0) {
            const path = uploadFiles.value[0].webkitRelativePath;
            if (path) {
                uploadForm.name = path.split('/')[0];
            }
        }
    }
};
const handleArchiveChange = (e) => {
    const target = e.target;
    if (target.files && target.files[0]) {
        uploadArchive.value = target.files[0];
        if (!uploadForm.name) {
            // Remove extension
            const name = uploadArchive.value.name;
            uploadForm.name = name.substring(0, name.lastIndexOf('.')) || name;
        }
    }
};
const handleUpload = async () => {
    if (!uploadForm.name)
        return;
    if (uploadMode.value === 'folder' && uploadFiles.value.length === 0)
        return;
    if (uploadMode.value === 'archive' && !uploadArchive.value)
        return;
    try {
        isUploading.value = true;
        uploadProgress.value = 0;
        const formData = new FormData();
        formData.append('name', uploadForm.name);
        if (uploadForm.version)
            formData.append('version', uploadForm.version);
        if (uploadForm.description)
            formData.append('description', uploadForm.description);
        if (uploadMode.value === 'folder') {
            uploadFiles.value.forEach(file => {
                formData.append('files', file);
                formData.append('paths[]', file.webkitRelativePath);
            });
        }
        else {
            if (uploadArchive.value) {
                formData.append('archive', uploadArchive.value);
            }
        }
        const res = await uploadSoftwareItem(projectId, formData, {
            onUploadProgress: (progressEvent) => {
                if (progressEvent.total) {
                    const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                    uploadProgress.value = percentCompleted;
                }
            }
        });
        if (res.code === 201) {
            closeUploadModal();
            fetchItems();
        }
        else {
            alert(res.message || '上传失败');
        }
    }
    catch (error) {
        console.error('Upload failed', error);
        alert('上传失败，请重试');
    }
    finally {
        isUploading.value = false;
    }
};
// Download Logic
const handleDownload = (item) => {
    const url = downloadSoftwareItem(projectId, item.item_id);
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
        }).then((response) => {
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
            console.error('Download error', err);
            alert('下载失败');
        });
    });
};
// Delete Logic
const confirmDelete = (item) => {
    itemToDelete.value = item;
    showDeleteModal.value = true;
};
const confirmBatchDelete = () => {
    itemToDelete.value = null;
    showDeleteModal.value = true;
};
const cancelDelete = () => {
    showDeleteModal.value = false;
    itemToDelete.value = null;
};
const executeDelete = async () => {
    try {
        isDeleting.value = true;
        if (itemToDelete.value) {
            await deleteSoftwareItem(projectId, itemToDelete.value.item_id);
        }
        else {
            // Batch delete
            // Since we don't have batch API yet, we loop.
            await Promise.all(selectedItems.value.map(id => deleteSoftwareItem(projectId, id)));
        }
        showDeleteModal.value = false;
        itemToDelete.value = null;
        selectedItems.value = [];
        fetchItems();
    }
    catch (error) {
        console.error('Delete failed', error);
        alert('删除失败，部分项目可能未删除');
        fetchItems();
    }
    finally {
        isDeleting.value = false;
    }
};
onMounted(() => {
    if (route.query.search) {
        searchQuery.value = String(route.query.search);
    }
    if (route.query.page) {
        currentPage.value = Number(route.query.page) || 1;
    }
    fetchItems();
    if (route.query.action === 'upload') {
        openUploadModal();
    }
});
watch([searchQuery, currentPage], () => {
    router.replace({
        query: {
            ...route.query,
            search: searchQuery.value || undefined,
            page: String(currentPage.value)
        }
    });
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['page-header']} */ ;
/** @type {__VLS_StyleScopedClasses['items-card']} */ ;
/** @type {__VLS_StyleScopedClasses['title-text']} */ ;
/** @type {__VLS_StyleScopedClasses['description-input']} */ ;
/** @type {__VLS_StyleScopedClasses['pagination']} */ ;
/** @type {__VLS_StyleScopedClasses['pagination']} */ ;
/** @type {__VLS_StyleScopedClasses['tab']} */ ;
/** @type {__VLS_StyleScopedClasses['tab']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-content']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['file-input-wrapper']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "items-container" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "page-header" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "actions" },
});
if (__VLS_ctx.selectedItems.length > 0) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.confirmBatchDelete) },
        ...{ class: "btn-danger" },
    });
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
    ...{ onClick: (__VLS_ctx.openUploadModal) },
    ...{ class: "btn-primary" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "filters" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "search-wrapper" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
    ...{ class: "search-icon" },
    width: "20",
    height: "20",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    'stroke-width': "2",
    'stroke-linecap': "round",
    'stroke-linejoin': "round",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.circle, __VLS_intrinsicElements.circle)({
    cx: "11",
    cy: "11",
    r: "8",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.line, __VLS_intrinsicElements.line)({
    x1: "21",
    y1: "21",
    x2: "16.65",
    y2: "16.65",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
    ...{ onInput: (__VLS_ctx.handleSearch) },
    placeholder: "搜索项目名称...",
    ...{ class: "search-input" },
});
(__VLS_ctx.searchQuery);
if (__VLS_ctx.loading) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "loading-state" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "spinner" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
}
else if (__VLS_ctx.items.length === 0) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "empty-state" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.openUploadModal) },
        ...{ class: "btn-link" },
    });
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "items-grid" },
    });
    for (const [item] of __VLS_getVForSourceType((__VLS_ctx.items))) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ onClick: (...[$event]) => {
                    if (!!(__VLS_ctx.loading))
                        return;
                    if (!!(__VLS_ctx.items.length === 0))
                        return;
                    __VLS_ctx.goToDetail(item);
                } },
            ...{ class: "items-card" },
            key: (item.item_id),
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "card-header" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "card-title" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "file-icon" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
            width: "24",
            height: "24",
            viewBox: "0 0 24 24",
            fill: "none",
            stroke: "currentColor",
            'stroke-width': "2",
            'stroke-linecap': "round",
            'stroke-linejoin': "round",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.path, __VLS_intrinsicElements.path)({
            d: "M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.polyline, __VLS_intrinsicElements.polyline)({
            points: "13 2 13 9 20 9",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "title-text" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.h4, __VLS_intrinsicElements.h4)({});
        (item.name);
        if (item.version) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
                ...{ class: "version-tag" },
            });
            (item.version);
        }
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "card-actions" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (...[$event]) => {
                    if (!!(__VLS_ctx.loading))
                        return;
                    if (!!(__VLS_ctx.items.length === 0))
                        return;
                    __VLS_ctx.handleDownload(item);
                } },
            ...{ class: "btn-icon" },
            title: "下载",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
            width: "18",
            height: "18",
            viewBox: "0 0 24 24",
            fill: "none",
            stroke: "currentColor",
            'stroke-width': "2",
            'stroke-linecap': "round",
            'stroke-linejoin': "round",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.path, __VLS_intrinsicElements.path)({
            d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.polyline, __VLS_intrinsicElements.polyline)({
            points: "7 10 12 15 17 10",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.line, __VLS_intrinsicElements.line)({
            x1: "12",
            y1: "15",
            x2: "12",
            y2: "3",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (...[$event]) => {
                    if (!!(__VLS_ctx.loading))
                        return;
                    if (!!(__VLS_ctx.items.length === 0))
                        return;
                    __VLS_ctx.confirmDelete(item);
                } },
            ...{ class: "btn-icon danger" },
            title: "删除",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
            width: "18",
            height: "18",
            viewBox: "0 0 24 24",
            fill: "none",
            stroke: "currentColor",
            'stroke-width': "2",
            'stroke-linecap': "round",
            'stroke-linejoin': "round",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.polyline, __VLS_intrinsicElements.polyline)({
            points: "3 6 5 6 21 6",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.path, __VLS_intrinsicElements.path)({
            d: "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "card-body" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
            ...{ class: "description" },
        });
        (item.description || '暂无描述');
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "meta-info" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "meta-item" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "label" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "value" },
        });
        (__VLS_ctx.formatSize(item.file_size));
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "meta-item" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "label" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "value" },
        });
        (__VLS_ctx.formatDate(item.uploaded_at));
    }
    if (__VLS_ctx.totalPages > 1) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "pagination" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (...[$event]) => {
                    if (!!(__VLS_ctx.loading))
                        return;
                    if (!!(__VLS_ctx.items.length === 0))
                        return;
                    if (!(__VLS_ctx.totalPages > 1))
                        return;
                    __VLS_ctx.changePage(__VLS_ctx.currentPage - 1);
                } },
            disabled: (__VLS_ctx.currentPage === 1),
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
        (__VLS_ctx.currentPage);
        (__VLS_ctx.totalPages);
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (...[$event]) => {
                    if (!!(__VLS_ctx.loading))
                        return;
                    if (!!(__VLS_ctx.items.length === 0))
                        return;
                    if (!(__VLS_ctx.totalPages > 1))
                        return;
                    __VLS_ctx.changePage(__VLS_ctx.currentPage + 1);
                } },
            disabled: (__VLS_ctx.currentPage === __VLS_ctx.totalPages),
        });
    }
}
if (__VLS_ctx.showUploadModal) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-overlay" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-content upload-modal" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.form, __VLS_intrinsicElements.form)({
        ...{ onSubmit: (__VLS_ctx.handleUpload) },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "upload-tabs" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ onClick: (...[$event]) => {
                if (!(__VLS_ctx.showUploadModal))
                    return;
                __VLS_ctx.uploadMode = 'folder';
            } },
        ...{ class: "tab" },
        ...{ class: ({ active: __VLS_ctx.uploadMode === 'folder' }) },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ onClick: (...[$event]) => {
                if (!(__VLS_ctx.showUploadModal))
                    return;
                __VLS_ctx.uploadMode = 'archive';
            } },
        ...{ class: "tab" },
        ...{ class: ({ active: __VLS_ctx.uploadMode === 'archive' }) },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "form-group" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "required" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
        value: (__VLS_ctx.uploadForm.name),
        type: "text",
        placeholder: "请输入名称",
        required: true,
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "form-group" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
        value: (__VLS_ctx.uploadForm.version),
        type: "text",
        placeholder: "例如 1.0.0",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "form-group" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "char-count" },
    });
    (__VLS_ctx.descriptionLength);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.textarea, __VLS_intrinsicElements.textarea)({
        value: (__VLS_ctx.uploadForm.description),
        placeholder: "请输入项目描述（选填）",
        rows: "4",
        maxlength: "500",
        ...{ class: "description-input" },
    });
    if (__VLS_ctx.uploadMode === 'folder') {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "form-group" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "required" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "file-input-wrapper" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
            ...{ onChange: (__VLS_ctx.handleFolderChange) },
            type: "file",
            required: true,
            webkitdirectory: true,
            directory: true,
        });
        if (__VLS_ctx.uploadFiles.length === 0) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
                ...{ class: "file-custom-label" },
            });
        }
        else {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
                ...{ class: "file-name" },
            });
            (__VLS_ctx.uploadFiles.length);
        }
    }
    if (__VLS_ctx.uploadMode === 'archive') {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "form-group" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "required" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "file-input-wrapper" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
            ...{ onChange: (__VLS_ctx.handleArchiveChange) },
            type: "file",
            required: true,
            accept: ".zip,.rar,.7z",
        });
        if (!__VLS_ctx.uploadArchive) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
                ...{ class: "file-custom-label" },
            });
        }
        else {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
                ...{ class: "file-name" },
            });
            (__VLS_ctx.uploadArchive.name);
        }
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-actions" },
    });
    if (__VLS_ctx.isUploading) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "progress-bar-container" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "progress-bar" },
            ...{ style: ({ width: __VLS_ctx.uploadProgress + '%' }) },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "progress-text" },
        });
        (__VLS_ctx.uploadProgress);
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.closeUploadModal) },
        type: "button",
        ...{ class: "btn-cancel" },
        disabled: (__VLS_ctx.isUploading),
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        type: "submit",
        ...{ class: "btn-primary" },
        disabled: (__VLS_ctx.isUploading),
    });
    (__VLS_ctx.isUploading ? (__VLS_ctx.uploadProgress === 100 ? '处理中...' : '上传中...') : '开始上传');
}
if (__VLS_ctx.showDeleteModal) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-overlay" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-content" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
    if (__VLS_ctx.itemToDelete) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
        (__VLS_ctx.itemToDelete.name);
    }
    else {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
        (__VLS_ctx.selectedItems.length);
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-actions" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.cancelDelete) },
        ...{ class: "btn-cancel" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.executeDelete) },
        ...{ class: "btn-danger-solid" },
        disabled: (__VLS_ctx.isDeleting),
    });
    (__VLS_ctx.isDeleting ? '删除中...' : '确认删除');
}
/** @type {__VLS_StyleScopedClasses['items-container']} */ ;
/** @type {__VLS_StyleScopedClasses['page-header']} */ ;
/** @type {__VLS_StyleScopedClasses['actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-danger']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-primary']} */ ;
/** @type {__VLS_StyleScopedClasses['filters']} */ ;
/** @type {__VLS_StyleScopedClasses['search-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['search-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['search-input']} */ ;
/** @type {__VLS_StyleScopedClasses['loading-state']} */ ;
/** @type {__VLS_StyleScopedClasses['spinner']} */ ;
/** @type {__VLS_StyleScopedClasses['empty-state']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-link']} */ ;
/** @type {__VLS_StyleScopedClasses['items-grid']} */ ;
/** @type {__VLS_StyleScopedClasses['items-card']} */ ;
/** @type {__VLS_StyleScopedClasses['card-header']} */ ;
/** @type {__VLS_StyleScopedClasses['card-title']} */ ;
/** @type {__VLS_StyleScopedClasses['file-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['title-text']} */ ;
/** @type {__VLS_StyleScopedClasses['version-tag']} */ ;
/** @type {__VLS_StyleScopedClasses['card-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['danger']} */ ;
/** @type {__VLS_StyleScopedClasses['card-body']} */ ;
/** @type {__VLS_StyleScopedClasses['description']} */ ;
/** @type {__VLS_StyleScopedClasses['meta-info']} */ ;
/** @type {__VLS_StyleScopedClasses['meta-item']} */ ;
/** @type {__VLS_StyleScopedClasses['label']} */ ;
/** @type {__VLS_StyleScopedClasses['value']} */ ;
/** @type {__VLS_StyleScopedClasses['meta-item']} */ ;
/** @type {__VLS_StyleScopedClasses['label']} */ ;
/** @type {__VLS_StyleScopedClasses['value']} */ ;
/** @type {__VLS_StyleScopedClasses['pagination']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-overlay']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-content']} */ ;
/** @type {__VLS_StyleScopedClasses['upload-modal']} */ ;
/** @type {__VLS_StyleScopedClasses['upload-tabs']} */ ;
/** @type {__VLS_StyleScopedClasses['tab']} */ ;
/** @type {__VLS_StyleScopedClasses['tab']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['required']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['char-count']} */ ;
/** @type {__VLS_StyleScopedClasses['description-input']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['required']} */ ;
/** @type {__VLS_StyleScopedClasses['file-input-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['file-custom-label']} */ ;
/** @type {__VLS_StyleScopedClasses['file-name']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['required']} */ ;
/** @type {__VLS_StyleScopedClasses['file-input-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['file-custom-label']} */ ;
/** @type {__VLS_StyleScopedClasses['file-name']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['progress-bar-container']} */ ;
/** @type {__VLS_StyleScopedClasses['progress-bar']} */ ;
/** @type {__VLS_StyleScopedClasses['progress-text']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-cancel']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-primary']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-overlay']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-content']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-cancel']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-danger-solid']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            items: items,
            loading: loading,
            searchQuery: searchQuery,
            currentPage: currentPage,
            totalPages: totalPages,
            selectedItems: selectedItems,
            showUploadModal: showUploadModal,
            isUploading: isUploading,
            uploadProgress: uploadProgress,
            uploadMode: uploadMode,
            uploadFiles: uploadFiles,
            uploadArchive: uploadArchive,
            uploadForm: uploadForm,
            descriptionLength: descriptionLength,
            showDeleteModal: showDeleteModal,
            itemToDelete: itemToDelete,
            isDeleting: isDeleting,
            handleSearch: handleSearch,
            changePage: changePage,
            goToDetail: goToDetail,
            formatSize: formatSize,
            formatDate: formatDate,
            closeUploadModal: closeUploadModal,
            openUploadModal: openUploadModal,
            handleFolderChange: handleFolderChange,
            handleArchiveChange: handleArchiveChange,
            handleUpload: handleUpload,
            handleDownload: handleDownload,
            confirmDelete: confirmDelete,
            confirmBatchDelete: confirmBatchDelete,
            cancelDelete: cancelDelete,
            executeDelete: executeDelete,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
