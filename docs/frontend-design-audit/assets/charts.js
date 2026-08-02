(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var danger = style.getPropertyValue('--danger').trim();
  var warning = style.getPropertyValue('--warning').trim();

  // --- Chart: Severity distribution ---
  var chartSeverity = echarts.init(document.getElementById('chart-severity'), null, { renderer: 'svg' });
  chartSeverity.setOption({
    animation: false,
    color: [danger, accent, muted],
    tooltip: { trigger: 'item', appendToBody: true, formatter: '{b}: {c} 项 ({d}%)' },
    legend: { bottom: 0, textStyle: { color: muted } },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 4, borderColor: '#ffffff', borderWidth: 2 },
      label: { show: true, formatter: '{b}: {c}', color: ink },
      data: [
        { value: 7, name: 'P0 阻塞' },
        { value: 13, name: 'P1 重要' },
        { value: 6, name: 'P2 建议' }
      ]
    }]
  });
  window.addEventListener('resize', function() { chartSeverity.resize(); });
})();
