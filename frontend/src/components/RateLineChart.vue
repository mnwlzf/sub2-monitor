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

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function legendGridTop() {
  if (chartSeries.value.length <= 1) {
    return 42
  }
  const rows = Math.ceil(chartSeries.value.length / 4)
  return Math.min(118, 34 + rows * 24)
}

function chartOptions(): EChartsCoreOption {
  return {
    animation: false,
    color: chartSeries.value.map((row) => row.color),
    legend: {
      type: 'plain',
      top: 0,
      left: 10,
      right: 10,
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 12,
      icon: 'circle',
      textStyle: {
        color: '#334155',
        fontSize: 12,
        fontWeight: 600,
        width: 132,
        overflow: 'truncate',
      },
      inactiveColor: '#cbd5e1',
      tooltip: {
        show: true,
      },
    },
    grid: {
      top: legendGridTop(),
      right: 28,
      bottom: 42,
      left: 72,
      containLabel: false,
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      appendTo: 'body',
      extraCssText: [
        'max-height: 280px',
        'max-width: 340px',
        'overflow-y: auto',
        'overflow-x: hidden',
        'box-shadow: 0 12px 30px rgba(15, 23, 42, 0.18)',
      ].join(';'),
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
        const items = rows
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
              '<div style="display:grid;gap:2px;padding:4px 0;border-bottom:1px solid #eef2f7;">',
              '<div style="display:flex;align-items:center;gap:6px;min-width:0;">',
              `<span style="width:8px;height:8px;border-radius:999px;background:${seriesRow.color};flex:0 0 auto;"></span>`,
              `<strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(seriesRow.row.group_name)}</strong>`,
              '</div>',
              `<div>实际倍率: ${formatNumber(point.effectiveRateMultiplier)}</div>`,
              `<div>原始倍率: ${formatNumber(point.rateMultiplier)} / RPM: ${point.rpmLimit ?? '-'}</div>`,
              '</div>',
            ].join('')
          })
          .filter(Boolean)
        const firstItem = rows[0] as { seriesIndex?: number; dataIndex?: number } | undefined
        const firstPoint =
          typeof firstItem?.seriesIndex === 'number' && typeof firstItem.dataIndex === 'number'
            ? chartSeries.value[firstItem.seriesIndex]?.points[firstItem.dataIndex]
            : null
        return [
          '<div style="display:grid;gap:6px;color:#475569;font-size:12px;line-height:1.45;">',
          firstPoint ? `<div style="font-weight:700;color:#0f172a;">${formatTime(firstPoint.at)}</div>` : '',
          ...items,
          '</div>',
        ].join('')
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
