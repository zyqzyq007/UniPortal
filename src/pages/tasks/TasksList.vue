<template>
  <div class="container">
    <div class="page-title">
      <h2>任务中心</h2>
      <RouterLink class="btn" :to="`/projects/${projectId}/tools`">创建新任务</RouterLink>
    </div>
    <table class="table" v-if="tasks.length">
      <thead>
        <tr>
          <th>任务 ID</th>
          <th>工具类型</th>
          <th>项目名称</th>
          <th>状态</th>
          <th>创建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in tasks" :key="task.id">
          <td>{{ task.id }}</td>
          <td>{{ task.toolName }}</td>
          <td>{{ task.projectName }}</td>
          <td>
            <span class="status" :class="statusClass(task.status)">
              {{ statusLabel(task.status) }}
            </span>
          </td>
          <td>{{ formatTime(task.createdAt) }}</td>
          <td>
            <RouterLink class="link-btn" :to="`/projects/${projectId}/tasks/${task.id}`">查看详情</RouterLink>
          </td>
        </tr>
      </tbody>
    </table>
    <div class="card" v-else>
      <p>当前项目暂无任务，请从工具中心创建任务。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getTasksByProject } from '../../store/mockStore'
import type { TaskItem } from '../../store/mockStore'

const route = useRoute()
const projectId = computed(() => route.params.projectId as string)
const tasks = ref<TaskItem[]>([])

const loadTasks = () => {
  tasks.value = getTasksByProject(projectId.value)
}

onMounted(loadTasks)

const statusLabel = (status: TaskItem['status']) => {
  if (status === 'RUNNING') return '执行中'
  if (status === 'SUCCEEDED') return '成功'
  return '失败'
}

const statusClass = (status: TaskItem['status']) => {
  if (status === 'RUNNING') return 'running'
  if (status === 'SUCCEEDED') return 'succeeded'
  return 'failed'
}

const formatTime = (time: string) => new Date(time).toLocaleString()
</script>
