<template>
  <div class="chart-container">
    <div class="chart-header">
      <h3>{{ title }}</h3>
    </div>
    <v-chart class="chart" :option="option" autoresize />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { BarChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  TitleComponent
} from 'echarts/components';
import VChart, { THEME_KEY } from 'vue-echarts';

use([
  CanvasRenderer,
  BarChart,
  GridComponent,
  TooltipComponent,
  TitleComponent
]);

const props = defineProps<{
  title: string;
  data: { name: string; value: number }[];
}>();

const option = computed(() => ({
  tooltip: {
    trigger: 'axis',
    axisPointer: {
      type: 'shadow'
    }
  },
  grid: {
    left: '3%',
    right: '4%',
    bottom: '3%',
    containLabel: true
  },
  xAxis: {
    type: 'category',
    data: props.data.map(item => item.name),
    axisTick: {
      alignWithLabel: true
    },
    axisLabel: {
      color: '#9ca3af', // gray-400
      fontSize: 10,
      interval: 0
    },
    axisLine: {
      lineStyle: {
        color: '#e5e7eb' // gray-200
      }
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
      name: 'Count',
      type: 'bar',
      barWidth: '40%',
      data: props.data.map(item => item.value),
      itemStyle: {
        color: '#5470c6',
        borderRadius: [4, 4, 0, 0]
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

.chart {
  height: 200px; /* Default height */
  flex: 1;
}
</style>
