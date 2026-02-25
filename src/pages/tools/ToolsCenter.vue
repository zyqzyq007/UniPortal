<template>
  <div class="container">
    <div class="page-title">
      <h2>工具中心</h2>
    </div>
    <div class="card-grid">
      <div class="card" v-for="tool in toolsList" :key="tool.key">
        <h3>{{ tool.name }}</h3>
        <p>{{ tool.description }}</p>
        <a class="btn" :href="tool.targetUrl" target="_blank" rel="noopener noreferrer">
          进入工具
        </a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { tools } from '../../mock/data'

const toolsList = tools
</script>

<style scoped>
.page-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 24px;
}

.card {
  background: white;
  padding: 24px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  transition: all 0.2s;
}

.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
  border-color: #cbd5e1;
}

.card h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  color: #1e293b;
}

.card p {
  margin: 0 0 20px 0;
  color: #64748b;
  font-size: 14px;
  flex: 1;
  line-height: 1.5;
}

.btn {
  align-self: flex-start;
  padding: 8px 16px;
  background: #3b82f6;
  color: white;
  border-radius: 6px;
  text-decoration: none;
  font-size: 14px;
  transition: background 0.2s;
}

.btn:hover {
  background: #2563eb;
}
</style>
