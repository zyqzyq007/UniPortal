<template>
  <div class="dashboard-section">
    <div class="section-title">【 测试工程仪表盘 】</div>
    
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div> 加载中...
    </div>

    <div v-else class="dashboard-layout">
      <!-- 1. 总体评分 -->
      <div class="metric-section">
        <div class="metric-card score-card">
          <h4>项目总体质量评分</h4>
          <div class="score-value">{{ formatValue(data?.overallScore, '分') }}</div>
        </div>
      </div>

      <div class="separator"></div>

      <!-- 2. 六维雷达图 -->
      <div class="metric-section">
        <div class="metric-card radar-card">
          <v-chart class="chart" :option="radarOption" autoresize />
        </div>
      </div>

      <div class="separator"></div>

      <!-- 3. 需求与文档健康度 -->
      <div class="metric-section">
        <div class="metric-header">需求与文档健康度</div>
        <div class="charts-row">
          <div class="chart-wrapper">
            <RingChart 
              title="需求覆盖率" 
              :data="{
                total: 100,
                completed: data?.metrics.requirements.coverage || 0,
                passed: data?.metrics.requirements.coverage || 0,
                passRate: data?.metrics.requirements.coverage || 0
              }"
            />
          </div>
          <div class="chart-wrapper">
            <RingChart 
              title="文档健康度" 
              :data="{
                total: 100,
                completed: data?.metrics.requirements.health || 0,
                passed: data?.metrics.requirements.health || 0,
                passRate: data?.metrics.requirements.health || 0
              }"
            />
          </div>
        </div>
      </div>

      <div class="separator"></div>

      <!-- 4. 代码质量 -->
      <div class="metric-section">
        <div class="metric-header">代码质量</div>
        <div class="cards-row">
          <StatCard 
            title="代码缺陷" 
            :value="formatValue(data?.metrics.codeQuality.bugs, '个')" 
            :icon="Bug" 
            color="red" 
          />
          <StatCard 
            title="安全漏洞" 
            :value="formatValue(data?.metrics.codeQuality.vulnerabilities, '个')" 
            :icon="ShieldCheck" 
            color="green" 
          />
          <StatCard 
            title="技术债务" 
            :value="formatValue(data?.metrics.codeQuality.debt, '小时')" 
            :icon="Clock" 
            color="orange" 
          />
        </div>
      </div>

      <div class="separator"></div>

      <!-- 5. 单元测试 -->
      <div class="metric-section">
        <div class="metric-header">单元测试</div>
        <div class="charts-row mixed-row">
          <div class="chart-wrapper">
            <RingChart 
              title="覆盖率" 
              :data="{
                total: 100,
                completed: data?.metrics.unitTest.coverage || 0,
                passed: data?.metrics.unitTest.coverage || 0,
                passRate: data?.metrics.unitTest.coverage || 0
              }"
            />
          </div>
          <div class="chart-wrapper">
            <RingChart 
              title="通过率" 
              :data="{
                total: 100,
                completed: 100,
                passed: data?.metrics.unitTest.passRate || 0,
                passRate: data?.metrics.unitTest.passRate || 0
              }"
            />
          </div>
          <div class="card-wrapper">
            <StatCard 
              title="执行耗时" 
              :value="formatValue(data?.metrics.unitTest.duration, '秒')" 
              :icon="Timer" 
              color="blue" 
            />
          </div>
        </div>
      </div>

      <div class="separator"></div>

      <!-- 6. 集成测试 -->
      <div class="metric-section">
        <div class="metric-header">集成测试</div>
        <div class="charts-row">
          <div class="chart-wrapper">
             <BarChart 
               title="测试用例的维度构成情况" 
               :data="[
                 { name: '功能', value: 40 },
                 { name: '性能', value: 30 },
                 { name: '边界', value: 20 },
                 { name: '接口', value: 50 },
                 { name: '兼容', value: 25 },
                 { name: '稳定性', value: 35 },
                 { name: '可用性', value: 45 },
                 { name: '安全性', value: 15 }
               ]"
             />
          </div>
          <div class="chart-wrapper">
            <RingChart 
              title="软件集成测试用例执行情况" 
              :data="{
                total: 1000,
                completed: 850,
                passed: 800,
                passRate: 94.1
              }"
              :icon="Code"
            />
          </div>
          <div class="chart-wrapper">
            <RingChart 
              title="软/硬件集成测试用例执行情况" 
              :data="{
                total: 500,
                completed: 480,
                passed: 470,
                passRate: 97.9
              }"
              :icon="ShieldCheck"
            />
          </div>
        </div>
        
        <div class="separator-dashed"></div>

        <!-- Stats Cards Row -->
        <div class="cards-row">
          <StatCard 
            title="测试文件数" 
            value="45" 
            :icon="FileText" 
            color="blue" 
          />
          <StatCard 
            title="总用例数" 
            value="1500" 
            :icon="Grid" 
            color="cyan" 
          />
          <StatCard 
            title="当前失败用例数" 
            value="15" 
            :icon="AlertCircle" 
            color="red" 
          />
          <StatCard 
            title="已修复失败用例数" 
            value="120" 
            :icon="CheckCircle" 
            color="green" 
          />
          <StatCard 
            title="当前失效用例数" 
            value="8" 
            :icon="Clock" 
            color="orange" 
          />
          <StatCard 
            title="已修复失效用例数" 
            value="5" 
            :icon="ShieldCheck" 
            color="green" 
          />
        </div>

        <div class="separator-dashed"></div>

        <!-- Trend Section -->
        <div class="chart-wrapper wide" style="height: 300px;">
           <LineChart 
             title="测试执行趋势分析" 
             :data="[
               { date: '2023-10-01', passed: 120, failed: 20 },
               { date: '2023-10-02', passed: 132, failed: 18 },
               { date: '2023-10-03', passed: 101, failed: 19 },
               { date: '2023-10-04', passed: 134, failed: 23 },
               { date: '2023-10-05', passed: 90, failed: 29 },
               { date: '2023-10-06', passed: 230, failed: 33 },
               { date: '2023-10-07', passed: 210, failed: 31 }
             ]" 
           />
        </div>
      </div>

      <div class="separator"></div>

      <!-- 7. 代码缺陷修复 -->
      <div class="metric-section">
        <div class="metric-header">代码缺陷修复</div>
        <div class="charts-row mixed-row">
          <div class="chart-wrapper wide">
            <BarChart 
              title="缺陷状态分布" 
              :data="[
                { name: '待修复', value: data?.metrics.defect.open || 0 },
                { name: '已修复', value: data?.metrics.defect.closed || 0 }
              ]"
            />
          </div>
          <div class="card-wrapper">
            <StatCard 
              title="平均修复时间" 
              :value="formatValue(data?.metrics.defect.avgCloseTime, '天')" 
              :icon="Activity" 
              color="cyan" 
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { RadarChart } from 'echarts/charts';
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import VChart from 'vue-echarts';
import type { DashboardData } from '../mock/dashboard';
import RingChart from './charts/RingChart.vue';
import BarChart from './charts/BarChart.vue';
import LineChart from './charts/LineChart.vue';
import StatCard from './dashboard/StatCard.vue';
import { 
  Activity,
  AlertCircle,
  Bug,
  CheckCircle,
  Clock,
  Code,
  FileText,
  Grid,
  ShieldCheck,
  Timer
} from 'lucide-vue-next';

