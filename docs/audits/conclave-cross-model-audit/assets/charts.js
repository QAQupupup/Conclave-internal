(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var warn = style.getPropertyValue('--warn').trim();
  var ok = style.getPropertyValue('--ok').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // Chart 1: Severity distribution across reports
  var chart1 = echarts.init(document.getElementById('chart-severity'), null, { renderer: 'svg' });
  var data1 = [
    { name: '早期审计', critical: 1, high: 0, medium: 6, low: 11 },
    { name: '审计 v5.0', critical: 8, high: 13, medium: 7, low: 3 },
    { name: '全面审计', critical: 10, high: 56, medium: 38, low: 0 },
    { name: '审计 v5', critical: 13, high: 36, medium: 46, low: 20 },
    { name: '审计 Final', critical: 18, high: 42, medium: 86, low: 48 }
  ];
  var categories = data1.map(function(d) { return d.name; });
  var option1 = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' }
    },
    legend: {
      data: ['Critical', 'High', 'Medium', 'Low'],
      bottom: 0
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '15%',
      top: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: { color: muted },
      axisLine: { lineStyle: { color: rule } }
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: muted },
      axisLine: { lineStyle: { color: rule } }
    },
    series: [
      {
        name: 'Critical',
        type: 'bar',
        stack: 'total',
        data: data1.map(function(d) { return d.critical; }),
        itemStyle: { color: accent2 }
      },
      {
        name: 'High',
        type: 'bar',
        stack: 'total',
        data: data1.map(function(d) { return d.high; }),
        itemStyle: { color: warn }
      },
      {
        name: 'Medium',
        type: 'bar',
        stack: 'total',
        data: data1.map(function(d) { return d.medium; }),
        itemStyle: { color: accent }
      },
      {
        name: 'Low',
        type: 'bar',
        stack: 'total',
        data: data1.map(function(d) { return d.low; }),
        itemStyle: { color: ok }
      }
    ]
  };
  chart1.setOption(option1);
  window.addEventListener('resize', function() { chart1.resize(); });

  // Chart 2: Consensus issues by module
  var chart2 = echarts.init(document.getElementById('chart-module'), null, { renderer: 'svg' });
  var data2 = [
    { name: '安全漏洞', value: 7 },
    { name: '前端交互', value: 4 },
    { name: '前端状态', value: 3 },
    { name: '图表可视化', value: 3 },
    { name: '后端架构', value: 4 },
    { name: 'API与并发', value: 2 },
    { name: '数据持久化', value: 2 },
    { name: '沙箱与工具', value: 2 }
  ];
  data2.sort(function(a, b) { return b.value - a.value; });
  var option2 = {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 项'
    },
    grid: {
      left: '10%',
      right: '10%',
      top: '3%',
      bottom: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'value',
      axisLabel: { color: muted },
      axisLine: { lineStyle: { color: rule } }
    },
    yAxis: {
      type: 'category',
      data: data2.map(function(d) { return d.name; }),
      axisLabel: { color: muted },
      axisLine: { lineStyle: { color: rule } }
    },
    series: [{
      type: 'bar',
      data: data2.map(function(d) { return d.value; }),
      itemStyle: {
        color: function(params) {
          return [accent2, warn, accent, ok][params.dataIndex % 4];
        }
      },
      label: {
        show: true,
        position: 'right',
        color: ink
      }
    }]
  };
  chart2.setOption(option2);
  window.addEventListener('resize', function() { chart2.resize(); });

  // Chart 3: Radar chart — coverage comparison
  var chart3 = echarts.init(document.getElementById('chart-radar'), null, { renderer: 'svg' });
  var option3 = {
    tooltip: { trigger: 'item' },
    legend: {
      bottom: 0,
      data: ['早期审计', '审计 v5.0', '全面审计', '审计 Final'],
      textStyle: { color: ink }
    },
    radar: {
      indicator: [
        { name: '安全审计', max: 10 },
        { name: '前端架构', max: 10 },
        { name: '后端架构', max: 10 },
        { name: 'API设计', max: 10 },
        { name: '可观测性', max: 10 },
        { name: 'UX交互', max: 10 },
        { name: '可视化', max: 10 },
        { name: '工程化', max: 10 }
      ],
      radius: '60%',
      center: ['50%', '45%'],
      axisName: { color: ink },
      splitArea: {
        areaStyle: {
          colors: [bg2, '#fff', bg2, '#fff']
        }
      }
    },
    series: [{
      name: '审计覆盖范围',
      type: 'radar',
      data: [
        {
          value: [2, 1, 1, 1, 0, 1, 0, 0],
          name: '早期审计',
          areaStyle: { opacity: 0.2 },
          lineStyle: { width: 2, color: accent2 }
        },
        {
          value: [5, 4, 3, 2, 2, 4, 4, 2],
          name: '审计 v5.0',
          areaStyle: { opacity: 0.2 },
          lineStyle: { width: 2, color: warn }
        },
        {
          value: [8, 7, 6, 5, 4, 6, 4, 5],
          name: '全面审计',
          areaStyle: { opacity: 0.2 },
          lineStyle: { width: 2, color: accent }
        },
        {
          value: [10, 9, 8, 7, 6, 7, 5, 7],
          name: '审计 Final',
          areaStyle: { opacity: 0.2 },
          lineStyle: { width: 2, color: ok }
        }
      ]
    }]
  };
  chart3.setOption(option3);
  window.addEventListener('resize', function() { chart3.resize(); });

})();
