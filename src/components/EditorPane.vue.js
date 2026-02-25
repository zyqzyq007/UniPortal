/// <reference types="../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { watch, ref, computed, shallowRef } from 'vue';
import { getProjectFileContent } from '../api/projects';
import CodeEditor from './CodeEditor.vue';
import CodeStructure from './CodeStructure.vue';
const props = defineProps();
const content = ref('');
const loading = ref(false);
const error = ref('');
const unsupported = ref(false);
const showStructure = ref(true);
const editorInstance = shallowRef(null);
let requestSeq = 0;
const language = computed(() => {
    if (!props.filePath)
        return 'plaintext';
    const ext = props.filePath.split('.').pop()?.toLowerCase();
    if (ext === 'js' || ext === 'jsx')
        return 'javascript';
    if (ext === 'ts' || ext === 'tsx')
        return 'typescript';
    if (ext === 'html')
        return 'html';
    if (ext === 'css')
        return 'css';
    if (ext === 'json')
        return 'json';
    if (ext === 'py')
        return 'python';
    if (ext === 'vue')
        return 'html'; // Monaco's vue support needs plugins, fallback to html for now
    return 'plaintext';
});
const onEditorMounted = (editor) => {
    editorInstance.value = editor;
};
const toggleStructure = () => {
    showStructure.value = !showStructure.value;
    // Resize editor after layout change
    setTimeout(() => {
        editorInstance.value?.layout();
    }, 50);
};
watch(() => props.filePath, async (p) => {
    content.value = '';
    error.value = '';
    unsupported.value = false;
    if (p) {
        await loadContent();
    }
}, { immediate: true });
const loadContent = async () => {
    if (!props.filePath)
        return;
    const seq = ++requestSeq;
    loading.value = true;
    error.value = '';
    unsupported.value = false;
    try {
        const res = await getProjectFileContent(props.projectId, props.filePath);
        if (seq !== requestSeq)
            return;
        content.value = res.data?.content ?? '';
    }
    catch (e) {
        if (seq !== requestSeq)
            return;
        if (e.code === 415) {
            unsupported.value = true;
            return;
        }
        error.value = e.message || '加载失败';
    }
    finally {
        if (seq === requestSeq)
            loading.value = false;
    }
};
const onSave = () => {
    // TODO: 接入后端保存接口
};
const onDownload = () => {
    if (!props.filePath)
        return;
    const blob = new Blob([content.value], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = props.filePath.split('/').pop() || 'file.txt';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
};
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "editor" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "toolbar" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "title" },
});
(__VLS_ctx.filePath || '未选择文件');
if (__VLS_ctx.filePath) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "actions" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.toggleStructure) },
        ...{ class: "btn" },
        ...{ class: ({ active: __VLS_ctx.showStructure }) },
        title: "Toggle Outline",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.onSave) },
        ...{ class: "btn" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.onDownload) },
        ...{ class: "btn" },
    });
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "body" },
});
if (__VLS_ctx.filePath) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "content-wrap" },
    });
    if (__VLS_ctx.loading) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "loading" },
        });
    }
    else if (__VLS_ctx.error) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "error" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "error-text" },
        });
        (__VLS_ctx.error);
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (__VLS_ctx.loadContent) },
            ...{ class: "btn retry" },
        });
    }
    else if (__VLS_ctx.unsupported) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "unsupported" },
        });
    }
    else {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "editor-layout" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "main-editor" },
        });
        /** @type {[typeof CodeEditor, ]} */ ;
        // @ts-ignore
        const __VLS_0 = __VLS_asFunctionalComponent(CodeEditor, new CodeEditor({
            ...{ 'onEditorMounted': {} },
            value: (__VLS_ctx.content),
            language: (__VLS_ctx.language),
        }));
        const __VLS_1 = __VLS_0({
            ...{ 'onEditorMounted': {} },
            value: (__VLS_ctx.content),
            language: (__VLS_ctx.language),
        }, ...__VLS_functionalComponentArgsRest(__VLS_0));
        let __VLS_3;
        let __VLS_4;
        let __VLS_5;
        const __VLS_6 = {
            onEditorMounted: (__VLS_ctx.onEditorMounted)
        };
        var __VLS_2;
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "side-panel" },
        });
        __VLS_asFunctionalDirective(__VLS_directives.vShow)(null, { ...__VLS_directiveBindingRestFields, value: (__VLS_ctx.showStructure) }, null, null);
        /** @type {[typeof CodeStructure, ]} */ ;
        // @ts-ignore
        const __VLS_7 = __VLS_asFunctionalComponent(CodeStructure, new CodeStructure({
            editor: (__VLS_ctx.editorInstance),
        }));
        const __VLS_8 = __VLS_7({
            editor: (__VLS_ctx.editorInstance),
        }, ...__VLS_functionalComponentArgsRest(__VLS_7));
    }
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "placeholder" },
    });
}
/** @type {__VLS_StyleScopedClasses['editor']} */ ;
/** @type {__VLS_StyleScopedClasses['toolbar']} */ ;
/** @type {__VLS_StyleScopedClasses['title']} */ ;
/** @type {__VLS_StyleScopedClasses['actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['body']} */ ;
/** @type {__VLS_StyleScopedClasses['content-wrap']} */ ;
/** @type {__VLS_StyleScopedClasses['loading']} */ ;
/** @type {__VLS_StyleScopedClasses['error']} */ ;
/** @type {__VLS_StyleScopedClasses['error-text']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['retry']} */ ;
/** @type {__VLS_StyleScopedClasses['unsupported']} */ ;
/** @type {__VLS_StyleScopedClasses['editor-layout']} */ ;
/** @type {__VLS_StyleScopedClasses['main-editor']} */ ;
/** @type {__VLS_StyleScopedClasses['side-panel']} */ ;
/** @type {__VLS_StyleScopedClasses['placeholder']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            CodeEditor: CodeEditor,
            CodeStructure: CodeStructure,
            content: content,
            loading: loading,
            error: error,
            unsupported: unsupported,
            showStructure: showStructure,
            editorInstance: editorInstance,
            language: language,
            onEditorMounted: onEditorMounted,
            toggleStructure: toggleStructure,
            loadContent: loadContent,
            onSave: onSave,
            onDownload: onDownload,
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
