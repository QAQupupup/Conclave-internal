// 资源图表组件：ECharts 优雅折线图 v4
// 设计参考：Linear / Vercel / Stripe Dashboard - 克制、精致、呼吸感
//
// [v4 重构] 基于用户反馈：
//   1) 数据点限制：仅展示最近 12 个采集点，折线更简洁
//   2) 线条 1.5px 细线（之前2px太粗），圆角端点
//   3) 颜色弃用蓝色，改用柔和深灰/墨色系：主色 #4A5568（slate灰蓝）
//   4) 去掉面积填充（更干净），或极淡5%透明度
//   5) 末点标记：最后一个数据点显示圆点 + 数值标签（endLabel）
//   6) 首末点有小圆点标记（symbol: 'circle' 仅首尾）
//   7) 网格线极淡 #F7F8F9
//   8) 紧凑/常规模式自适应
import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import type { EChartsType, EChartsOption } from 'echarts'
import type { MetricPoint } from '../lib/api.ts'

type ChartType = 'memory' | 'tokens' | 'throughput'

interface ResourceChartProps {
  type: ChartType
  data: MetricPoint[]
  title: string
}

/** 最多展示的数据点数量（保持折线优雅不密集） */
const MAX_POINTS = 12

interface Palette {
  primary: string       // 主折线：柔和深灰蓝
  secondary: string     // 副折线：灰绿
  tertiary: string      // 第三色：暖灰棕
  gridLine: string
  axisLine: string
  textPrimary: string
  textSecondary: string
  textTertiary: string
  dotBorder: string
  isDark: boolean
}

function getPalette(): Palette {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark'
  const light = {
    // [v4] 弃用蓝色，改用柔和墨色系
    primary: '#4A5568',     // slate-600 柔和深灰蓝
    secondary: '#5F7F6E',   // 灰绿（低饱和）
    tertiary: '#A08060',    // 暖灰棕（低饱和）
    gridLine: '#F7F8F9',    // 极淡灰
    axisLine: '#EDF0F3',    // 轴线更淡
    textPrimary: '#1A202C',
    textSecondary: '#8791A0',
    textTertiary: '#B0B8C4',
    dotBorder: '#FFFFFF',
  }
  const dark = {
    primary: '#9AA8B8',
    secondary: '#7FA890',
    tertiary: '#C0A080',
    gridLine: 'rgba(255,255,255,0.05)',
    axisLine: 'rgba(255,255,255,0.08)',
    textPrimary: '#E8ECF1',
    textSecondary: 'rgba(255,255,255,0.40)',
    textTertiary: 'rgba(255,255,255,0.22)',
    dotBorder: '#1A1F29',
  }
  return { ...(isDark ? dark : light), isDark }
}

