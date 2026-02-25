/// <reference types="../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { ref, onMounted, onBeforeUnmount, watch } from 'vue';
import * as monaco from 'monaco-editor';
const props = defineProps();
const emit = defineEmits();
const editorRef = ref(null);
let editor = null;
const initEditor = () => {
    if (!editorRef.value)
        return;
    editor = monaco.editor.create(editorRef.value, {
        value: props.value,
        language: props.language || 'plaintext',
        theme: props.theme || 'vs-dark',
        automaticLayout: true,
        minimap: {
            enabled: true
        },
        fontSize: 14,
        scrollBeyondLastLine: false,
        renderWhitespace: 'selection',
        tabSize: 2,
    });
    editor.onDidChangeModelContent(() => {
        const val = editor?.getValue() || '';
        emit('update:value', val);
    });
    emit('editor-mounted', editor);
};
watch(() => props.value, (newVal) => {
    if (editor && editor.getValue() !== newVal) {
        editor.setValue(newVal);
    }
});
watch(() => props.language, (newLang) => {
    if (editor) {
        monaco.editor.setModelLanguage(editor.getModel(), newLang);
    }
});
watch(() => props.theme, (newTheme) => {
    if (editor) {
        monaco.editor.setTheme(newTheme || 'vs-dark');
    }
});
onMounted(() => {
    initEditor();
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
    ...{ class: "editor-container" },
    ref: "editorRef",
});
/** @type {typeof __VLS_ctx.editorRef} */ ;
/** @type {__VLS_StyleScopedClasses['editor-container']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            editorRef: editorRef,
        };
    },
    __typeEmits: {},
    __typeProps: {},
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
    __typeEmits: {},
    __typeProps: {},
});
; /* PartiallyEnd: #4569/main.vue */
