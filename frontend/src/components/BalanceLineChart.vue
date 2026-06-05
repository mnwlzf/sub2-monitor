<template>
  <div ref="chartEl" class="balance-line-chart" />
</template>

<script setup lang="ts">
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'

import type { AccountBalanceHistorySeries } from '@/api/client'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  series: AccountBalanceHistorySeries
}>()

const chartEl = shallowRef<HTMLDivElement | null>(null)
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const sampledPoints = computed(() =>
  props.series.points
    .filter((point) => point.balance !== null)
    .map((point) => ({
      at: point.at,
      balance: point.balance as number,
      quotaUsed: point.quota_used,
      quotaLimit: point.quota_limit,
    })),
)

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return '-'
  }
  return Number(value.toFixed(6)).toString()
}

function formatTime(value: string) {
  const date = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  })
}

function chartOptions(): EChartsCoreOption {
  const data = sampledPoints.value.map((point) => [point.at, point.balance])
  return {
    animation: false,
    color: ['#2563eb'],
    grid: {
      top: 32,
      right: 28,
      bottom: 42,
      left: 72,
      containLabel: false,
    },
    tooltip: {
      trigger: 'axis',
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
          `<strong>${props.series.account_name}</strong>`,
          `时间: ${formatTime(point.at)}`,
          `余额: ${formatNumber(point.balance)}`,
          `消耗: ${formatNumber(point.quotaUsed)}`,
          `额度: ${formatNumber(point.quotaLimit)}`,
        ].join('<br />')
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
      splitLine: {
        show: false,
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        color: '#64748b',
        fontFamily: 'Cascadia Mono, SFMono-Regular, Consolas, Liberation Mono, monospace',
        formatter(value: number) {
          return formatNumber(value)
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
        name: props.series.account_name,
        type: 'line',
        data,
        showSymbol: data.length <= 96,
        symbol: 'circle',
        symbolSize: 6,
        smooth: false,
        connectNulls: false,
        lineStyle: {
          width: 3,
          color: '#2563eb',
        },
        itemStyle: {
          color: '#2563eb',
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
              { offset: 0, color: 'rgba(37, 99, 235, 0.16)' },
              { offset: 1, color: 'rgba(37, 99, 235, 0)' },
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
