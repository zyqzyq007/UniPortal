<template>
  <div class="container">
    <div class="page-title">
      <h2>结果查看</h2>
      <RouterLink class="btn btn-light" :to="`/projects/${projectId}/tasks/${taskId}`">
        返回任务详情
      </RouterLink>
    </div>
    <div class="card">
      <div v-if="resultUrl">
        <iframe class="result-frame" :src="resultUrl" title="结果预览" />
      </div>
      <div v-else>
        <p>暂无结果预览链接，可返回任务详情下载报告。</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { getTaskById } from '../../store/mockStore'

const route = useRoute()
const projectId = computed(() => route.params.projectId as string)
const taskId = computed(() => route.params.taskId as string)
const task = computed(() => getTaskById(taskId.value))
const resultUrl = computed(() => task.value ? 'https://example.com/result' : '')
</script>

<style scoped>
.result-frame {
  width: 100%;
  height: 520px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}
</style>
