<template>
  <div ref="chartEl" class="rate-line-chart" />
</template>

<script setup lang="ts">
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'

import type { GroupRateHistorySeries } from '@/api/client'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  series: GroupRateHistorySeries[]
}>()

const palette = ['#2563eb', '#059669', '#d97706', '#7c3aed', '#dc2626', '#0891b2', '#db2777', '#65a30d']

const chartEl = shallowRef<HTMLDivElement | null>(null)
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const chartSeries = computed(() =>
  props.series.map((row, index) => ({
    row,
    color: palette[index % palette.length],
    points: row.points
      .filter((point) => point.effective_rate_multiplier !== null)
      .map((point) => ({
        at: point.at,
        timestamp: parseTime(point.at),
        rateMultiplier: point.rate_multiplier,
        effectiveRateMultiplier: point.effective_rate_multiplier as number,
        rpmLimit: point.rpm_limit,
      }))
      .filter((point) => point.timestamp !== null),
  })),
)

function parseTime(value: string) {
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  const timestamp = new Date(normalized).getTime()
  return Number.isNaN(timestamp) ? null : timestamp
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return '-'
  }
  return Number(value.toFixed(6)).toString()
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

function chartOptions(): EChartsCoreOption {
  return {
    animation: false,
    color: chartSeries.value.map((row) => row.color),
    legend: {
      type: 'scroll',
      top: 0,
      left: 10,
      right: 10,
      itemWidth: 10,
      itemHeight: 10,
      icon: 'circle',
      textStyle: {
        color: '#334155',
        fontSize: 12,
        fontWeight: 600,
      },
      inactiveColor: '#cbd5e1',
      pageIconColor: '#64748b',
      pageIconInactiveColor: '#cbd5e1',
      pageTextStyle: {
        color: '#64748b',
      },
      tooltip: {
        show: true,
      },
    },
    grid: {
      top: 48,
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
        const rows = Array.isArray(params) ? params : [params]
        return rows
          .map((item) => {
            const pointRef = item as { seriesIndex?: number; dataIndex?: number }
            if (typeof pointRef.seriesIndex !== 'number' || typeof pointRef.dataIndex !== 'number') {
              return ''
            }
            const seriesRow = chartSeries.value[pointRef.seriesIndex]
            const point = seriesRow?.points[pointRef.dataIndex]
            if (!seriesRow || !point) {
              return ''
            }
            return [
              `<strong>${seriesRow.row.group_name}</strong>`,
              `时间: ${formatTime(point.at)}`,
              `实际倍率: ${formatNumber(point.effectiveRateMultiplier)}`,
              `原始倍率: ${formatNumber(point.rateMultiplier)}`,
              `RPM: ${point.rpmLimit ?? '-'}`,
            ].join('<br />')
          })
          .filter(Boolean)
          .join('<br /><br />')
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
          return formatNumber(value)
        },
      },
      splitLine: {
        lineStyle: {
          color: '#e2e8f0',
        },
      },
    },
    series: chartSeries.value.map((row) => ({
      name: row.row.group_name,
      type: 'line',
      data: row.points.map((point) => [point.timestamp, point.effectiveRateMultiplier]),
      showSymbol: row.points.length <= 96,
      symbol: 'circle',
      symbolSize: 6,
      smooth: false,
      connectNulls: false,
      lineStyle: {
        width: 3,
        color: row.color,
      },
      itemStyle: {
        color: row.color,
        borderColor: '#ffffff',
        borderWidth: 1.5,
      },
    })),
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
  () => props.series,
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
