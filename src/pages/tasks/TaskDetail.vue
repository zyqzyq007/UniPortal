<template>
  <div class="container" v-if="task">
    <div class="page-title">
      <h2>任务详情</h2>
      <RouterLink class="btn btn-light" :to="`/projects/${projectId}/tasks`">返回任务中心</RouterLink>
    </div>
    <div class="card detail">
      <div class="info">
        <div>
          <strong>任务 ID：</strong>
          <span>{{ task.id }}</span>
        </div>
        <div>
          <strong>工具类型：</strong>
          <span>{{ task.toolName }}</span>
        </div>
        <div>
          <strong>项目名称：</strong>
          <span>{{ task.projectName }}</span>
        </div>
        <div>
          <strong>状态：</strong>
          <span class="status" :class="statusClass(task.status)">
            {{ statusLabel(task.status) }}
          </span>
        </div>
        <div>
          <strong>创建时间：</strong>
          <span>{{ formatTime(task.createdAt) }}</span>
        </div>
      </div>
      <div class="actions">
        <RouterLink class="btn" :to="`/projects/${projectId}/results/${task.id}`">查看结果</RouterLink>
        <a class="btn btn-light" :href="mockDownloadUrl" download>下载报告</a>
      </div>
      <div class="error" v-if="task.errorMessage">
        <strong>失败信息：</strong>
        <span>{{ task.errorMessage }}</span>
      </div>
    </div>
    <div class="card">
      <h3>任务参数</h3>
      <ul>
        <li v-for="(value, key) in task.params" :key="key">
          <strong>{{ key }}：</strong>{{ value || '未填写' }}
        </li>
      </ul>
    </div>
  </div>
  <div class="container" v-else>
    <div class="card">
      <p>未找到任务信息，请返回任务中心重新选择。</p>
      <RouterLink class="btn" :to="`/projects/${projectId}/tasks`">返回任务中心</RouterLink>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { getTaskById } from '../../store/mockStore'
import type { TaskItem } from '../../store/mockStore'

const route = useRoute()
const projectId = computed(() => route.params.projectId as string)
const taskId = computed(() => route.params.taskId as string)
const task = computed(() => getTaskById(taskId.value))
const mockDownloadUrl = 'https://example.com/report.pdf'

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

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.info {
  display: grid;
  gap: 8px;
}

.actions {
  display: flex;
  gap: 12px;
}

.error {
  color: #b91c1c;
  font-weight: 600;
}

ul {
  padding-left: 18px;
}
</style>
