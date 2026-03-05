# Chart Component Library

This project includes a set of reusable Vue 3 chart components built on top of ECharts and `vue-echarts`.

## Components

### 1. BarChart

Used for comparing categorical data.

**Props:**
- `title` (string): Title of the chart.
- `data` (Array<{ name: string, value: number }>): Data points.

**Usage:**
```vue
<template>
  <BarChart 
    title="Test Case Composition" 
    :data="[
      { name: 'Functional', value: 120 },
      { name: 'Performance', value: 80 }
    ]" 
  />
</template>
```

### 2. RingChart (Pie Chart)

Used for showing completion status and pass rates.

**Props:**
- `title` (string): Title of the chart.
- `icon` (Component, optional): Lucide icon component for the title.
- `data` (Object):
  - `total` (number): Total count.
  - `completed` (number): Completed count.
  - `passed` (number): Passed/Correct count.
  - `passRate` (number): Pass rate percentage (0-100).

**Usage:**
```vue
<template>
  <RingChart 
    title="Execution Status"
    :data="{
      total: 100,
      completed: 85,
      passed: 80,
      passRate: 94.1
    }"
    :icon="CodeIcon"
  />
</template>
```

### 3. LineChart

Used for visualizing trends over time.

**Props:**
- `title` (string): Title of the chart.
- `data` (Array<{ date: string, failed: number, passed: number }>): Trend data points.

**Usage:**
```vue
<template>
  <LineChart 
    title="Execution Trend" 
    :data="[
      { date: '2023-10-01', failed: 5, passed: 100 },
      { date: '2023-10-02', failed: 2, passed: 120 }
    ]" 
  />
</template>
```

## Dependencies

- `echarts`: ^5.x
- `vue-echarts`: ^6.x
- `lucide-vue-next`: For icons.

## Testing

Unit tests are located in `src/components/charts/Charts.spec.ts`.
Run tests with:
```bash
npm run test
```
