/// <reference types="../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue';
import * as monaco from 'monaco-editor';
import { getSoftwareItemFileContent } from '../api/projects';
const props = defineProps();
const editorContainer = ref(null);
let editor = null;
const content = ref('');
const loading = ref(false);
const error = ref('');
const language = computed(() => {
    if (!props.file)
        return 'plaintext';
    const ext = props.file.name.split('.').pop()?.toLowerCase();
    const map = {
        js: 'javascript',
        ts: 'typescript',
        py: 'python',
        html: 'html',
        css: 'css',
        json: 'json',
        md: 'markdown',
        vue: 'html' // simplified
    };
    return map[ext || ''] || 'plaintext';
});
const formatSize = (bytes) => {
    if (bytes < 1024)
        return bytes + ' B';
    return (bytes / 1024).toFixed(1) + ' KB';
};
const loadFile = async () => {
    if (!props.file)
        return;
    loading.value = true;
    error.value = '';
    try {
        const res = await getSoftwareItemFileContent(props.projectId, props.itemId, props.file.path);
        if (res.code === 200) {
            content.value = res.data.content;
            if (editor) {
                editor.setValue(content.value);
                monaco.editor.setModelLanguage(editor.getModel(), language.value);
            }
        }
        else {
            error.value = res.message || '加载失败';
        }
    }
    catch (e) {
        error.value = '请求失败';
    }
    finally {
        loading.value = false;
    }
};
watch(() => props.file, () => {
    loadFile();
});
onMounted(() => {
    if (editorContainer.value) {
        editor = monaco.editor.create(editorContainer.value, {
            value: '',
            language: 'plaintext',
            theme: 'vs', // 'vs-dark' based on system preference
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 13,
            scrollBeyondLastLine: false,
            automaticLayout: true
        });
    }
    loadFile();
});
onBeforeUnmount(() => {
    if (editor) {
        editor.dispose();
    }
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "file-viewer" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "viewer-header" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "file-meta" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ class: "path" },
});
(__VLS_ctx.file.path);
if (__VLS_ctx.content) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "info" },
    });
    (__VLS_ctx.language);
    (__VLS_ctx.formatSize(__VLS_ctx.file.size));
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "viewer-body" },
    ref: "editorContainer",
});
/** @type {typeof __VLS_ctx.editorContainer} */ ;
if (__VLS_ctx.loading) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "loading-overlay" },
    });
}
if (__VLS_ctx.error) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "error-state" },
    });
    (__VLS_ctx.error);
}
/** @type {__VLS_StyleScopedClasses['file-viewer']} */ ;
/** @type {__VLS_StyleScopedClasses['viewer-header']} */ ;
/** @type {__VLS_StyleScopedClasses['file-meta']} */ ;
/** @type {__VLS_StyleScopedClasses['path']} */ ;
/** @type {__VLS_StyleScopedClasses['info']} */ ;
/** @type {__VLS_StyleScopedClasses['viewer-body']} */ ;
/** @type {__VLS_StyleScopedClasses['loading-overlay']} */ ;
/** @type {__VLS_StyleScopedClasses['error-state']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            editorContainer: editorContainer,
            content: content,
            loading: loading,
            error: error,
            language: language,
            formatSize: formatSize,
        };
    },
    __typeProps: {},
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
    __typeProps: {},
});
; /* PartiallyEnd: #4569/main.vue */
