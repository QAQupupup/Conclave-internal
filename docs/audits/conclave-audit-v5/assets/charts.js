(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim() || '#2563eb';
  var accent2 = style.getPropertyValue('--accent2').trim() || '#059669';
  var ink = style.getPropertyValue('--ink').trim() || '#1a1d21';
  var muted = style.getPropertyValue('--muted').trim() || '#6b7280';
  var rule = style.getPropertyValue('--rule').trim() || '#e5e7eb';
  var bg2 = style.getPropertyValue('--bg2').trim() || '#f8f9fa';

  var dangerColor = '#dc2626';
  var warnColor = '#d97706';
  var blueColor = '#2563eb';
  var greenColor = '#059669';

  // --- Chart 1: Issue count by audit dimension ---
  var chart1 = echarts.init(document.getElementById('chart-dimension'), null, { renderer: 'svg' });
  chart1.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    legend: { data: ['Critical', 'High', 'Medium', 'Low'], bottom: 0, textStyle: { color: muted } },
    grid: { left: '8%', right: '5%', top: '5%', bottom: '15%' },
    xAxis: {
      type: 'category',
      data: ['前端', '后端', '基础设施', '前后端契约'],
      axisLabel: { color: ink, fontSize: 13 },
      axisLine: { lineStyle: { color: rule } }
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: rule } }
    },
    series: [
      { name: 'Critical', type: 'bar', stack: 'total', itemStyle: { color: dangerColor }, data: [5, 7, 8, 2] },
      { name: 'High', type: 'bar', stack: 'total', itemStyle: { color: warnColor }, data: [30, 12, 18, 4] },
      { name: 'Medium', type: 'bar', stack: 'total', itemStyle: { color: blueColor }, data: [32, 25, 16, 3] },
      { name: 'Low', type: 'bar', stack: 'total', itemStyle: { color: greenColor }, data: [0, 20, 3, 0] }
    ]
  });
  window.addEventListener('resize', function() { chart1.resize(); });

  // --- Chart 2: Backend issue severity distribution (pie) ---
  var chart2 = echarts.init(document.getElementById('chart-backend'), null, { renderer: 'svg' });
  chart2.setOption({
    animation: false,
    tooltip: { trigger: 'item', appendToBody: true },
    legend: { bottom: 0, textStyle: { color: muted } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '45%'],
      label: { color: ink, fontSize: 12 },
      data: [
        { value: 7, name: 'Critical', itemStyle: { color: dangerColor } },
        { value: 12, name: 'High', itemStyle: { color: warnColor } },
        { value: 25, name: 'Medium', itemStyle: { color: blueColor } },
        { value: 20, name: 'Low', itemStyle: { color: greenColor } }
      ]
    }]
  });
  window.addEventListener('resize', function() { chart2.resize(); });

  // --- Chart 3: Global severity distribution (donut) ---
  var chart3 = echarts.init(document.getElementById('chart-severity'), null, { renderer: 'svg' });
  chart3.setOption({
    animation: false,
    tooltip: { trigger: 'item', appendToBody: true },
    legend: { bottom: 0, textStyle: { color: muted } },
    series: [{
      type: 'pie',
      radius: ['45%', '75%'],
      center: ['50%', '45%'],
      label: {
        color: ink,
        fontSize: 12,
        formatter: '{b}\n{c} ({d}%)'
      },
      data: [
        { value: 20, name: 'Critical', itemStyle: { color: dangerColor } },
        { value: 60, name: 'High', itemStyle: { color: warnColor } },
        { value: 73, name: 'Medium', itemStyle: { color: blueColor } },
        { value: 23, name: 'Low', itemStyle: { color: greenColor } }
      ]
    }]
  });
  window.addEventListener('resize', function() { chart3.resize(); });

  // --- Chart 4: Issue count by module (horizontal bar) ---
  var chart4 = echarts.init(document.getElementById('chart-module'), null, { renderer: 'svg' });
  chart4.setOption({
    animation: false,
    tooltip: { trigger: 'axis', appendToBody: true },
    grid: { left: '18%', right: '8%', top: '5%', bottom: '5%' },
    xAxis: {
      type: 'value',
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: rule } }
    },
    yAxis: {
      type: 'category',
      data: ['组件架构', '状态管理', '交互逻辑', 'WebSocket', '样式/UI', '图表统计', '路由', '类型安全',
             '安全漏洞', 'API/数据层', '编排器', 'Agent/LLM', 'Docker', '配置管理', '数据库迁移', '测试覆盖', '前后端契约'],
      axisLabel: { color: ink, fontSize: 11 },
      axisLine: { lineStyle: { color: rule } }
    },
    series: [{
      type: 'bar',
      barWidth: '55%',
      itemStyle: {
        color: function(params) {
          var idx = params.dataIndex;
          if (idx <= 7) return accent;
          if (idx === 8) return dangerColor;
          if (idx <= 10) return warnColor;
          if (idx <= 12) return warnColor;
          return blueColor;
        }
      },
      data: [8, 6, 8, 7, 10, 7, 4, 6,
             7, 12, 8, 6,
             8, 6, 3, 5, 9]
    }]
  });
  window.addEventListener('resize', function() { chart4.resize(); });

})();
