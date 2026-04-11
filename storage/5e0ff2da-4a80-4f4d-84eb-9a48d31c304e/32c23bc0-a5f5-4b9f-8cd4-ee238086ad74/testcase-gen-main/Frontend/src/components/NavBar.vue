<template>
  <nav class="bg-white border-b border-slate-200 px-6 py-4">
    <div class="max-w-7xl mx-auto flex items-center justify-between">
      <div class="flex items-center space-x-2">
        <div class="w-8 h-8 bg-primary-900 rounded flex items-center justify-center">
          <span class="font-bold text-white">C</span>
        </div>
        <span class="text-lg font-bold tracking-tight text-slate-900">Unit Test Gen</span>
      </div>

      <div class="flex items-center space-x-4">
        <template v-for="(step, index) in steps" :key="step.path">
          <div class="flex items-center">
            <!-- Connector -->
            <div v-if="index > 0" class="h-px w-8 mx-2" :class="getConnectorClass(index)"></div>
            
            <!-- Step Item -->
            <router-link 
              :to="step.path"
              :class="getStepClass(index)"
              @click.prevent="handleStepClick(index, step.path)"
              class="flex items-center space-x-2 px-3 py-1.5 rounded-full transition-all duration-200"
            >
              <div class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold" :class="getIconClass(index)">
                <component :is="getIcon(index)" class="w-4 h-4" v-if="isCompleted(index)" />
                <span v-else>{{ index + 1 }}</span>
              </div>
              <span class="text-sm font-semibold">{{ step.name }}</span>
            </router-link>
          </div>
        </template>
      </div>

      <div class="flex items-center space-x-4 text-xs text-slate-500">
        <div v-if="store.projectName" class="flex items-center bg-slate-100 px-3 py-1 rounded-full">
          <span class="opacity-60 mr-2 font-medium">Project:</span>
          <span class="text-slate-900 font-semibold">{{ store.projectName }}</span>
        </div>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '../store'
import { Check, Upload, FolderTree, Zap, BarChart3, LayoutDashboard } from 'lucide-vue-next'

const store = useAppStore()
const route = useRoute()
const router = useRouter()

const steps = [
  { name: '项目上传', path: '/', icon: Upload },
  { name: '总览看板', path: '/dashboard', icon: LayoutDashboard },
  { name: '项目浏览', path: '/browse', icon: FolderTree },
  { name: '测试生成', path: '/generate', icon: Zap },
  { name: '执行结果', path: '/result', icon: BarChart3 },
]

const currentStepIndex = computed(() => {
  const path = route.path
  if (path === '/') return 0
  if (path === '/dashboard') return 1
  if (path === '/browse') return 2
  if (path === '/generate') return 3
  if (path === '/result') return 4
  return 0
})

const isCompleted = (index) => {
  if (index === 0) return store.projectId !== null && currentStepIndex.value > 0
  if (index === 1) return store.projectId !== null && currentStepIndex.value > 1
  if (index === 2) return store.functionId !== null && currentStepIndex.value > 2
  if (index === 3) return store.taskId !== null && currentStepIndex.value > 3
  if (index === 4) return currentStepIndex.value > 4
  return false
}

const isActive = (index) => currentStepIndex.value === index

const isDisabled = (index) => {
  if (index === 0) return false
  if (index === 1) return store.projectId === null
  if (index === 2) return store.functionId === null
  if (index === 3) return store.taskId === null
  return true
}

const getStepClass = (index) => {
  if (isActive(index)) return 'bg-primary-900 text-white shadow-md'
  if (isCompleted(index)) return 'text-green-600 hover:bg-green-50'
  if (isDisabled(index)) return 'text-slate-300 cursor-not-allowed'
  return 'text-slate-600 hover:bg-slate-100'
}

const getIconClass = (index) => {
  if (isActive(index)) return 'bg-white text-primary-900'
  if (isCompleted(index)) return 'bg-green-500 text-white'
  if (isDisabled(index)) return 'bg-slate-100 text-slate-300'
  return 'bg-slate-200 text-slate-600'
}

const getConnectorClass = (index) => {
  if (index <= currentStepIndex.value) return 'bg-primary-900'
  return 'bg-slate-200'
}

const getIcon = (index) => Check

const handleStepClick = (index, path) => {
  if (!isDisabled(index)) {
    router.push(path)
  }
}
</script>
