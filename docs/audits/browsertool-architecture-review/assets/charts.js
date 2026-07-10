(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var danger = style.getPropertyValue('--danger').trim();
  var warn = style.getPropertyValue('--warn').trim();

  // --- Chart: Memory Consumption ---
  var chartEl = document.getElementById('chart-memory');
  if (chartEl) {
    var chart = echarts.init(chartEl, null, { renderer: 'svg' });

    var meetings = [1, 5, 10, 15, 20, 30];
    var chromium = meetings.map(function() { return 200; });
    var contexts = meetings.map(function(m) { return m * 50; });
    var pages = meetings.map(function(m) { return m * 2 * 80; });
    var total = meetings.map(function(m, i) { return chromium[i] + contexts[i] + pages[i]; });
    var limit = meetings.map(function() { return 2048; });

    chart.setOption({
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        appendToBody: true,
        formatter: function(params) {
          var html = '并行 Meeting: ' + params[0].axisValue + '<br/>';
          params.forEach(function(p) {
            html += '<span style="color:' + p.color + '">●</span> ' + p.seriesName + ': ' + p.value + ' MB<br/>';
          });
          return html;
        }
      },
      legend: {
        data: ['Chromium 进程', 'Context 层', 'Page 层', '总内存', '2GB 上限'],
        textStyle: { color: muted, fontSize: 11 },
        top: 0
      },
      grid: { left: 50, right: 20, top: 50, bottom: 40 },
      xAxis: {
        type: 'category',
        data: meetings.map(function(m) { return m + ' 个'; }),
        axisLine: { lineStyle: { color: rule } },
        axisLabel: { color: muted, fontSize: 11 },
        name: '并行 Meeting 数',
        nameLocation: 'middle',
        nameGap: 25,
        nameTextStyle: { color: muted, fontSize: 11 }
      },
      yAxis: {
        type: 'value',
        name: '内存 (MB)',
        nameTextStyle: { color: muted, fontSize: 11 },
        axisLine: { lineStyle: { color: rule } },
        axisLabel: { color: muted, fontSize: 11 },
        splitLine: { lineStyle: { color: rule, type: 'dashed' } }
      },
      series: [
        {
          name: 'Chromium 进程',
          type: 'bar',
          stack: 'mem',
          data: chromium,
          itemStyle: { color: accent },
          barWidth: '40%'
        },
        {
          name: 'Context 层',
          type: 'bar',
          stack: 'mem',
          data: contexts,
          itemStyle: { color: accent2 }
        },
        {
          name: 'Page 层',
          type: 'bar',
          stack: 'mem',
          data: pages,
          itemStyle: { color: warn }
        },
        {
          name: '总内存',
          type: 'line',
          data: total,
          itemStyle: { color: danger },
          lineStyle: { width: 2 },
          symbol: 'circle',
          symbolSize: 6,
          z: 10
        },
        {
          name: '2GB 上限',
          type: 'line',
          data: limit,
          itemStyle: { color: muted },
          lineStyle: { type: 'dashed', width: 1.5 },
          symbol: 'none'
        }
      ]
    });

    window.addEventListener('resize', function() { chart.resize(); });
  }
})();