function hexRgba(hex: string, a: number): string {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map(x => x + x).join('')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${a})`
}

/** 数值格式化 */
function fmt(n: number): string {
  if (!Number.isFinite(n)) return '0'
  const abs = Math.abs(n)
  if (abs >= 1e9) return (n / 1e9).toFixed(1) + 'B'
  if (abs >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  if (Number.isInteger(n)) return String(n)
  if (abs < 10) return n.toFixed(1)
  return String(Math.round(n))
}

/** 成本格式化 */
function fmtCost(n: number): string {
  if (n < 0.01) return '<$0.01'
  return `$${n.toFixed(2)}`
}

function summarize(arr: number[]): { max: number; avg: number; last: number } | null {
  if (!arr.length) return null
  let max = -Infinity, sum = 0
  for (const v of arr) { if (v > max) max = v; sum += v }
  return { max, avg: sum / arr.length, last: arr[arr.length - 1] }
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

interface Ctx {
  p: Palette
  compact: boolean
  narrow: boolean  // < 220px 超窄模式：隐藏X轴标签和图例
}

/** 截取最近 N 个数据点 */
function takeRecent<T>(arr: T[], n: number): T[] {
  if (arr.length <= n) return arr
  return arr.slice(arr.length - n)
}

function chartTitle(text: string, subtext: string, ctx: Ctx): EChartsOption['title'] {
  return {
    show: true,
    text,
    subtext,
    left: 0,
    top: 2,
    textStyle: { color: ctx.p.textPrimary, fontSize: ctx.compact ? 12 : 13, fontWeight: 600, fontFamily: 'inherit' },
    subtextStyle: { color: ctx.p.textSecondary, fontSize: ctx.compact ? 10 : 11, fontFamily: 'inherit', fontWeight: 400, lineHeight: 14 },
    itemGap: 4,
    padding: 0,
  }
}

function emptyState(title: string, hint: string, ctx: Ctx): EChartsOption {
  return {
    title: chartTitle(title, '', ctx),
    graphic: [{
      type: 'group', left: 'center', top: 'middle',
      children: [{
        type: 'text',
        style: { text: hint, fill: ctx.p.textTertiary, fontSize: 12, fontFamily: 'inherit', align: 'center', fontWeight: 500 },
        left: 'center', top: -8,
      }],
    }],
    xAxis: { type: 'category', show: false, data: [] },
    yAxis: { type: 'value', show: false },
  }
}

function commonBase(ctx: Ctx, xLabels: string[], showLegend: boolean, dualAxis: boolean): EChartsOption {
  // [v4.5] 响应式边距
  const { p, compact, narrow } = ctx
  const effectiveShowLegend = showLegend && !narrow
  const gridLeft = compact ? 44 : 52
  const gridRight = compact ? (narrow ? 8 : 20) : (dualAxis ? (effectiveShowLegend ? 60 : 48) : 56)
  const gridTop = compact ? 28 : 48
  const gridBottom = effectiveShowLegend ? (compact ? 42 : 48) : (compact ? 22 : 30)

  return {
    backgroundColor: 'transparent',
    animation: true,
    animationDuration: 500,
    animationEasing: 'cubicOut',
    animationDurationUpdate: 200,
    animationEasingUpdate: 'cubicInOut',
    grid: { left: gridLeft, right: gridRight, top: gridTop, bottom: gridBottom, containLabel: false },
    tooltip: {
      trigger: 'axis',
      appendToBody: true,
      confine: true,
      backgroundColor: ctx.p.isDark ? 'rgba(26,31,41,0.96)' : 'rgba(255,255,255,0.97)',
      borderColor: ctx.p.isDark ? 'rgba(255,255,255,0.10)' : '#EDF0F3',
      borderWidth: 1,
      borderRadius: 8,
      padding: [10, 14],
      extraCssText: `box-shadow:0 4px 20px rgba(0,0,0,${ctx.p.isDark ? '0.50' : '0.07'}),0 1px 3px rgba(0,0,0,0.04);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);`,
      textStyle: { color: p.textPrimary, fontSize: 12, fontFamily: 'inherit' },
      axisPointer: {
        type: 'line', snap: true, animation: true,
        lineStyle: { color: p.textTertiary, width: 1, type: 'dashed', opacity: 0.6 },
        label: { show: false },
      },
      formatter: (params: any) => {
        if (!params || !params.length) return ''
        let html = `<div style="font-weight:600;margin-bottom:6px;color:${p.textPrimary};font-size:12px">${params[0].axisValue}</div>`
        for (const item of params) {
          const dot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${item.color};margin-right:8px;flex-shrink:0"></span>`
          const val = typeof item.value === 'number' ? fmt(item.value) : item.value
          html += `<div style="display:flex;justify-content:space-between;align-items:center;margin:3px 0;min-width:130px;gap:16px">
            <span style="display:flex;align-items:center;color:${p.textSecondary};font-size:12px">${dot}${item.seriesName}</span>
            <span style="font-weight:600;color:${p.textPrimary};font-variant-numeric:tabular-nums;font-size:12px">${val}</span>
          </div>`
        }
        return html
      },
    },
    // [v4.4] 图例放底部居中，narrow模式隐藏
    legend: effectiveShowLegend ? {
      show: true,
      bottom: 2,
      left: 'center',
      orient: 'horizontal',
      itemWidth: compact ? 10 : 12,
      itemHeight: 2,
      itemGap: compact ? 10 : 16,
      icon: 'roundRect',
      textStyle: { color: p.textSecondary, fontSize: compact ? 9 : 11, fontFamily: 'inherit' },
      inactiveColor: p.textTertiary,
      selectedMode: true,
      padding: [0, 0, 0, 0],
    } : { show: false },
    xAxis: {
      type: 'category',
      data: xLabels,
      boundaryGap: false,
      axisLine: { show: true, lineStyle: { color: p.axisLine, width: 1 } },
      axisTick: { show: false },
      axisLabel: {
        color: p.textSecondary,
        fontSize: compact ? 9 : 11,
        fontFamily: 'inherit',
        margin: compact ? 5 : 8,
        showMaxLabel: !narrow,
        showMinLabel: !narrow,
        hideOverlap: true,
        show: !narrow,
        // compact 模式只显示首末；非compact模式约5-6个标签
        interval: narrow ? 0 : (compact ? xLabels.length - 1 : Math.max(2, Math.floor(xLabels.length / 5))),
      },
      splitLine: { show: false },
    },
  }
}

function makeYAxis(ctx: Ctx, customFmt?: (v: number) => string, minInterval?: number): any {
  const { p, compact } = ctx
  return {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: p.textSecondary,
      fontSize: compact ? 9 : 11,
      fontFamily: 'inherit',
      margin: 6,
      formatter: customFmt || ((v: number) => fmt(v)),
      hideOverlap: true,
      align: 'right' as const,
    },
    splitLine: { show: true, lineStyle: { color: p.gridLine, width: 1, type: 'solid' } },
    splitNumber: compact ? 3 : 4,
    scale: true,
    minInterval: minInterval,
  }
}

