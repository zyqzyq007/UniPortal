<template>
  <div class="tree-wrap">
    <div class="tree-toolbar">
      <input v-model="query" class="search" placeholder="搜索文件或文件夹" />
      <button class="btn-toggle" @click="toggleAll">
        {{ expandAll ? '全部收起' : '全部展开' }}
      </button>
    </div>
    <ul class="tree">
      <TreeNode
        v-for="node in filtered"
        :key="nodeKey(node)"
        :node="node"
        :activePath="activePath"
        :expandAll="expandAll"
        :level="1"
        @open-file="$emit('open-file', $event)"
      />
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { FileNode } from '../store/mockStore'
import TreeNode from './TreeNode.vue'

const props = defineProps<{ nodes: FileNode[]; activePath?: string }>()
defineEmits<{ (e: 'open-file', payload: { path: string; type: string }): void }>()

const query = ref('')
const expandAll = ref(false)

const toggleAll = () => {
  expandAll.value = !expandAll.value
}

const filterNodes = (list: FileNode[], q: string): FileNode[] => {
  if (!q) return list
  const low = q.toLowerCase()
  const walk = (n: FileNode): FileNode | null => {
    const nameMatch = n.name.toLowerCase().includes(low)
    // If it's a directory, check children
    // But children might not be loaded yet for lazy load.
    // If we want search to work on lazy loaded structure, we can only search loaded nodes.
    // Backend search is not implemented, so we filter what we have.
    
    if (n.type === 'dir') {
      const children = n.children || []
      const kids = children.map(walk).filter(Boolean) as FileNode[]
      if (nameMatch || kids.length) return { ...n, children: kids }
      return null
    }
    return nameMatch ? n : null
  }
  return list.map(walk).filter(Boolean) as FileNode[]
}

const filtered = computed(() => filterNodes(props.nodes, query.value))

watch(
  () => query.value,
  (q) => {
    if (q) expandAll.value = true
  }
)

const nodeKey = (n: FileNode) => `${n.type}-${n.name}`
</script>

<style scoped>
.tree-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tree-toolbar {
  display: flex;
  gap: 8px;
}
.search {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 13px;
}
.btn-toggle {
  flex-shrink: 0;
  padding: 6px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
  color: #0f172a;
  font-size: 12px;
  cursor: pointer;
}
.btn-toggle:hover {
  background: #eff6ff;
  border-color: #bfdbfe;
}
@media (max-width: 768px) {
  .tree-toolbar {
    flex-direction: column;
  }
  .btn-toggle {
    width: 100%;
  }
}
.tree {
  list-style: none;
  padding-left: 0;
  margin: 0;
}
.node {
  margin: 4px 0;
}
.row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 6px;
  cursor: pointer;
}
.row:hover {
  background: #f1f5f9;
}
.name.dir {
  font-weight: 600;
}
.icon {
  width: 10px;
  height: 10px;
  border-left: 2px solid #334155;
  border-bottom: 2px solid #334155;
  transform: rotate(-45deg);
  transition: transform 0.15s;
}
.icon.open {
  transform: rotate(45deg);
}
.icon.file {
  width: 10px;
  height: 10px;
  border: none;
  background: #334155;
  border-radius: 2px;
}
.children {
  list-style: none;
  padding-left: 16px;
  margin: 4px 0 0;
}
</style>
