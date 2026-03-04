<template>
  <div class="chart-container">
    <div class="chart-header">
      <h3>{{ title }}</h3>
    </div>
    <div class="chart-content">
      <v-chart class="chart" :option="option" autoresize />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { LineChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent
} from 'echarts/components';
import VChart from 'vue-echarts';

use([
  CanvasRenderer,
  LineChart,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent
]);

const props = defineProps<{
  title: string;
  data: { date: string; failed: number; passed: number }[];
}>();

const option = computed(() => ({
  tooltip: {
    trigger: 'axis'
  },
  legend: {
    data: ['通过用例', '失败用例'],
    bottom: 0
  },
  grid: {
    left: '3%',
    right: '4%',
    bottom: '10%',
    top: '10%',
    containLabel: true
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: props.data.map(item => item.date),
    axisLine: {
      lineStyle: {
        color: '#e5e7eb'
      }
    },
    axisLabel: {
      color: '#6b7280'
    }
  },
  yAxis: {
    type: 'value',
    splitLine: {
      lineStyle: {
        type: 'dashed',
        color: '#f3f4f6'
      }
    }
  },
  series: [
    {
      name: '通过用例',
      type: 'line',
      data: props.data.map(item => item.passed),
      smooth: true,
      itemStyle: { color: '#91cc75' },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: 'rgba(145, 204, 117, 0.5)' }, { offset: 1, color: 'rgba(145, 204, 117, 0.1)' }]
        }
      }
    },
    {
      name: '失败用例',
      type: 'line',
      data: props.data.map(item => item.failed),
      smooth: true,
      itemStyle: { color: '#ee6666' },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: 'rgba(238, 102, 102, 0.5)' }, { offset: 1, color: 'rgba(238, 102, 102, 0.1)' }]
        }
      }
    }
  ]
}));
</script>

<style scoped>
.chart-container {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.chart-header h3 {
  font-size: 14px;
  font-weight: 500;
  color: #374151;
  margin: 0 0 12px 0;
}

.chart-content {
  flex: 1;
  min-height: 0; /* Important for flex child to shrink/grow correctly */
  position: relative;
}

.chart {
  width: 100%;
  height: 100%;
  min-height: 200px; /* Ensure minimum height */
}
</style>