function makeSecondaryYAxis(ctx: Ctx, customFmt?: (v: number) => string): any {
  const { p, compact } = ctx
  return {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: p.textTertiary,
      fontSize: compact ? 10 : 11,
      fontFamily: 'inherit',
      margin: 6,
      formatter: customFmt || ((v: number) => fmt(v)),
      hideOverlap: true,
      align: 'right' as const,
      show: !compact,
    },
    splitLine: { show: false },
    splitNumber: compact ? 3 : 4,
    scale: true,
  }
}

/** 创建折线系列 */
function makeSeries(
  name: string,
  values: number[],
  color: string,
  yAxisIndex: number,
  dashed: boolean,
  ctx: Ctx,
  endLabelFmt?: (v: number) => string,
): any {
  const { p, compact } = ctx
  const len = values.length
  // 仅首尾点显示小圆点，其他点隐藏
  const symbolSize = compact ? 3 : 3.5
  const symbolFn = (_value: number, params: any) => {
    const idx = params.dataIndex
    if (idx === 0 || idx === len - 1) return 'circle'
    return 'none'
  }

  return {
    name,
    type: 'line',
    data: values,
    yAxisIndex,
    smooth: 0.35,        // 轻微平滑，不过度弯曲
    smoothMonotone: 'x',
    sampling: 'lttb',
    // [v4] 1.5px 细线
    lineStyle: {
      width: 1.5,
      color,
      cap: 'round',
      join: 'round',
      type: dashed ? [4, 4] : 'solid',
    },
    // 无面积填充（更干净）
    areaStyle: undefined,
    // 首尾点标记
    symbol: symbolFn,
    symbolSize: symbolSize,
    itemStyle: {
      color,
      borderColor: p.dotBorder,
      borderWidth: 1.5,
    },
    // 末点数值标签（endLabel）：仅非compact模式显示，避免重叠
    endLabel: {
      show: !compact && !!endLabelFmt,
      formatter: (params: any) => endLabelFmt ? endLabelFmt(params.value) : fmt(params.value),
      color: p.textPrimary,
      fontSize: 10,
      fontWeight: 600,
      fontFamily: 'inherit',
      padding: [2, 5],
      backgroundColor: ctx.p.isDark ? 'rgba(255,255,255,0.08)' : hexRgba(color, 0.08),
      borderRadius: 3,
      offset: [6, -2],
    },
    labelLayout: { moveOverlap: 'shiftY' },
    emphasis: {
      focus: 'series',
      scale: false,
      lineStyle: { width: 2, color },
      itemStyle: {
        color,
        borderColor: p.dotBorder,
        borderWidth: 2,
        shadowBlur: 6,
        shadowColor: hexRgba(color, 0.3),
      },
    },
    blur: { lineStyle: { opacity: 0.2 } },
    connectNulls: true,
    showSymbol: true,  // 必须true，否则symbol函数不生效
    hoverAnimation: true,
  }
}

/** 根据数据范围计算合适的Y轴最小间距，避免标签重复 */
function calcMinInterval(values: number[]): number {
  const max = Math.max(...values)
  const min = Math.min(...values)
  const range = max - min
  if (max >= 1000) return Math.max(50, Math.ceil(range / 4 / 50) * 50)
  if (max >= 100) return Math.max(10, Math.ceil(range / 4 / 10) * 10)
  if (max >= 10) return Math.max(1, Math.ceil(range / 4))
  if (max >= 1) return Math.max(0.5, range / 4)
  return Math.max(0.1, range / 4)
}

/** 内存图表 */
function buildMemoryOption(points: MetricPoint[], ctx: Ctx): EChartsOption {
  const tss = points.map(d => fmtTime(d.ts))
  const values = points.map(d => d.memory_mb)
  const sum = summarize(values)
  const sub = ctx.compact ? '' : (sum ? `峰值 ${fmt(sum.max)} MB · 当前 ${fmt(sum.last)} MB` : '')
  return {
    ...commonBase(ctx, tss, false, false),
    title: chartTitle('内存使用', sub, ctx),
    yAxis: makeYAxis(ctx, undefined, calcMinInterval(values)),
    series: [makeSeries('内存 (MB)', values, ctx.p.primary, 0, false, ctx, v => `${fmt(v)} MB`)],
  }
}

