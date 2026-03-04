<template>
  <div class="chart-container">
    <div class="chart-header">
      <h3>
        <component :is="icon" v-if="icon" class="title-icon" />
        {{ title }}
      </h3>
    </div>
    <div class="chart-content">
      <v-chart class="chart" :option="option" autoresize />
      <div class="center-text">
        <div class="percentage">{{ data.passRate }}%</div>
        <div class="label">通过率</div>
      </div>
    </div>
    <div class="legend">
      <div class="legend-item">
        <span class="dot bg-blue"></span>
        <span>总: {{ data.total }}</span>
      </div>
      <div class="legend-item">
        <span class="dot bg-yellow"></span>
        <span>完成: {{ data.completed }}</span>
      </div>
      <div class="legend-item">
        <span class="dot bg-green"></span>
        <span>正确: {{ data.passed }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { PieChart } from 'echarts/charts';
import {
  TooltipComponent,
  TitleComponent
} from 'echarts/components';
import VChart from 'vue-echarts';

use([
  CanvasRenderer,
  PieChart,
  TooltipComponent,
  TitleComponent
]);

const props = defineProps<{
  title: string;
  icon?: any;
  data: {
    total: number;
    completed: number;
    passed: number;
    passRate: number;
  };
}>();

const option = computed(() => ({
  tooltip: {
    trigger: 'item'
  },
  series: [
    {
      name: '执行情况',
      type: 'pie',
      radius: ['60%', '75%'],
      avoidLabelOverlap: false,
      itemStyle: {
        borderRadius: 10,
        borderColor: '#fff',
        borderWidth: 2
      },
      label: {
        show: false,
        position: 'center'
      },
      emphasis: {
        label: {
          show: false
        }
      },
      labelLine: {
        show: false
      },
      data: [
        { value: props.data.passed, name: '正确', itemStyle: { color: '#91cc75' } },
        { value: props.data.completed - props.data.passed, name: '完成(未通过)', itemStyle: { color: '#fac858' } },
        { value: props.data.total - props.data.completed, name: '未完成', itemStyle: { color: '#e5e7eb' } }
      ]
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
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-icon {
  width: 16px;
  height: 16px;
}

.chart-content {
  position: relative;
  flex: 1;
  min-height: 148px;
}

.chart {
  height: 100%;
}

.center-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  pointer-events: none;
}

.percentage {
  font-size: 24px;
  font-weight: bold;
  color: #1f2937;
}

.label {
  font-size: 12px;
  color: #9ca3af;
}

.legend {
  display: flex;
  justify-content: center;
  gap: 16px;
  margin-top: 4px;
  padding-bottom: 2px;
  font-size: 12px;
  color: #6b7280;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.bg-blue { background-color: #5470c6; } /* Not used in pie data but requested in legend text "Total"? Actually pie logic above is "Correct", "Completed(Fail)", "Unfinished". The legend asks for "Total", "Completed", "Correct". The colors in legend dots should probably match standard or chart. Let's make "Total" blue, "Completed" yellow, "Correct" green. */
.bg-yellow { background-color: #fac858; }
.bg-green { background-color: #91cc75; }
</style>
