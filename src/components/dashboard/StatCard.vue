<template>
  <div class="stat-card">
    <div class="stat-icon" :class="colorClass">
      <component :is="icon" v-if="icon" />
    </div>
    <div class="stat-content">
      <div class="label">{{ title }}</div>
      <div class="value">{{ value }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  title: string;
  value: number | string;
  icon: any;
  color: 'blue' | 'cyan' | 'red' | 'green' | 'yellow' | 'orange';
}>();

const colorClass = computed(() => `bg-${props.color}`);
</script>

<style scoped>
.stat-card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 16px;
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-icon svg {
  width: 24px;
  height: 24px;
}

.stat-content {
  flex: 1;
}

.label {
  font-size: 13px;
  color: #6b7280;
  margin-bottom: 4px;
}

.value {
  font-size: 20px;
  font-weight: 600;
  color: #1f2937;
}

/* Color variants */
.bg-blue { background: #eff6ff; color: #3b82f6; }
.bg-cyan { background: #ecfeff; color: #06b6d4; }
.bg-red { background: #fef2f2; color: #ef4444; }
.bg-green { background: #f0fdf4; color: #22c55e; }
.bg-yellow { background: #fefce8; color: #eab308; }
.bg-orange { background: #fff7ed; color: #f97316; }
</style>
