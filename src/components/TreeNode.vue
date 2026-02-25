<template>
  <li class="node">
    <div
      class="row"
      :class="{ active: isActive }"
      @click="onClick"
    >
      <div v-if="node.type === 'dir'" class="arrow-wrapper" @click.stop="onClick">
        <ArrowIcon class="arrow" :class="{ expanded: expanded }" />
      </div>
      <div class="icon-wrapper">
        <component :is="getIcon(node)" class="file-icon" />
      </div>
      <span :class="['name', node.type === 'dir' ? 'dir' : 'file']">{{ node.name }}</span>
      <span v-if="error" class="error-indicator" title="加载失败">⚠️</span>
    </div>
    <Transition name="collapse">
      <ul
        v-if="node.type === 'dir' && expanded && node.children && node.children.length && currentLevel < 5"
        class="children"
      >
        <TreeNode
          v-for="child in node.children"
          :key="childKey(child)"
          :node="child"
          :parentPath="currentPath"
          :activePath="activePath"
          :expandAll="expandAll"
          :level="currentLevel + 1"
          @open-file="$emit('open-file', $event)"
        />
      </ul>
    </Transition>
  </li>
</template>

<script setup lang="ts">
import { ref, computed, defineAsyncComponent, watch } from 'vue'
import type { FileNode } from '../store/mockStore'
import { getProjectStructure } from '../api/projects'
import { useRoute } from 'vue-router'

defineOptions({ name: 'TreeNode' })

const props = defineProps<{
  node: FileNode
  parentPath?: string
  activePath?: string
  expandAll?: boolean
  level?: number
}>()
const emit = defineEmits<{ (e: 'open-file', payload: { path: string; type: string }): void }>()
const expanded = ref(!!props.expandAll) // Default closed unless expandAll is true
const currentLevel = computed(() => props.level ?? 1)
const loading = ref(false)
const error = ref(false)
const route = useRoute()
const projectId = computed(() => route.params.projectId as string)

const ArrowIcon = defineAsyncComponent(() => import('../assets/icons/chevron-right.svg'))
const FolderIcon = defineAsyncComponent(() => import('../assets/icons/folder.svg'))
const FolderOpenIcon = defineAsyncComponent(() => import('../assets/icons/folder-open.svg'))
const JsIcon = defineAsyncComponent(() => import('../assets/icons/js.svg'))
const TsIcon = defineAsyncComponent(() => import('../assets/icons/ts.svg'))
const VueIcon = defineAsyncComponent(() => import('../assets/icons/vue.svg'))
const HtmlIcon = defineAsyncComponent(() => import('../assets/icons/html.svg'))
const CssIcon = defineAsyncComponent(() => import('../assets/icons/css.svg'))
const JsonIcon = defineAsyncComponent(() => import('../assets/icons/json.svg'))
const PythonIcon = defineAsyncComponent(() => import('../assets/icons/python.svg'))
const DefaultIcon = defineAsyncComponent(() => import('../assets/icons/default.svg'))
const LoadingIcon = defineAsyncComponent(() => import('../assets/icons/default.svg')) // Placeholder for loading

const currentPath = computed(() => (props.parentPath ? `${props.parentPath}/${props.node.name}` : props.node.name))
const isActive = computed(() => props.activePath === currentPath.value)

const loadChildren = async () => {
  if (loading.value) return
  // If children already loaded and not empty, don't reload
  // Wait, if node.children is undefined, it means we haven't tried loading
  // If node.children is [], it means empty dir or loaded.
  // We can't distinguish empty dir from not loaded if initial is []. 
  // Let's assume initial state from parent sets children to undefined if not loaded?
  // But our backend returns children=[] for dirs.
  // So we need a way to track if we fetched.
  // Let's check if children is empty AND expanded. 
  // Actually, let's just fetch if children is empty? No, empty dir loop.
  // We need a local flag `loaded`
}

const isLoaded = ref(false)

const onClick = async () => {
  if (props.node.type === 'dir') {
    if (currentLevel.value < 5) {
      expanded.value = !expanded.value
      
      // Lazy load logic
      if (expanded.value && !isLoaded.value && (!props.node.children || props.node.children.length === 0)) {
        await fetchChildren()
      }
    }
  } else {
    emit('open-file', { path: currentPath.value, type: props.node.type })
  }
}

