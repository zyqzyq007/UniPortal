import { mount } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import ProjectDashboard from './ProjectDashboard.vue'
import { mockDashboardData, emptyDashboardData } from '../mock/dashboard'
import RingChart from './charts/RingChart.vue'
import BarChart from './charts/BarChart.vue'
import StatCard from './dashboard/StatCard.vue'

// Mock vue-echarts
vi.mock('vue-echarts', () => ({
  default: { name: 'v-chart', template: '<div class="echarts-mock"></div>' },
  THEME_KEY: 'echarts-theme'
}))

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

describe('ProjectDashboard.vue', () => {
  it('renders loading state correctly', () => {
    const wrapper = mount(ProjectDashboard, {
      props: {
        data: null,
        loading: true
      }
    })
    expect(wrapper.find('.loading-state').exists()).toBe(true)
    expect(wrapper.text()).toContain('加载中')
  })

  it('renders normal data correctly', () => {
    const wrapper = mount(ProjectDashboard, {
      props: {
        data: mockDashboardData,
        loading: false
      }
    })
    
    expect(wrapper.find('.loading-state').exists()).toBe(false)
    expect(wrapper.find('.section-title').text()).toBe('【 测试工程仪表盘 】')
    
    // Check score
    expect(wrapper.find('.score-value').text()).toBe('85.5 分')
    
    // Check Requirement Coverage (RingChart)
    const ringCharts = wrapper.findAllComponents(RingChart)
    expect(ringCharts.length).toBeGreaterThan(0)
    // Find the one with title "需求覆盖率"
    const reqChart = ringCharts.find(c => c.props('title') === '需求覆盖率')
    expect(reqChart).toBeDefined()
    expect(reqChart?.props('data').passRate).toBe(92.5)

    // Check Code Defects (StatCard)
    const statCards = wrapper.findAllComponents(StatCard)
    const bugCard = statCards.find(c => c.props('title') === '代码缺陷')
    expect(bugCard).toBeDefined()
    expect(bugCard?.props('value')).toBe('12 个')

    // Check Defect Distribution (BarChart)
    const barCharts = wrapper.findAllComponents(BarChart)
    const defectChart = barCharts.find(c => c.props('title') === '缺陷状态分布')
    expect(defectChart).toBeDefined()
    expect(defectChart?.props('data')).toEqual([
      { name: '待修复', value: 5 },
      { name: '已修复', value: 120 }
    ])

    // Check Integration Test Dashboard content
    const integrationBarChart = barCharts.find(c => c.props('title') === '测试用例的维度构成情况')
    expect(integrationBarChart).toBeDefined()
    expect(integrationBarChart?.props('data')).toHaveLength(8)
    
    const integrationRingChart = ringCharts.find(c => c.props('title') === '软件集成测试用例执行情况')
    expect(integrationRingChart).toBeDefined()
    expect(integrationRingChart?.props('data').passRate).toBe(94.1)
  })

  it('renders empty data with placeholders', () => {
    const wrapper = mount(ProjectDashboard, {
      props: {
        data: emptyDashboardData,
        loading: false
      }
    })
    
    expect(wrapper.find('.score-value').text()).toBe('- -')
    
    // Check RingChart placeholders
    const ringCharts = wrapper.findAllComponents(RingChart)
    const reqChart = ringCharts.find(c => c.props('title') === '需求覆盖率')
    expect(reqChart?.props('data').passRate).toBe(0) // Default 0 if null/empty
    
    // Check StatCard placeholders
    const statCards = wrapper.findAllComponents(StatCard)
    const bugCard = statCards.find(c => c.props('title') === '代码缺陷')
    expect(bugCard?.props('value')).toBe('- -') // formatValue handles null -> '- -' without unit
  })

  it('renders null data (timeout/error) with placeholders', () => {
    const wrapper = mount(ProjectDashboard, {
      props: {
        data: null,
        loading: false
      }
    })
    
    expect(wrapper.find('.score-value').text()).toBe('- -')
    
    // Check components receive safe defaults or formatted placeholders
    const ringCharts = wrapper.findAllComponents(RingChart)
    const reqChart = ringCharts.find(c => c.props('title') === '需求覆盖率')
    // In template: data?.metrics.requirements.coverage || 0
    expect(reqChart?.props('data').passRate).toBe(0)

    const statCards = wrapper.findAllComponents(StatCard)
    const bugCard = statCards.find(c => c.props('title') === '代码缺陷')
    expect(bugCard?.props('value')).toBe('- -')
  })
})
