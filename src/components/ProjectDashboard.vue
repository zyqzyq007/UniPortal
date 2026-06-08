<template>
  <div class="dashboard-section">
    <div class="section-title">【 工程资产概览 】</div>

    <div v-if="loading" class="loading-state">
      <div class="spinner"></div> 加载中...
    </div>

    <div v-else-if="!data || data.files.total === 0" class="loading-state">
      该工程暂无可统计的文件（请先上传软件项目）
    </div>

    <div v-else class="dashboard-layout">
      <!-- 0. 资产总览 -->
      <div class="metric-section">
        <div class="metric-header">资产总览</div>
        <div class="cards-row">
          <StatCard title="软件条目数" :value="data.itemCount" :icon="Grid" color="cyan" />
          <StatCard title="代码文件" :value="data.files.source + data.files.header" :icon="Code" color="blue" />
          <StatCard title="文档文件" :value="data.docs.total" :icon="FileText" color="orange" />
          <StatCard title="需求条目" :value="data.requirements.items + data.requirements.reqFiles" :icon="CheckCircle" color="green" />
        </div>
      </div>

      <div class="separator"></div>

      <!-- 1. 代码规模 -->
      <div class="metric-section">
        <div class="metric-header">代码规模</div>
        <div class="cards-row">
          <StatCard title="源文件 (.c/.cpp)" :value="data.files.source" :icon="Code" color="blue" />
          <StatCard title="头文件 (.h)" :value="data.files.header" :icon="FileText" color="blue" />
          <StatCard title="代码总行数" :value="data.lines.total" :icon="Activity" color="green" />
          <StatCard title="函数总数" :value="data.functions.count" :icon="ShieldCheck" color="orange" />
        </div>
      </div>

      <div class="separator"></div>

      <!-- 2. 代码构成 + 注释率 -->
      <div class="metric-section">
        <div class="metric-header">代码构成（有效代码 / 注释 / 空行）</div>
        <div class="charts-row">
          <div class="chart-wrapper">
            <v-chart class="chart" :option="codeCompositionOption" autoresize />
          </div>
          <div class="card-wrapper">
            <StatCard title="注释率" :value="data.commentRatio + '%'" :icon="CheckCircle" color="green" />
            <StatCard title="平均函数行数" :value="data.functions.avgLines" :icon="Timer" color="blue" style="margin-top:16px;" />
          </div>
        </div>
      </div>

      <!-- 3. 需求与文档 (仅当存在文档/需求时显示) -->
      <template v-if="hasReqOrDoc">
        <div class="separator"></div>
        <div class="metric-section">
          <div class="metric-header">需求与文档</div>
          <div class="cards-row">
            <StatCard title="需求规格文档" :value="data.docs.spec" :icon="FileText" color="orange" />
            <StatCard title="结构化需求条目" :value="data.requirements.items" :icon="Grid" color="cyan" />
            <StatCard title="需求条目文件" :value="data.requirements.reqFiles" :icon="AlertCircle" color="blue" />
          </div>
          <template v-if="data.requirements.types.length">
            <div class="metric-header" style="margin-top:16px;">需求类型分布</div>
            <div class="chart-wrapper wide" style="height: 260px;">
              <v-chart class="chart" :option="reqTypeOption" autoresize />
            </div>
          </template>
        </div>
      </template>

      <div class="separator"></div>

      <!-- 4. 文件类型分布 -->
      <div class="metric-section">
        <div class="metric-header">文件类型分布</div>
        <div class="chart-wrapper wide" style="height: 280px;">
          <v-chart class="chart" :option="fileTypeOption" autoresize />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { PieChart } from 'echarts/charts';
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import VChart from 'vue-echarts';
import type { CodeStats } from '../api/projects';
import StatCard from './dashboard/StatCard.vue';
import { Activity, AlertCircle, CheckCircle, Code, FileText, Grid, ShieldCheck, Timer } from 'lucide-vue-next';