/** Token 图表 */
function buildTokensOption(points: MetricPoint[], ctx: Ctx): EChartsOption {
  const tss = points.map(d => fmtTime(d.ts))
  const tokens = points.map(d => d.tokens)
  const costScaled = points.map(d => d.cost_usd * 100)
  const rawCost = points.map(d => d.cost_usd)
  const sumTok = summarize(tokens)
  const sumCost = summarize(rawCost)
  const sub = ctx.compact ? '' : (sumTok ? `累计 ${fmt(sumTok.last)} · 成本 ${fmtCost(sumCost?.last ?? 0)}` : '')
  return {
    ...commonBase(ctx, tss, true, true),
    title: chartTitle('Token 消耗', sub, ctx),
    yAxis: [
      makeYAxis(ctx, undefined, calcMinInterval(tokens)),
      makeSecondaryYAxis(ctx, v => ctx.compact ? '' : `$${(v / 100).toFixed(2)}`),
    ],
    series: [
      makeSeries('Tokens', tokens, ctx.p.primary, 0, false, ctx, v => fmt(v)),
      makeSeries('成本', costScaled, ctx.p.secondary, 1, true, ctx),
    ],
  }
}

/** 吞吐量图表 */
function buildThroughputOption(points: MetricPoint[], ctx: Ctx): EChartsOption {
  const tss = points.map(d => fmtTime(d.ts))
  const rpm = points.map(d => d.requests_per_min)
  const lat = points.map(d => d.latency_ms)
  const sumRpm = summarize(rpm)
  const sumLat = summarize(lat)
  const sub = ctx.compact ? '' : (sumRpm ? `当前 ${fmt(sumRpm.last)}/min · 延迟 ${fmt(sumLat?.last ?? 0)}ms` : '')
  return {
    ...commonBase(ctx, tss, true, true),
    title: chartTitle('API 吞吐量', sub, ctx),
    yAxis: [
      makeYAxis(ctx, undefined, calcMinInterval(rpm)),
      makeSecondaryYAxis(ctx, v => ctx.compact ? '' : `${fmt(v)}ms`),
    ],
    series: [
      makeSeries('请求/分钟', rpm, ctx.p.primary, 0, false, ctx, v => `${fmt(v)}/m`),
      makeSeries('延迟 (ms)', lat, ctx.p.tertiary, 1, true, ctx),
    ],
  }
}

export function ResourceChart({ type, data, title }: ResourceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const roRef = useRef<ResizeObserver | null>(null)
  const themeObsRef = useRef<MutationObserver | null>(null)
  const [, setLayout] = useState({ compact: false, narrow: false })

  function buildOption(d: MetricPoint[], isCompact: boolean, isNarrow: boolean): EChartsOption {
    const p = getPalette()
    const ctx: Ctx = { p, compact: isCompact, narrow: isNarrow }
    if (!d || d.length === 0) return emptyState(title, '暂无数据', ctx)
    const points = takeRecent(d, MAX_POINTS)
    const hasNonZero = points.some(pt => pt.memory_mb > 0 || pt.tokens > 0 || pt.requests_per_min > 0 || pt.latency_ms > 0)
    if (!hasNonZero) return emptyState(title, '等待数据中...', ctx)
    switch (type) {
      case 'memory': return buildMemoryOption(points, ctx)
      case 'tokens': return buildTokensOption(points, ctx)
      case 'throughput': return buildThroughputOption(points, ctx)
    }
  }

  function applyChart(w: number) {
    const isCompact = w < 380
    const isNarrow = w < 220
    setLayout({ compact: isCompact, narrow: isNarrow })
    if (chartRef.current && !chartRef.current.isDisposed()) {
      chartRef.current.setOption(buildOption(data, isCompact, isNarrow), { notMerge: true, lazyUpdate: true })
    }
  }

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const w = container.clientWidth
    if (!chartRef.current) {
      chartRef.current = echarts.init(container, undefined, {
        renderer: 'canvas',
        useDirtyRect: true,
        devicePixelRatio: window.devicePixelRatio || 1,
      })
    }
    const chart = chartRef.current
    applyChart(w)

    roRef.current?.disconnect()
    roRef.current = new ResizeObserver((entries) => {
      if (chart && !chart.isDisposed()) {
        const newW = entries[0]?.contentRect.width ?? container.clientWidth
        applyChart(newW)
        chart.resize()
      }
    })
    roRef.current.observe(container)
    return () => { roRef.current?.disconnect(); roRef.current = null }
  }, [data, type, title])

  useEffect(() => {
    themeObsRef.current = new MutationObserver(() => {
      // 主题切换：用新调色板重建选项
      if (containerRef.current) {
        applyChart(containerRef.current.clientWidth)
      }
    })
    themeObsRef.current.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { themeObsRef.current?.disconnect(); themeObsRef.current = null }
  }, [data])

  useEffect(() => {
    return () => {
      if (chartRef.current && !chartRef.current.isDisposed()) chartRef.current.dispose()
      chartRef.current = null
    }
  }, [])

  return (
    <div className="resource-chart">
      <div ref={containerRef} className="chart-container" />
    </div>
  )
}
