<template>
  <div class="editor-container" ref="editorRef"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as monaco from 'monaco-editor'

const props = defineProps<{
  value: string
  language: string
  theme?: string
}>()

const emit = defineEmits<{
  (e: 'update:value', value: string): void
  (e: 'editor-mounted', editor: monaco.editor.IStandaloneCodeEditor): void
}>()

const editorRef = ref<HTMLElement | null>(null)
let editor: monaco.editor.IStandaloneCodeEditor | null = null

const initEditor = () => {
  if (!editorRef.value) return

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
  })

  editor.onDidChangeModelContent(() => {
    const val = editor?.getValue() || ''
    emit('update:value', val)
  })

  emit('editor-mounted', editor)
}

watch(
  () => props.value,
  (newVal) => {
    if (editor && editor.getValue() !== newVal) {
      editor.setValue(newVal)
    }
  }
)

watch(
  () => props.language,
  (newLang) => {
    if (editor) {
      monaco.editor.setModelLanguage(editor.getModel()!, newLang)
    }
  }
)

watch(
  () => props.theme,
  (newTheme) => {
    if (editor) {
      monaco.editor.setTheme(newTheme || 'vs-dark')
    }
  }
)

onMounted(() => {
  initEditor()
})

onBeforeUnmount(() => {
  if (editor) {
    editor.dispose()
  }
})
</script>

<style scoped>
.editor-container {
  width: 100%;
  height: 100%;
  overflow: hidden;
}
</style>