// 注册 ECharts 组件 (饼图)
use([CanvasRenderer, PieChart, TitleComponent, TooltipComponent, LegendComponent]);

const props = defineProps<{
  data: CodeStats | null;
  loading: boolean;
}>();

// 是否存在需求/文档资产 (决定"需求与文档"板块是否显示)
const hasReqOrDoc = computed(() => {
  const d = props.data;
  if (!d) return false;
  return d.docs.total > 0 || d.requirements.items > 0 || d.requirements.reqFiles > 0;
});

const FILE_PALETTE = ['#3b82f6', '#22c55e', '#f59e0b', '#8b5cf6', '#06b6d4', '#ef4444', '#ec4899', '#94a3b8'];

// 代码构成饼图: 有效代码 / 注释 / 空行
const codeCompositionOption = computed(() => {
  const l = props.data?.lines || { total: 0, code: 0, comment: 0, blank: 0 };
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 行 ({d}%)' },
    legend: { bottom: 0 },
    series: [{
      name: '代码构成',
      type: 'pie',
      radius: ['40%', '65%'],
      center: ['50%', '42%'],
      avoidLabelOverlap: false,
      label: { show: false },
      labelLine: { show: false },
      data: [
        { value: l.code, name: '有效代码', itemStyle: { color: '#3b82f6' } },
        { value: l.comment, name: '注释', itemStyle: { color: '#22c55e' } },
        { value: l.blank, name: '空行', itemStyle: { color: '#cbd5e1' } },
      ],
    }],
  };
});

// 文件类型分布饼图
const fileTypeOption = computed(() => {
  const types = props.data?.fileTypes || [];
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 个 ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [{
      name: '文件类型',
      type: 'pie',
      radius: '62%',
      center: ['50%', '45%'],
      data: types.map((t, i) => ({
        value: t.value,
        name: t.name,
        itemStyle: { color: FILE_PALETTE[i % FILE_PALETTE.length] },
      })),
    }],
  };
});

// 需求类型分布饼图 (功能需求 / 性能需求 / 余量需求 ...)
const reqTypeOption = computed(() => {
  const types = props.data?.requirements?.types || [];
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条 ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [{
      name: '需求类型',
      type: 'pie',
      radius: ['35%', '62%'],
      center: ['50%', '45%'],
      data: types.map((t, i) => ({
        value: t.value,
        name: t.name,
        itemStyle: { color: FILE_PALETTE[i % FILE_PALETTE.length] },
      })),
    }],
  };
});
</script>

<style scoped lang="scss">
.dashboard-section {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  margin-top: 24px;
  margin-bottom: 24px;
  border: 1px solid #e2e8f0;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 20px;
}

.loading-state {
  text-align: center;
  padding: 40px;
  color: #64748b;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 10px;

  .spinner {
    width: 20px;
    height: 20px;
    border: 2px solid #e2e8f0;
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.dashboard-layout {
  display: flex;
  flex-direction: column;
}

.metric-section {
  display: flex;
  flex-direction: column;
  padding: 10px 0;
}

.metric-header {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 12px;
  font-weight: 500;
}

.separator {
  height: 1px;
  background-color: #e2e8f0;
  margin: 24px 0;
  width: 100%;
}

.chart {
  width: 100%;
  height: 100%;
  min-height: 240px;
}

.charts-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.cards-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 12px;
}

.chart-wrapper {
  flex: 1;
  min-width: 280px;
  height: 248px;
}

.card-wrapper {
  flex: 1;
  min-width: 200px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.wide {
  flex: 2;
  min-width: 400px;
}

.card-wrapper :deep(.stat-card) {
  height: 100%;
  box-sizing: border-box;
}

@media (max-width: 768px) {
  .charts-row, .cards-row {
    flex-direction: column;
    grid-template-columns: 1fr;
  }

  .wide {
    min-width: 100%;
  }
}
</style>
