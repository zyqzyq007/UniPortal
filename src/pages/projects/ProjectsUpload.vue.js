import { ref, reactive } from 'vue';
import { useRouter } from 'vue-router';
import { createProject } from '../../api/projects';
const router = useRouter();
const name = ref('');
const description = ref('');
const repoUrl = ref('');
const fileName = ref('');
const folderName = ref('');
const selectedFile = ref(null);
const selectedFolderFiles = ref([]);
const successMessage = ref('');
const isSubmitting = ref(false);
const showInlineError = ref(false);
const inlineErrorMessage = ref('');
const canRetry = ref(false);
const abortController = ref(null);
// 验证状态
const errors = reactive({
    name: false,
    repoSource: false
});
const showErrorModal = ref(false);
const errorMessage = ref('');
const clearError = (field) => {
    errors[field] = false;
};
const onRepoUrlInput = () => {
    clearError('repoSource');
    if (repoUrl.value.trim()) {
        selectedFile.value = null;
        fileName.value = '';
        selectedFolderFiles.value = [];
        folderName.value = '';
    }
};
const onFileChange = (e) => {
    const target = e.target;
    const file = target.files && target.files[0];
    selectedFile.value = file || null;
    fileName.value = file ? file.name : '';
    selectedFolderFiles.value = [];
    folderName.value = '';
    if (file) {
        repoUrl.value = '';
    }
    clearError('repoSource');
};
const onFolderChange = (e) => {
    const target = e.target;
    const files = target.files;
    selectedFolderFiles.value = files ? Array.from(files) : [];
    folderName.value = files && files.length > 0 ? `${files.length} 个文件` : '';
    selectedFile.value = null;
    fileName.value = '';
    if (files && files.length > 0) {
        repoUrl.value = '';
    }
    clearError('repoSource');
};
const validateForm = () => {
    let isValid = true;
    // 1. 验证项目名称
    if (!name.value.trim()) {
        errors.name = true;
        isValid = false;
    }
    // 2. 验证仓库信息（三选一）
    const sources = [
        repoUrl.value.trim().length > 0,
        !!selectedFile.value,
        selectedFolderFiles.value.length > 0
    ].filter(Boolean);
    if (sources.length !== 1) {
        errors.repoSource = true;
        isValid = false;
    }
    return isValid;
};
const handleSubmit = async () => {
    // 重置错误
    errors.name = false;
    errors.repoSource = false;
    showInlineError.value = false;
    inlineErrorMessage.value = '';
    canRetry.value = false;
    if (!validateForm()) {
        // 设置错误信息并弹框
        const msgs = [];
        if (errors.name)
            msgs.push('请填写项目名称');
        if (errors.repoSource)
            msgs.push('请选择且仅选择一种仓库提交方式');
        errorMessage.value = msgs.join('\n');
        showErrorModal.value = true;
        return;
    }
    try {
        isSubmitting.value = true;
        const formData = new FormData();
        formData.append('name', name.value);
        if (description.value.trim())
            formData.append('description', description.value);
        if (repoUrl.value.trim()) {
            formData.append('repoUrl', repoUrl.value.trim());
        }
        else if (selectedFile.value) {
            formData.append('archive', selectedFile.value);
        }
        else if (selectedFolderFiles.value.length > 0) {
            selectedFolderFiles.value.forEach((file) => {
                const filePath = file.webkitRelativePath || file.name;
                formData.append('folder', file); // Send file
                formData.append('folderPaths', filePath); // Send explicit path
            });
        }
        const controller = new AbortController();
        abortController.value = controller;
        await createProject(formData, { signal: controller.signal });
        successMessage.value = '提交成功';
        router.back();
    }
    catch (err) {
        const msg = err?.message || '创建失败';
        inlineErrorMessage.value = msg;
        showInlineError.value = true;
        canRetry.value = true;
    }
    finally {
        isSubmitting.value = false;
        abortController.value = null;
    }
};
const closeErrorModal = () => {
    showErrorModal.value = false;
};
const handleRetry = () => {
    handleSubmit();
};
const handleCancel = () => {
    if (abortController.value) {
        abortController.value.abort();
    }
    isSubmitting.value = false;
    showInlineError.value = true;
    inlineErrorMessage.value = '已取消提交';
    canRetry.value = true;
};
const goBack = () => {
    if (window.history.state && window.history.state.back) {
        router.back();
    }
    else {
        router.push('/projects');
    }
};
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['custom-file-input']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "container" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "page-title" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
    ...{ onClick: (__VLS_ctx.goBack) },
    ...{ class: "btn btn-light" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "card" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.form, __VLS_intrinsicElements.form)({
    ...{ onSubmit: (__VLS_ctx.handleSubmit) },
    ...{ class: "form" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: ({ 'has-error': __VLS_ctx.errors.name }) },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ class: "required" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
    ...{ onInput: (...[$event]) => {
            __VLS_ctx.clearError('name');
        } },
    value: (__VLS_ctx.name),
    type: "text",
    placeholder: "请输入项目名称",
    ...{ class: ({ 'input-error': __VLS_ctx.errors.name }) },
});
if (__VLS_ctx.errors.name) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
        ...{ class: "error-msg" },
    });
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.textarea)({
    value: (__VLS_ctx.description),
    placeholder: "请输入项目描述",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "divider" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: ({ 'has-error': __VLS_ctx.errors.repoSource }) },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
    ...{ onInput: (__VLS_ctx.onRepoUrlInput) },
    value: (__VLS_ctx.repoUrl),
    type: "text",
    placeholder: "例如：https://github.com/org/repo.git",
    ...{ class: ({ 'input-error': __VLS_ctx.errors.repoSource && __VLS_ctx.repoUrl }) },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: ({ 'has-error': __VLS_ctx.errors.repoSource }) },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "file-input-wrapper" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
    ...{ onChange: (__VLS_ctx.onFileChange) },
    type: "file",
    accept: ".zip,.tar,.tar.gz",
    ...{ class: ({ 'input-error': __VLS_ctx.errors.repoSource && __VLS_ctx.fileName }) },
});
if (__VLS_ctx.fileName) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.small, __VLS_intrinsicElements.small)({});
    (__VLS_ctx.fileName);
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: ({ 'has-error': __VLS_ctx.errors.repoSource }) },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "custom-file-input" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
    ...{ onChange: (__VLS_ctx.onFolderChange) },
    type: "file",
    webkitdirectory: true,
    directory: true,
    id: "folder-input",
    ...{ class: "hidden-input" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({
    for: "folder-input",
    ...{ class: "btn btn-secondary" },
    ...{ class: ({ 'btn-error': __VLS_ctx.errors.repoSource && __VLS_ctx.folderName }) },
});
if (__VLS_ctx.folderName) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "file-name" },
    });
    (__VLS_ctx.folderName);
}
if (__VLS_ctx.errors.repoSource) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
        ...{ class: "error-msg" },
    });
}
if (__VLS_ctx.showInlineError) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "inline-error" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "inline-icon" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "inline-text" },
    });
    (__VLS_ctx.inlineErrorMessage);
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "actions" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
    ...{ class: "btn" },
    type: "submit",
    disabled: (__VLS_ctx.isSubmitting),
});
(__VLS_ctx.isSubmitting ? '提交中...' : '提交');
if (__VLS_ctx.canRetry && !__VLS_ctx.isSubmitting) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.handleRetry) },
        ...{ class: "btn btn-secondary" },
        type: "button",
    });
}
if (__VLS_ctx.isSubmitting) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.handleCancel) },
        ...{ class: "btn btn-light" },
        type: "button",
    });
}
if (__VLS_ctx.successMessage) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
        ...{ class: "success" },
    });
    (__VLS_ctx.successMessage);
}
const __VLS_0 = {}.Transition;
/** @type {[typeof __VLS_components.Transition, typeof __VLS_components.Transition, ]} */ ;
// @ts-ignore
const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
    name: "fade",
}));
const __VLS_2 = __VLS_1({
    name: "fade",
}, ...__VLS_functionalComponentArgsRest(__VLS_1));
__VLS_3.slots.default;
if (__VLS_ctx.showErrorModal) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-overlay" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-content" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({
        ...{ class: "modal-title" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
        ...{ class: "modal-message" },
    });
    (__VLS_ctx.errorMessage);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.closeErrorModal) },
        ...{ class: "btn btn-primary" },
    });
}
var __VLS_3;
/** @type {__VLS_StyleScopedClasses['container']} */ ;
/** @type {__VLS_StyleScopedClasses['page-title']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-light']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['form']} */ ;
/** @type {__VLS_StyleScopedClasses['required']} */ ;
/** @type {__VLS_StyleScopedClasses['error-msg']} */ ;
/** @type {__VLS_StyleScopedClasses['divider']} */ ;
/** @type {__VLS_StyleScopedClasses['file-input-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['custom-file-input']} */ ;
/** @type {__VLS_StyleScopedClasses['hidden-input']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-secondary']} */ ;
/** @type {__VLS_StyleScopedClasses['file-name']} */ ;
/** @type {__VLS_StyleScopedClasses['error-msg']} */ ;
/** @type {__VLS_StyleScopedClasses['inline-error']} */ ;
/** @type {__VLS_StyleScopedClasses['inline-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['inline-text']} */ ;
/** @type {__VLS_StyleScopedClasses['actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-secondary']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-light']} */ ;
/** @type {__VLS_StyleScopedClasses['success']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-overlay']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-content']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-title']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-message']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-primary']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            name: name,
            description: description,
            repoUrl: repoUrl,
            fileName: fileName,
            folderName: folderName,
            successMessage: successMessage,
            isSubmitting: isSubmitting,
            showInlineError: showInlineError,
            inlineErrorMessage: inlineErrorMessage,
            canRetry: canRetry,
            errors: errors,
            showErrorModal: showErrorModal,
            errorMessage: errorMessage,
            clearError: clearError,
            onRepoUrlInput: onRepoUrlInput,
            onFileChange: onFileChange,
            onFolderChange: onFolderChange,
            handleSubmit: handleSubmit,
            closeErrorModal: closeErrorModal,
            handleRetry: handleRetry,
            handleCancel: handleCancel,
            goBack: goBack,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