const fetchChildren = async () => {
  try {
    loading.value = true
    error.value = false
    const res: any = await getProjectStructure(projectId.value, currentPath.value)
    if (res.code === 200 && res.data) {
      // The backend returns a root node containing children
      // We need to update props.node.children
      // Since props are readonly, we need to emit an update or mutate if it's an object reference (Vue reactive)
      // FileNode passed from parent is likely reactive.
      props.node.children = res.data.children || []
      isLoaded.value = true
    }
  } catch (err) {
    console.error('Failed to load children', err)
    error.value = true
  } finally {
    loading.value = false
  }
}

const childKey = (n: FileNode) => `${n.type}-${n.name}`

watch(
  () => props.expandAll,
  (val) => {
    if (props.node.type === 'dir') {
      expanded.value = !!val
      // If expanding all, we might need to load children if not loaded?
      // For recursive expand all, this might trigger mass requests. 
      // Let's limit auto-load on expand-all to avoid flooding, or only expand loaded ones.
      // Or just keep existing behavior (only visual expand).
    }
  },
  { immediate: true }
)

const getIcon = (node: FileNode) => {
  if (loading.value) return LoadingIcon // Or a spinner
  
  if (node.type === 'dir') {
    return expanded.value ? FolderOpenIcon : FolderIcon
  }
  
  const ext = node.name.split('.').pop()?.toLowerCase()
  switch (ext) {
    case 'js': return JsIcon
    case 'ts': return TsIcon
    case 'vue': return VueIcon
    case 'html': return HtmlIcon
    case 'css': return CssIcon
    case 'json': return JsonIcon
    case 'py': return PythonIcon
    default: return DefaultIcon
  }
}
</script>

<style scoped>
.node {
  margin: 0;
  position: relative;
}
.row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.1s;
  position: relative;
}
.row:hover {
  background: #e2e8f0;
}
.row.active {
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px #bfdbfe;
}
.arrow-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 12px;
  height: 12px;
  margin-right: 2px;
}
.arrow {
  width: 16px;
  height: 16px;
  color: #94a3b8;
  transition: transform 0.2s;
  transform: rotate(0deg);
  display: block;
}
.arrow.expanded {
  transform: rotate(90deg);
}
.icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  z-index: 1;
}
.file-icon {
  width: 100%;
  height: 100%;
}
.name {
  font-size: 13px;
  color: #334155;
  line-height: 1.5;
}
.name.dir {
  font-weight: 500;
  color: #0f172a;
}
.error-indicator {
  font-size: 12px;
  margin-left: auto;
}
.children {
  list-style: none;
  padding-left: 24px; /* Increased indent for arrow */
  margin: 0;
  position: relative;
}

/* 连接线样式 */
.children::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 12px; /* Adjusted vertical line position */
  width: 1px;
  background-color: #e2e8f0;
}

.node::before {
  content: '';
  position: absolute;
  top: 12px; /* 水平线起始高度 */
  left: -12px; /* 连接到父级垂直线 */
  width: 12px;
  height: 1px;
  background-color: #e2e8f0;
}

/* 第一层节点不需要左侧连接线 */
.node:first-child::before {
  display: none; /* 仅针对根列表的直接子项有效，但递归组件中每个li都是.node */
}

/* 修正：.node是递归组件内的li，它的位置是相对于ul.children的 */
/* 只有当它位于 .children 内部时才显示水平线 */
.children > .node::before {
  display: block;
}

/* 根节点的ul没有.children类名（在FileTree中是ul.tree），所以第一层不会有线条，符合预期 */

.collapse-enter-active,
.collapse-leave-active {
  transition: all 0.15s ease;
}
.collapse-enter-from,
.collapse-leave-to {
  max-height: 0;
  opacity: 0;
}
.collapse-enter-to,
.collapse-leave-from {
  max-height: 500px;
  opacity: 1;
}
@media (max-width: 768px) {
  .row {
    padding: 6px 8px;
  }
  .name {
    font-size: 12px;
  }
  .icon-wrapper {
    width: 14px;
    height: 14px;
  }
  .children {
    padding-left: 10px;
  }
}
</style>
