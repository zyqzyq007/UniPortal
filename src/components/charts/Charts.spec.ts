import { mount } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import BarChart from './BarChart.vue'
import RingChart from './RingChart.vue'
import LineChart from './LineChart.vue'
import { Code as CodeIcon } from 'lucide-vue-next'

// Mock vue-echarts to avoid canvas errors
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

describe('Chart Components', () => {
  describe('BarChart.vue', () => {
    it('renders correctly with data', () => {
      const wrapper = mount(BarChart, {
        props: {
          title: 'Test Bar Chart',
          data: [{ name: 'A', value: 10 }, { name: 'B', value: 20 }]
        }
      })
      expect(wrapper.find('h3').text()).toBe('Test Bar Chart')
      expect(wrapper.find('.chart').exists()).toBe(true)
    })
  })

  describe('RingChart.vue', () => {
    it('renders correctly with data', () => {
      const wrapper = mount(RingChart, {
        props: {
          title: 'Test Ring Chart',
          data: {
            total: 100,
            completed: 80,
            passed: 75,
            passRate: 93.75
          },
          icon: CodeIcon
        }
      })
      expect(wrapper.find('h3').text()).toContain('Test Ring Chart')
      expect(wrapper.find('.percentage').text()).toBe('93.75%')
      expect(wrapper.find('.label').text()).toBe('通过率')
      expect(wrapper.text()).toContain('总: 100')
      expect(wrapper.text()).toContain('完成: 80')
      expect(wrapper.text()).toContain('正确: 75')
    })
  })

  describe('LineChart.vue', () => {
    it('renders correctly with data', () => {
      const wrapper = mount(LineChart, {
        props: {
          title: 'Test Line Chart',
          data: [
            { date: '2023-01-01', failed: 5, passed: 10 },
            { date: '2023-01-02', failed: 3, passed: 15 }
          ]
        }
      })
      expect(wrapper.find('h3').text()).toBe('Test Line Chart')
      expect(wrapper.find('.chart').exists()).toBe(true)
    })
  })
})
