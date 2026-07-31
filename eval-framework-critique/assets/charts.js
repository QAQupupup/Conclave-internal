(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var accent3 = style.getPropertyValue('--accent3').trim();
  var accent4 = style.getPropertyValue('--accent4').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // --- Chart 1: Stage Pass Rates by Model ---
  var el1 = document.getElementById('chart-stage-pass');
  if (el1) {
    var chart1 = echarts.init(el1, null, { renderer: 'svg' });
    chart1.setOption({
      animation: false,
      tooltip: {
        trigger: 'axis',
        appendToBody: true,
        formatter: function(params) {
          var s = params[0].axisValue + '<br/>';
          params.forEach(function(p) {
            s += p.marker + ' ' + p.seriesName + ': ' + (p.value * 100).toFixed(1) + '%<br/>';
          });
          return s;
        }
      },
      legend: {
        data: ['V4-Flash', 'Doubao-lite', 'Doubao-mini'],
        top: 0,
        textStyle: { color: muted, fontSize: 12 }
      },
      grid: { top: 40, right: 20, bottom: 40, left: 50 },
      xAxis: {
        type: 'category',
        data: ['clarify', 'intra_team', 'cross_team', 'evidence_check', 'arbitrate', 'produce'],
        axisLabel: { color: muted, fontSize: 11, rotate: 15 },
        axisLine: { lineStyle: { color: rule } },
        axisTick: { show: false }
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 1,
        axisLabel: {
          color: muted,
          fontSize: 11,
          formatter: function(v) { return (v * 100) + '%'; }
        },
        splitLine: { lineStyle: { color: rule, type: 'dashed' } },
        axisLine: { show: false }
      },
      series: [
        {
          name: 'V4-Flash',
          type: 'bar',
          data: [1.0, 0.889, 0.333, 0.222, 0.444, 0.889],
          itemStyle: { color: accent },
          barMaxWidth: 20
        },
        {
          name: 'Doubao-lite',
          type: 'bar',
          data: [0.75, 0.375, 0.25, 1.0, 1.0, 0.375],
          itemStyle: { color: accent4 },
          barMaxWidth: 20
        },
        {
          name: 'Doubao-mini',
          type: 'bar',
          data: [1.0, 0.667, 0.778, 0.778, 1.0, 1.0],
          itemStyle: { color: accent3 },
          barMaxWidth: 20
        }
      ]
    });
    window.addEventListener('resize', function() { chart1.resize(); });
  }

  // --- Chart 2: Heatmap per case ---
  var el2 = document.getElementById('chart-heatmap');
  if (el2) {
    var chart2 = echarts.init(el2, null, { renderer: 'svg' });
    var cases = [
      'api-gateway', 'data-warehouse', 'ecommerce-platform',
      'file-storage', 'microservices-migration', 'monitoring-alerting',
      'realtime-analytics', 'saas-pricing', 'tech-stack-research', 'user-auth'
    ];
    var models = ['V4-Flash', 'Doubao-lite R1', 'Doubao-lite R2', 'Doubao-mini'];
    // 1=PASS, 0=FAIL, -1=ERROR
    var heatData = [
      [0,0,0],[0,1,-1],[0,2,0],[0,3,1],  // api-gateway: F,T/O,F,P
      [1,0,0],[1,1,1],[1,2,0],[1,3,0],   // data-warehouse
      [2,0,0],[2,1,0],[2,2,0],[2,3,0],   // ecommerce
      [3,0,0],[3,1,0],[3,2,0],[3,3,1],   // file-storage
      [4,0,0],[4,1,0],[4,2,0],[4,3,0],   // microservices
      [5,0,0],[5,1,0],[5,2,0],[5,3,0],   // monitoring
      [6,0,0],[6,1,0],[6,2,0],[6,3,0],   // realtime
      [7,0,0],[7,1,0],[7,2,0],[7,3,1],   // saas-pricing
      [8,0,-1],[8,1,-1],[8,2,-1],[8,3,-1], // tech-stack
      [9,0,1],[9,1,0],[9,2,0],[9,3,0]    // user-auth
    ];
    var fullData = [];
    cases.forEach(function(_, yi) {
      models.forEach(function(_, xi) {
        var found = heatData.find(function(d) { return d[0] === yi && d[1] === xi; });
        if (found) {
          fullData.push(found);
        } else {
          fullData.push([yi, xi, '-']);
        }
      });
    });
    chart2.setOption({
      animation: false,
      tooltip: {
        appendToBody: true,
        formatter: function(p) {
          var v = p.value[2];
          var label = v === 1 ? 'PASS' : v === 0 ? 'FAIL' : v === -1 ? 'ERROR' : 'N/A';
          return cases[p.value[0]] + ' / ' + models[p.value[1]] + '<br/><b>' + label + '</b>';
        }
      },
      grid: { top: 20, right: 80, bottom: 80, left: 160 },
      xAxis: {
        type: 'category',
        data: models,
        axisLabel: { color: muted, fontSize: 11, rotate: 20 },
        axisLine: { lineStyle: { color: rule } },
        axisTick: { show: false },
        splitArea: { show: false }
      },
      yAxis: {
        type: 'category',
        data: cases,
        axisLabel: { color: muted, fontSize: 11 },
        axisLine: { lineStyle: { color: rule } },
        axisTick: { show: false },
        splitArea: { show: false }
      },
      visualMap: {
        min: -1,
        max: 1,
        calculable: false,
        orient: 'vertical',
        right: 10,
        top: 'center',
        inRange: {
          color: [accent2 + 'cc', '#f5f5f5', accent3]
        },
        outOfRange: { color: 'transparent' },
        textStyle: { color: muted, fontSize: 11 },
        text: ['PASS', 'ERROR'],
        pieces: [
          { value: -1, color: accent2 + 'cc', label: 'ERROR' },
          { value: 0, color: '#f0d0d0', label: 'FAIL' },
          { value: 1, color: accent3, label: 'PASS' }
        ]
      },
      series: [{
        type: 'heatmap',
        data: fullData,
        label: {
          show: true,
          fontSize: 11,
          color: ink,
          formatter: function(p) {
            var v = p.value[2];
            if (v === 1) return 'P';
            if (v === 0) return 'F';
            if (v === -1) return 'E';
            return '-';
          }
        },
        itemStyle: { borderWidth: 2, borderColor: bg2 }
      }]
    });
    window.addEventListener('resize', function() { chart2.resize(); });
  }

  // --- Chart 3: CI Width by Sample Size ---
  var el3 = document.getElementById('chart-ci');
  if (el3) {
    var chart3 = echarts.init(el3, null, { renderer: 'svg' });
    function wilsonCI(p, n, z) {
      z = z || 1.96;
      var denom = 1 + z*z/n;
      var centre = (p + z*z/(2*n)) / denom;
      var half = z * Math.sqrt((p*(1-p) + z*z/(4*n))/n) / denom;
      return [centre - half, centre + half];
    }
    var ns = [5, 10, 15, 20, 30, 50, 75, 100, 150, 200];
    var lower = [], upper = [], width = [];
    var p = 0.3;
    ns.forEach(function(n) {
      var ci = wilsonCI(p, n);
      lower.push((ci[0] * 100).toFixed(1));
      upper.push((ci[1] * 100).toFixed(1));
      width.push(((ci[1] - ci[0]) * 100).toFixed(1));
    });
    chart3.setOption({
      animation: false,
      tooltip: {
        trigger: 'axis',
        appendToBody: true,
        formatter: function(params) {
          var n = params[0].dataIndex;
          return 'n=' + ns[n] + '<br/>' +
            '95% CI: [' + lower[n] + '%, ' + upper[n] + '%]<br/>' +
            '宽度: ' + width[n] + '个百分点';
        }
      },
      grid: { top: 30, right: 20, bottom: 40, left: 60 },
      xAxis: {
        type: 'category',
        data: ns.map(String),
        name: '样本量 (n)',
        nameLocation: 'middle',
        nameGap: 28,
        nameTextStyle: { color: muted, fontSize: 12 },
        axisLabel: { color: muted, fontSize: 11 },
        axisLine: { lineStyle: { color: rule } },
        axisTick: { show: false }
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        name: 'Pass@1 (%)',
        nameTextStyle: { color: muted, fontSize: 12 },
        axisLabel: { color: muted, fontSize: 11, formatter: '{value}%' },
        splitLine: { lineStyle: { color: rule, type: 'dashed' } },
        axisLine: { show: false }
      },
      series: [
        {
          name: 'CI 上限',
          type: 'line',
          data: upper.map(Number),
          lineStyle: { color: accent, width: 1, type: 'dashed' },
          itemStyle: { color: accent },
          symbol: 'circle',
          symbolSize: 5,
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: accent + '22' },
                { offset: 1, color: accent + '08' }
              ]
            }
          }
        },
        {
          name: '点估计 (30%)',
          type: 'line',
          data: ns.map(function() { return 30; }),
          lineStyle: { color: accent4, width: 2 },
          itemStyle: { color: accent4 },
          symbol: 'none'
        },
        {
          name: 'CI 下限',
          type: 'line',
          data: lower.map(Number),
          lineStyle: { color: accent, width: 1, type: 'dashed' },
          itemStyle: { color: accent },
          symbol: 'circle',
          symbolSize: 5,
          areaStyle: {
            color: 'rgba(255,255,255,0.9)'
          }
        }
      ]
    });
    window.addEventListener('resize', function() { chart3.resize(); });
  }
})();