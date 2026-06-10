<template>
  <div class="chart-shell">
    <div ref="chartEl" class="first-token-line-chart" />
    <div v-if="sampledPoints.length === 0" class="chart-empty-state">
      暂无首 token 采样点
    </div>
  </div>
</template>

<script setup lang="ts">
import { LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'

import type { PlatformFirstTokenHistorySeries } from '@/api/client'

use([LineChart, DataZoomComponent, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  series: PlatformFirstTokenHistorySeries
}>()

const chartEl = shallowRef<HTMLDivElement | null>(null)
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const sampledPoints = computed(() =>
  props.series.points
    .filter((point) => point.model_first_token_ms !== null)
    .map((point) => ({
      at: point.at,
      timestamp: parseTime(point.at),
      firstTokenMs: point.model_first_token_ms as number,
      connectLatencyMs: point.connect_latency_ms,
      status: point.status,
      error: point.model_test_error || point.error_message,
    }))
    .filter((point) => point.timestamp !== null),
)

function parseTime(value: string) {
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  const timestamp = new Date(normalized).getTime()
  return Number.isNaN(timestamp) ? null : timestamp
}

function formatLatency(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return '-'
  }
  if (value >= 1000) {
    return `${Number((value / 1000).toFixed(2))}s`
  }
  return `${Math.round(value)}ms`
}

function formatTime(value: string) {
  const timestamp = parseTime(value)
  if (timestamp === null) {
    return value
  }
  return new Date(timestamp).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  })
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function chartOptions(): EChartsCoreOption {
  const data = sampledPoints.value.map((point) => [point.timestamp, point.firstTokenMs])
  return {
    animation: false,
    color: ['#0f766e'],
    grid: {
      top: 32,
      right: 54,
      bottom: 42,
      left: 72,
      containLabel: false,
    },
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: 0,
        filterMode: 'none',
        throttle: 60,
      },
      {
        type: 'inside',
        yAxisIndex: 0,
        filterMode: 'none',
        throttle: 60,
      },
      {
        type: 'slider',
        yAxisIndex: 0,
        filterMode: 'none',
        right: 8,
        top: 32,
        bottom: 42,
        width: 18,
        borderColor: '#cbd5e1',
        fillerColor: 'rgba(15, 118, 110, 0.12)',
        backgroundColor: '#f8fafc',
        handleSize: 14,
        labelFormatter(value: number) {
          return formatLatency(value)
        },
      },
    ],
    tooltip: {
      trigger: 'axis',
      confine: true,
      axisPointer: {
        type: 'line',
        lineStyle: {
          color: '#94a3b8',
          width: 1,
          type: 'dashed',
        },
      },
      formatter(params: unknown) {
        const first = (Array.isArray(params) ? params[0] : params) as { dataIndex?: number }
        if (typeof first.dataIndex !== 'number') {
          return ''
        }
        const point = sampledPoints.value[first.dataIndex]
        if (!point) {
          return ''
        }
        return [
          `<strong>${escapeHtml(props.series.platform_name)}</strong>`,
          `时间: ${formatTime(point.at)}`,
          `首 token: ${formatLatency(point.firstTokenMs)}`,
          `连接耗时: ${formatLatency(point.connectLatencyMs)}`,
          `状态: ${point.status}`,
          point.error ? `错误: ${escapeHtml(point.error)}` : '',
        ].filter(Boolean).join('<br />')
      },
    },
    xAxis: {
      type: 'time',
      boundaryGap: ['1%', '1%'],
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
      axisLabel: {
        color: '#64748b',
        fontFamily: 'Cascadia Mono, SFMono-Regular, Consolas, Liberation Mono, monospace',
        formatter(value: number) {
          return new Date(value).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
            timeZone: 'Asia/Shanghai',
          })
        },
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        color: '#64748b',
        fontFamily: 'Cascadia Mono, SFMono-Regular, Consolas, Liberation Mono, monospace',
        formatter(value: number) {
          return formatLatency(value)
        },
      },
      splitLine: {
        lineStyle: {
          color: '#e2e8f0',
        },
      },
    },
    series: [
      {
        name: props.series.platform_name,
        type: 'line',
        data,
        showSymbol: data.length <= 96,
        symbol: 'circle',
        symbolSize: 6,
        smooth: false,
        connectNulls: false,
        lineStyle: {
          width: 3,
          color: '#0f766e',
        },
        itemStyle: {
          color: '#0f766e',
          borderColor: '#ffffff',
          borderWidth: 1.5,
        },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(15, 118, 110, 0.16)' },
              { offset: 1, color: 'rgba(15, 118, 110, 0)' },
            ],
          },
        },
      },
    ],
  }
}

function renderChart() {
  if (!chartEl.value) {
    return
  }
  if (!chart) {
    chart = init(chartEl.value, undefined, { renderer: 'canvas' })
  }
  chart.setOption(chartOptions(), true)
}

onMounted(async () => {
  await nextTick()
  renderChart()
  if (chartEl.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartEl.value)
  }
})

watch(
  () => props.series.points,
  async () => {
    await nextTick()
    renderChart()
  },
  { deep: true },
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>
