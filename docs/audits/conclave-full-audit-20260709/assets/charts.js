(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var ok = '#16a34a';
  var warn = '#d97706';
  var err = '#dc2626';
  var critical = '#7c2d12';

  // ── Chart 1: Overview — Stacked Bar by Module ──
  var chartOverview = echarts.init(document.getElementById('chart-overview'), null, { renderer: 'svg' });
  chartOverview.setOption({
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, appendToBody: true },
    legend: { data: ['Critical', 'Major', 'Minor'], bottom: 0, textStyle: { color: muted, fontSize: 12 } },
    grid: { left: 80, right: 30, top: 20, bottom: 50 },
    xAxis: { type: 'value', axisLine: { lineStyle: { color: rule } }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule, type: 'dashed' } } },
    yAxis: { type: 'category', data: ['架构/UX', '后端', '前端'], axisLine: { lineStyle: { color: rule } }, axisLabel: { color: ink, fontSize: 13, fontWeight: 'bold' } },
    series: [
      { name: 'Critical', type: 'bar', stack: 'total', data: [0, 4, 6], itemStyle: { color: critical }, barWidth: 36 },
      { name: 'Major', type: 'bar', stack: 'total', data: [8, 24, 24], itemStyle: { color: err } },
      { name: 'Minor', type: 'bar', stack: 'total', data: [15, 12, 11], itemStyle: { color: warn } }
    ]
  });

  // ── Chart 2: Frontend — Radar by Dimension ──
  var chartFrontend = echarts.init(document.getElementById('chart-frontend'), null, { renderer: 'svg' });
  chartFrontend.setOption({
    animation: false,
    tooltip: { appendToBody: true },
    radar: {
      indicator: [
        { name: '交互逻辑', max: 15 },
        { name: '状态管理', max: 15 },
        { name: '数据可视化', max: 15 },
        { name: '样式/UI', max: 15 },
        { name: '代码质量', max: 15 },
        { name: '路由/构建', max: 15 }
      ],
      shape: 'polygon',
      splitNumber: 3,
      axisName: { color: ink, fontSize: 12 },
      splitLine: { lineStyle: { color: rule } },
      splitArea: { areaStyle: { color: [bg2, 'transparent'] } },
      axisLine: { lineStyle: { color: rule } }
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: [7, 5, 4, 5, 10, 4],
          name: '问题数量',
          lineStyle: { color: accent, width: 2 },
          areaStyle: { color: accent + '22' },
          itemStyle: { color: accent }
        }
      ]
    }]
  });

  // ── Chart 3: Backend — Horizontal Bar by Category ──
  var chartBackend = echarts.init(document.getElementById('chart-backend'), null, { renderer: 'svg' });
  chartBackend.setOption({
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, appendToBody: true },
    legend: { data: ['Critical', 'Major'], bottom: 0, textStyle: { color: muted, fontSize: 12 } },
    grid: { left: 100, right: 30, top: 20, bottom: 50 },
    xAxis: { type: 'value', axisLine: { lineStyle: { color: rule } }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule, type: 'dashed' } } },
    yAxis: { type: 'category', data: ['代码质量', '可观测性', '安全', 'WebSocket', '编排/Agent', '数据库', 'API 设计'], axisLine: { lineStyle: { color: rule } }, axisLabel: { color: ink, fontSize: 12 } },
    series: [
      { name: 'Critical', type: 'bar', stack: 'total', data: [0, 0, 1, 0, 1, 1, 1], itemStyle: { color: critical }, barWidth: 28 },
      { name: 'Major', type: 'bar', stack: 'total', data: [4, 1, 3, 2, 3, 5, 3], itemStyle: { color: err } }
    ]
  });

  // ── Chart 4: Priority Matrix — Scatter ──
  var chartPriority = echarts.init(document.getElementById('chart-priority'), null, { renderer: 'svg' });
  chartPriority.setOption({
    animation: false,
    tooltip: {
      appendToBody: true,
      formatter: function(p) { return p.data[3] + '<br/>影响: ' + p.data[0] + ' / 紧急度: ' + p.data[1]; }
    },
    grid: { left: 70, right: 30, top: 30, bottom: 50 },
    xAxis: { name: '影响范围 →', nameLocation: 'center', nameGap: 30, nameTextStyle: { color: muted, fontSize: 12 }, type: 'value', min: 0, max: 10, axisLine: { lineStyle: { color: rule } }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule, type: 'dashed' } } },
    yAxis: { name: '↑ 紧急程度', nameLocation: 'end', nameTextStyle: { color: muted, fontSize: 12 }, type: 'value', min: 0, max: 10, axisLine: { lineStyle: { color: rule } }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule, type: 'dashed' } } },
    series: [
      {
        type: 'scatter',
        symbolSize: function(data) { return data[2] * 3; },
        data: [
          [9, 10, 18, 'C-01 命令执行安全绕过', critical],
          [7, 9, 14, 'C-02 路由装饰器缺失', critical],
          [8, 7, 16, 'C-03 双重持久化层', critical],
          [6, 8, 12, 'C-04 介入处理竞态', critical],
          [9, 8, 16, 'C-05 无 Error Boundary', critical],
          [7, 6, 12, 'C-06/07 ECharts 问题', critical],
          [5, 5, 10, 'C-08 ThemeContext memo', critical],
          [4, 4, 8, 'C-09 动态 import', critical],
          [3, 3, 8, 'C-10 语言硬编码', critical],
          [8, 6, 14, 'AR-01 数据库并存', err],
          [7, 5, 12, 'AR-02 Docker 安全', err],
          [6, 5, 12, 'BE-G04 RealLLM 实例泄漏', err],
          [5, 4, 10, 'BE-D01 WS 心跳', err],
          [8, 4, 14, 'FE-D01 CSS 模块化', err],
          [6, 3, 12, 'BE-C05/06 拆分大文件', err],
          [4, 3, 10, 'AR-03 Landing Page', err],
          [5, 2, 10, 'BE-G03 测试覆盖', err],
          [3, 2, 8, 'AR-04 信息过载', err]
        ],
        itemStyle: {
          color: function(params) { return params.data[4]; }
        },
        label: { show: false }
      }
    ],
    visualMap: { show: false }
  });

  // ── Resize ──
  window.addEventListener('resize', function() {
    chartOverview.resize();
    chartFrontend.resize();
    chartBackend.resize();
    chartPriority.resize();
  });
})();
