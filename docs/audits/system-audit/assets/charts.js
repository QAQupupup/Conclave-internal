(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var bg = style.getPropertyValue('--bg').trim();
  var danger = '#e74c3c';
  var warn = '#f39c12';
  var ok = '#27ae60';

  // --- Chart 1: 问题严重程度分布 ---
  var c1 = echarts.init(document.getElementById('chart-severity'), null, { renderer: 'svg' });
  c1.setOption({
    animation: false,
    tooltip: { appendToBody: true, trigger: 'item', formatter: '{b}: {c}个 ({d}%)' },
    legend: { bottom: 0, textStyle: { color: muted } },
    color: [danger, '#e67e22', warn, '#3498db', ok],
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 6, borderColor: bg, borderWidth: 2 },
      label: { show: true, formatter: '{b}\n{c}个', color: ink, fontSize: 12 },
      labelLine: { lineStyle: { color: rule } },
      data: [
        { value: 1, name: 'P0 阻断' },
        { value: 12, name: 'P1 严重' },
        { value: 18, name: 'P2 中等' },
        { value: 12, name: 'P3 低/质量' },
        { value: 10, name: '优化建议' }
      ]
    }]
  });

  // --- Chart 2: 问题分类分布 ---
  var c2 = echarts.init(document.getElementById('chart-category'), null, { renderer: 'svg' });
  c2.setOption({
    animation: false,
    tooltip: { appendToBody: true, trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 120, right: 30, top: 20, bottom: 30 },
    xAxis: { type: 'value', axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    yAxis: {
      type: 'category',
      axisLabel: { color: ink, fontSize: 12 },
      axisLine: { lineStyle: { color: rule } },
      data: ['前端缺失/死代码', '事件契约不一致', '架构/理念冲突', '状态机/流程bug', '资源泄漏/并发', 'WebSocket/通信', '安全加固遗留', '代码质量/死代码']
    },
    series: [{
      type: 'bar',
      data: [
        { value: 9, itemStyle: { color: accent } },
        { value: 8, itemStyle: { color: accent2 } },
        { value: 7, itemStyle: { color: '#8e44ad' } },
        { value: 7, itemStyle: { color: danger } },
        { value: 6, itemStyle: { color: warn } },
        { value: 5, itemStyle: { color: '#e67e22' } },
        { value: 5, itemStyle: { color: '#3498db' } },
        { value: 6, itemStyle: { color: ok } }
      ],
      barWidth: 18,
      itemStyle: { borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: 'right', color: ink, fontSize: 12, formatter: '{c}' }
    }]
  });

  // --- Chart 3: 前后端问题分布 ---
  var c3 = echarts.init(document.getElementById('chart-febe'), null, { renderer: 'svg' });
  c3.setOption({
    animation: false,
    tooltip: { appendToBody: true, trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: muted } },
    color: [accent, accent2, '#95a5a6'],
    series: [{
      type: 'pie',
      radius: '65%',
      center: ['50%', '45%'],
      itemStyle: { borderRadius: 4, borderColor: bg, borderWidth: 2 },
      label: { color: ink, formatter: '{b}: {c}个' },
      data: [
        { value: 29, name: '后端' },
        { value: 18, name: '前端' },
        { value: 6, name: '前后端交互' }
      ]
    }]
  });

  // --- Chart 4: 各阶段发现问题数 ---
  var c4 = echarts.init(document.getElementById('chart-area'), null, { renderer: 'svg' });
  c4.setOption({
    animation: false,
    tooltip: { appendToBody: true, trigger: 'axis' },
    legend: { bottom: 0, textStyle: { color: muted } },
    grid: { left: 50, right: 20, top: 40, bottom: 60 },
    xAxis: {
      type: 'category',
      data: ['状态机', '并发/资源', '事件总线', '数据访问', 'WebSocket', '安全/沙箱', '记忆子系统', '前端面板', '前端状态', 'UI/UX'],
      axisLabel: { color: muted, rotate: 30, fontSize: 11 },
      axisLine: { lineStyle: { color: rule } }
    },
    yAxis: { type: 'value', axisLabel: { color: muted }, splitLine: { lineStyle: { color: rule } } },
    series: [
      {
        name: 'P0/P1',
        type: 'bar',
        stack: 'total',
        data: [3, 3, 2, 2, 3, 1, 0, 2, 3, 0],
        itemStyle: { color: danger },
        barWidth: 28
      },
      {
        name: 'P2',
        type: 'bar',
        stack: 'total',
        data: [2, 2, 2, 1, 1, 2, 2, 3, 2, 1],
        itemStyle: { color: warn }
      },
      {
        name: 'P3/优化',
        type: 'bar',
        stack: 'total',
        data: [2, 1, 0, 2, 1, 2, 3, 4, 3, 4],
        itemStyle: { color: ok }
      }
    ]
  });

  window.addEventListener('resize', function() {
    c1.resize(); c2.resize(); c3.resize(); c4.resize();
  });
})();
