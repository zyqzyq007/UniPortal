<template>
  <li class="tree-node">
    <div
      class="node-row"
      :class="{ active: selectedPath === node.path }"
      @click="handleClick"
      @contextmenu.prevent="emit('contextmenu', $event, node)"
    >
      <span class="arrow" @click.stop="toggle">
        <span v-if="node.type === 'dir'">{{ expanded ? '▾' : '▸' }}</span>
      </span>
      <span class="icon">{{ node.type === 'dir' ? (expanded ? '📂' : '📁') : fileIcon }}</span>
      <span class="name" v-html="highlightedName"></span>
    </div>
    <ul v-if="node.type === 'dir' && expanded && (node.children || []).length > 0" class="children">
      <SoftwareTreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :selected-path="selectedPath"
        :expanded-map="expandedMap"
        :keyword="keyword"
        @open-file="emit('open-file', $event)"
        @toggle-dir="emit('toggle-dir', $event)"
        @contextmenu="onChildContextmenu"
      />
    </ul>
  </li>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { FileTreeNode } from '../../api/projects'

defineOptions({ name: 'SoftwareTreeNode' })

const props = defineProps<{
  node: FileTreeNode
  selectedPath: string
  expandedMap: Record<string, boolean>
  keyword: string
}>()

const emit = defineEmits<{
  (e: 'open-file', node: FileTreeNode): void
  (e: 'toggle-dir', node: FileTreeNode): void
  (e: 'contextmenu', event: MouseEvent, node: FileTreeNode): void
}>()

const expanded = computed(() => !!props.expandedMap[props.node.path])

const fileIcon = computed(() => {
  const ext = props.node.name.split('.').pop()?.toLowerCase()
  if (ext === 'js') return '🟨'
  if (ext === 'ts') return '🔷'
  if (ext === 'json') return '🟫'
  if (ext === 'md') return '📝'
  return '📄'
})

const escapeReg = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const highlightedName = computed(() => {
  if (!props.keyword.trim()) return props.node.name
  const re = new RegExp(`(${escapeReg(props.keyword)})`, 'ig')
  return props.node.name.replace(re, '<mark>$1</mark>')
})

const handleClick = () => {
  if (props.node.type === 'dir') {
    emit('toggle-dir', props.node)
    return
  }
  emit('open-file', props.node)
}

const toggle = () => {
  if (props.node.type === 'dir') {
    emit('toggle-dir', props.node)
  }
}

const onChildContextmenu = (event: MouseEvent, childNode: FileTreeNode) => {
  emit('contextmenu', event, childNode)
}
</script>

<style scoped>
.tree-node { list-style: none; }
.node-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
}
.node-row:hover { background: #f1f5f9; }
.node-row.active { background: #dbeafe; }
.arrow { width: 16px; text-align: center; color: #64748b; }
.icon { width: 18px; text-align: center; }
.name { font-size: 13px; color: #1e293b; }
.children { margin: 0; padding-left: 18px; }
:deep(mark) {
  background: #fde68a;
  color: inherit;
  padding: 0;
}
</style>