// 注册 ECharts 组件
use([CanvasRenderer, RadarChart, TitleComponent, TooltipComponent, LegendComponent]);

const props = defineProps<{
  data: DashboardData | null;
  loading: boolean;
}>();

// 格式化数值工具函数
const formatValue = (value: number | null | undefined, unit: string) => {
  if (value === null || value === undefined) return '- -';
  if (unit === '%') return `${value}%`;
  if (unit === '小时/天' || unit === '天' || unit === '小时') {
     return `${Number.isInteger(value) ? value : value.toFixed(1)} ${unit}`;
  }
  return `${value} ${unit}`;
};

const radarOption = computed(() => {
  const values = props.data?.radarData || [0, 0, 0, 0, 0, 0];
  const isEmpty = !props.data || !props.data.radarData || props.data.radarData.length === 0;

  return {
    tooltip: {},
    radar: {
      indicator: [
        { name: '需求与文档健康度', max: 100 },
        { name: '代码质量', max: 100 },
        { name: '单元测试', max: 100 },
        { name: '集成测试', max: 100 },
        { name: '缺陷闭环', max: 100 },
        { name: '安全质量', max: 100 }
      ],
      radius: '65%',
      center: ['50%', '50%']
    },
    series: [
      {
        name: '工程质量维度',
        type: 'radar',
        data: [
          {
            value: isEmpty ? [0, 0, 0, 0, 0, 0] : values,
            name: '当前工程'
          }
        ],
        itemStyle: {
           color: '#5470c6'
        },
        areaStyle: {
          opacity: 0.2
        }
      }
    ]
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

.separator-dashed {
  height: 1px;
  background-color: transparent;
  border-top: 1px dashed #e2e8f0;
  margin: 24px 0;
  width: 100%;
}

.metric-card {
  width: 100%; 
  padding: 0 16px;
  box-sizing: border-box;
}

.score-card {
  text-align: center;
  display: flex;
  flex-direction: column;
  justify-content: center;
  
  .score-value {
    font-size: 36px;
    font-weight: bold;
    color: #3b82f6;
  }
  
  h4 {
    font-size: 14px;
    color: #64748b;
    margin: 0 0 12px 0;
    font-weight: 500;
  }
}

.radar-card {
  /* 移除 flex: 2 */
  width: 100%;
  height: 260px;
  display: flex;
  justify-content: center;
  align-items: center;
}

.chart {
  width: 100%;
  height: 100%;
  min-height: 240px;
}

/* New Layout Styles */
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
  justify-content: center; /* Center card vertically if row is tall */
}

.wide {
  flex: 2; /* Take more space */
  min-width: 400px;
}

/* Adjust StatCard inside wrapper */
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
