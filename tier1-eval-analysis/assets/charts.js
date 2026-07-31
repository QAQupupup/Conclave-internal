(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var green = style.getPropertyValue('--green').trim();
  var red = style.getPropertyValue('--red').trim();
  var amber = style.getPropertyValue('--amber').trim();

  var fontFamily = style.getPropertyValue('--font').trim() || "'WorkSans', sans-serif";

  // === Chart 1: Overall Comparison (Bar) ===
  var chart1 = echarts.init(document.getElementById('chart-overall'), null, { renderer: 'svg' });
  chart1.setOption({
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, appendToBody: true },
    legend: { data: ['Pass@1 (%)', '平均分 (×100)'], bottom: 0, textStyle: { color: muted, fontSize: 12 } },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '15%' },
    xAxis: {
      type: 'category',
      data: ['V4-Flash 基线', 'Doubao R1', 'Doubao R2 (Stub)', 'Doubao-mini'],
      axisLine: { lineStyle: { color: rule } },
      axisLabel: { color: muted, fontSize: 11, rotate: 0 }
    },
    yAxis: {
      type: 'value', max: 100,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: rule, type: 'dashed' } },
      axisLabel: { color: muted, fontSize: 11 }
    },
    series: [
      {
        name: 'Pass@1 (%)', type: 'bar', barWidth: '25%',
        data: [10, 10, 0, 30],
        itemStyle: { color: accent, borderRadius: [3, 3, 0, 0] }
      },
      {
        name: '平均分 (×100)', type: 'bar', barWidth: '25%',
        data: [69.6, 62.5, 50.6, 84.9],
        itemStyle: { color: accent2, borderRadius: [3, 3, 0, 0] }
      }
    ]
  });
  window.addEventListener('resize', function() { chart1.resize(); });

  // === Chart 2: Stage Heatmap ===
  var stages = ['clarify', 'intra_team', 'cross_team', 'evidence_check', 'arbitrate', 'produce'];
  var runs = ['V4-Flash 基线', 'Doubao R1', 'Doubao R2 (Stub)', 'Doubao-mini'];
  var heatmapData = [
    [0, 0, 100], [0, 1, 88.9], [0, 2, 0], [0, 3, 30],
    [1, 0, 75], [1, 1, 37.5], [1, 2, 25], [1, 3, 10],
    [2, 0, 44.4], [2, 1, 0], [2, 2, 0], [2, 3, 0],
    [3, 0, 100], [3, 1, 66.7], [3, 2, 77.8], [3, 3, 77.8],
    [4, 0, 44.4], [4, 1, 100], [4, 2, 100], [4, 3, 100],
    [5, 0, 88.9], [5, 1, 37.5], [5, 2, 33.3], [5, 3, 100]
  ];

  var chart2 = echarts.init(document.getElementById('chart-heatmap'), null, { renderer: 'svg' });
  chart2.setOption({
    animation: false,
    tooltip: {
      trigger: 'item',
      appendToBody: true,
      formatter: function(p) {
        return stages[p.value[0]] + ' / ' + runs[p.value[1]] + '<br/>通过率: ' + p.value[2] + '%';
      }
    },
    grid: { left: '15%', right: '10%', top: '5%', bottom: '15%' },
    xAxis: {
      type: 'category', data: runs, splitArea: { show: false },
      axisLine: { lineStyle: { color: rule } },
      axisLabel: { color: muted, fontSize: 11 }
    },
    yAxis: {
      type: 'category', data: stages, splitArea: { show: false },
      axisLine: { lineStyle: { color: rule } },
      axisLabel: { color: muted, fontSize: 11 }
    },
    visualMap: {
      min: 0, max: 100,
      calculable: true, orient: 'horizontal', left: 'center', bottom: '2%',
      textStyle: { color: muted, fontSize: 11 },
      inRange: { color: [bg2, '#a8c5df', accent] }
    },
    series: [{
      type: 'heatmap', data: heatmapData,
      label: {
        show: true, color: ink, fontSize: 11,
        formatter: function(p) { return p.value[2] + '%'; }
      },
      itemStyle: { borderColor: bg2, borderWidth: 2 }
    }]
  });
  window.addEventListener('resize', function() { chart2.resize(); });

  // === Chart 3: Radar (V4-Flash vs Doubao-mini) ===
  var chart3 = echarts.init(document.getElementById('chart-radar'), null, { renderer: 'svg' });
  chart3.setOption({
    animation: false,
    tooltip: { trigger: 'item', appendToBody: true },
    legend: { data: ['V4-Flash 基线', 'Doubao-mini'], bottom: 0, textStyle: { color: muted, fontSize: 12 } },
    radar: {
      indicator: [
        { name: 'Clarify', max: 100 },
        { name: 'Intra_team', max: 100 },
        { name: 'Cross_team', max: 100 },
        { name: 'Evidence', max: 100 },
        { name: 'Arbitrate', max: 100 },
        { name: 'Produce', max: 100 }
      ],
      axisName: { color: muted, fontSize: 11 },
      splitLine: { lineStyle: { color: rule } },
      splitArea: { areaStyle: { color: [bg2, 'transparent'] } },
      axisLine: { lineStyle: { color: rule } }
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: [100, 88.9, 33.3, 22.2, 44.4, 88.9],
          name: 'V4-Flash 基线',
          itemStyle: { color: accent2 },
          lineStyle: { color: accent2, width: 2 },
          areaStyle: { color: accent2 + '20' }
        },
        {
          value: [100, 66.7, 77.8, 77.8, 100, 100],
          name: 'Doubao-mini',
          itemStyle: { color: accent },
          lineStyle: { color: accent, width: 2 },
          areaStyle: { color: accent + '20' }
        }
      ]
    }]
  });
  window.addEventListener('resize', function() { chart3.resize(); });

  // === Chart 4: Per-case Bar Chart ===
  var caseIds = [
    'api-gateway', 'data-warehouse', 'ecommerce', 'file-storage',
    'microservices', 'monitoring', 'realtime-analytics', 'saas-pricing',
    'tech-stack', 'user-auth'
  ];
  var v4flashScores = [66.7, 80.6, 52.8, 66.7, 66.7, 66.7, 62.5, 80.6, 0, 83.3];
  var miniScores = [88.9, 86.1, 69.4, 94.4, 86.1, 80.6, 88.9, 88.9, 0, 80.6];

  var chart4 = echarts.init(document.getElementById('chart-cases'), null, { renderer: 'svg' });
  chart4.setOption({
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, appendToBody: true },
    legend: { data: ['V4-Flash 基线', 'Doubao-mini'], bottom: 0, textStyle: { color: muted, fontSize: 12 } },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '15%' },
    xAxis: {
      type: 'category', data: caseIds,
      axisLine: { lineStyle: { color: rule } },
      axisLabel: { color: muted, fontSize: 10, rotate: 30 }
    },
    yAxis: {
      type: 'value', max: 100,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: rule, type: 'dashed' } },
      axisLabel: { color: muted, fontSize: 11, formatter: '{value}%' }
    },
    series: [
      {
        name: 'V4-Flash 基线', type: 'bar', barWidth: '30%',
        data: v4flashScores,
        itemStyle: { color: accent2, borderRadius: [3, 3, 0, 0] }
      },
      {
        name: 'Doubao-mini', type: 'bar', barWidth: '30%',
        data: miniScores,
        itemStyle: { color: accent, borderRadius: [3, 3, 0, 0] }
      }
    ]
  });
  window.addEventListener('resize', function() { chart4.resize(); });

})();
