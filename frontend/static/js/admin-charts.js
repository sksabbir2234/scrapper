/* ═══════════════════════════════════════════════════════════════════
   GlobalNews — Admin Charts (Chart.js 4.4.0)
   Reads CSS vars for light/dark theming
   ═══════════════════════════════════════════════════════════════════ */

(function() {
  'use strict';

  // ── CSS Var Reader ──
  function getCSSVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // ── Chart.js Global Defaults ──
  function applyChartDefaults() {
    var textColor   = getCSSVar('--text-muted')   || '#9aa3a8';
    var gridColor   = getCSSVar('--border')        || '#e8e4de';
    var fontSans    = getCSSVar('--font-sans')     || '-apple-system, sans-serif';
    Chart.defaults.color = textColor;
    Chart.defaults.borderColor = gridColor;
    Chart.defaults.font.family = fontSans;
    Chart.defaults.font.size = 12;
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.animation.duration = 600;
  }

  // ── Fetch with admin auth ──
  function fetchJSON(url) {
    var token = localStorage.getItem('admin_token');
    return fetch(url, {
      headers: token ? { 'Authorization': 'Bearer ' + token } : {}
    }).then(function(r) {
      if (r.status === 401) { localStorage.removeItem('admin_token'); location.reload(); }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  // ── Chart Instances (for destroy/recreate) ──
  var charts = {};
  function destroyChart(key) {
    if (charts[key]) { charts[key].destroy(); charts[key] = null; }
  }

  // ── Show/Hide Empty State ──
  function showEmpty(id) { var el = document.getElementById(id); if (el) el.style.display = 'flex'; }
  function hideEmpty(id) { var el = document.getElementById(id); if (el) el.style.display = 'none'; }

  // ── Color Palette ──
  var colors = {
    accent:    getCSSVar('--accent')    || '#6c8ea4',
    highlight: getCSSVar('--highlight') || '#7eb8b0',
    success:   getCSSVar('--success')   || '#2d9e6b',
    warning:   getCSSVar('--warning')   || '#c97b2e',
    danger:    getCSSVar('--danger')    || '#c0392b',
    info:      getCSSVar('--info')      || '#2980b9',
  };

  var palette = [
    colors.accent, colors.highlight, colors.success,
    colors.warning, colors.info, colors.danger,
    '#8e6fc0', '#e0887c', '#5ba8a0', '#c4a35a',
    '#7a9cc6', '#b8860b'
  ];

  // ── 1. Views Line Chart ──
  window.initViewsChart = function(days) {
    days = days || 7;
    destroyChart('views');
    fetchJSON('/admin/analytics/views?days=' + days).then(function(json) {
      var data = json.data || [];
      var canvas = document.getElementById('chart-views');
      if (!canvas) return;
      var ctx = canvas.getContext('2d');

      if (data.length === 0) { showEmpty('empty-views'); canvas.style.display = 'none'; return; }
      hideEmpty('empty-views'); canvas.style.display = 'block';

      var labels = data.map(function(d) { return d.view_date.substring(5); }); // MM-DD
      charts.views = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            {
              label: 'Total Views',
              data: data.map(function(d) { return d.total_views; }),
              borderColor: colors.accent,
              backgroundColor: colors.accent + '20',
              fill: true,
              tension: 0.3,
              borderWidth: 2,
              pointRadius: 3,
              pointHoverRadius: 5,
            },
            {
              label: 'Desktop',
              data: data.map(function(d) { return d.desktop; }),
              borderColor: colors.highlight,
              borderWidth: 1.5,
              borderDash: [4, 2],
              tension: 0.3,
              pointRadius: 0,
            },
            {
              label: 'Mobile',
              data: data.map(function(d) { return d.mobile; }),
              borderColor: colors.warning,
              borderWidth: 1.5,
              borderDash: [4, 2],
              tension: 0.3,
              pointRadius: 0,
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: true, position: 'top', labels: { boxWidth: 12, padding: 15 } },
            tooltip: { mode: 'index', intersect: false },
          },
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true, grid: { color: getCSSVar('--border') } }
          },
          interaction: { mode: 'nearest', axis: 'x', intersect: false },
        }
      });
    }).catch(function() { showEmpty('empty-views'); });
  };

  // ── 2. Sources Stacked Bar ──
  window.initSourcesChart = function(days) {
    days = days || 7;
    destroyChart('sources');
    fetchJSON('/admin/analytics/sources?days=' + days).then(function(json) {
      var data = json.data || [];
      var canvas = document.getElementById('chart-sources');
      if (!canvas) return;
      var ctx = canvas.getContext('2d');

      if (data.length === 0) { showEmpty('empty-sources'); canvas.style.display = 'none'; return; }
      hideEmpty('empty-sources'); canvas.style.display = 'block';

      // Group by source name
      var sourceNames = [];
      var daySet = [];
      var sourceMap = {};
      data.forEach(function(d) {
        if (sourceNames.indexOf(d.name) === -1) sourceNames.push(d.name);
        if (daySet.indexOf(d.day) === -1) daySet.push(d.day);
        if (!sourceMap[d.name]) sourceMap[d.name] = {};
        sourceMap[d.name][d.day] = d.count;
      });
      daySet.sort();

      var datasets = sourceNames.slice(0, 8).map(function(name, i) {
        return {
          label: name,
          data: daySet.map(function(day) { return (sourceMap[name] && sourceMap[name][day]) || 0; }),
          backgroundColor: palette[i % palette.length] + 'cc',
          borderRadius: 3,
        };
      });

      charts.sources = new Chart(ctx, {
        type: 'bar',
        data: { labels: daySet.map(function(d) { return d.substring(5); }), datasets: datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: true, position: 'top', labels: { boxWidth: 10, padding: 10 } } },
          scales: {
            x: { stacked: true, grid: { display: false } },
            y: { stacked: true, beginAtZero: true }
          }
        }
      });
    }).catch(function() { showEmpty('empty-sources'); });
  };

  // ── 3. Categories Doughnut ──
  window.initCategoriesChart = function() {
    destroyChart('categories');
    fetchJSON('/admin/analytics/categories').then(function(json) {
      var data = json.data || [];
      var canvas = document.getElementById('chart-categories');
      if (!canvas) return;
      var ctx = canvas.getContext('2d');

      if (data.length === 0) { showEmpty('empty-categories'); canvas.style.display = 'none'; return; }
      hideEmpty('empty-categories'); canvas.style.display = 'block';

      charts.categories = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: data.map(function(d) { return d.name; }),
          datasets: [{
            data: data.map(function(d) { return d.count; }),
            backgroundColor: palette.slice(0, data.length),
            borderWidth: 1,
            borderColor: getCSSVar('--bg-card') || '#fff',
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '55%',
          plugins: {
            legend: { display: true, position: 'right', labels: { boxWidth: 10, padding: 8, font: { size: 11 } } },
          }
        }
      });
    }).catch(function() { showEmpty('empty-categories'); });
  };

  // ── 4. Engagement Horizontal Bar ──
  window.initEngagementChart = function(days) {
    days = days || 7;
    destroyChart('engagement');
    fetchJSON('/admin/analytics/engagement?days=' + days).then(function(json) {
      var articles = json.top_articles || [];
      var canvas = document.getElementById('chart-engagement');
      if (!canvas) return;
      var ctx = canvas.getContext('2d');

      if (articles.length === 0) { showEmpty('empty-engagement'); canvas.style.display = 'none'; return; }
      hideEmpty('empty-engagement'); canvas.style.display = 'block';

      var labels = articles.map(function(a) {
        var t = a.title || '';
        return t.length > 35 ? t.substring(0, 35) + '...' : t;
      });

      charts.engagement = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{
            data: articles.map(function(a) { return a.views; }),
            backgroundColor: colors.accent + 'cc',
            borderRadius: 4,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          indexAxis: 'y',
          plugins: { tooltip: { callbacks: { label: function(c) { return c.raw + ' views'; } } } },
          scales: {
            x: { beginAtZero: true, grid: { color: getCSSVar('--border') } },
            y: { grid: { display: false }, ticks: { font: { size: 11 } } }
          }
        }
      });
    }).catch(function() { showEmpty('empty-engagement'); });
  };

  // ── 5. Activity Feed ──
  var activityInterval = null;
  var activityPaused = false;

  window.initActivityFeed = function() {
    loadActivityFeed();
    if (activityInterval) clearInterval(activityInterval);
    activityInterval = setInterval(function() {
      if (!activityPaused) loadActivityFeed();
    }, 10000);
  };

  function loadActivityFeed() {
    fetchJSON('/admin/analytics/activity?limit=20').then(function(json) {
      var data = json.data || [];
      var feed = document.getElementById('activity-feed');
      if (!feed) return;

      if (data.length === 0) {
        feed.innerHTML = '<div class="chart-empty">No activity yet</div>';
        return;
      }

      feed.innerHTML = data.map(function(item) {
        var icon = item.type === 'article' ? 'New' : (item.status === 'error' ? 'Err' : '...');
        var typeClass = item.status === 'error' ? ' type-error' : '';
        var ago = timeAgoShort(item.ts);
        return '<div class="activity-item' + typeClass + '">' +
          '<span class="act-icon">' + icon + '</span>' +
          '<span class="act-text">' + escHTML(item.label) + '</span>' +
          '<span class="act-time">' + ago + '</span>' +
        '</div>';
      }).join('');
    }).catch(function() {});
  }

  window.toggleActivityRefresh = function() {
    activityPaused = !activityPaused;
    var btn = document.getElementById('activity-toggle');
    if (btn) btn.textContent = activityPaused ? 'OFF' : 'ON';
  };

  // ── Date Range Buttons ──
  function initDateRangeButtons() {
    document.querySelectorAll('.date-range-btns').forEach(function(group) {
      var chartName = group.getAttribute('data-chart');
      group.querySelectorAll('.date-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
          group.querySelectorAll('.date-btn').forEach(function(b) { b.classList.remove('active'); });
          btn.classList.add('active');
          var days = parseInt(btn.getAttribute('data-days'));
          if (chartName === 'views') initViewsChart(days);
          if (chartName === 'sources') initSourcesChart(days);
          if (chartName === 'engagement') initEngagementChart(days);
        });
      });
    });
  }

  // ── Master Init ──
  window.initCharts = function() {
    applyChartDefaults();
    initViewsChart(7);
    initSourcesChart(7);
    initCategoriesChart();
    initEngagementChart(7);
    initActivityFeed();
    initDateRangeButtons();
  };

  // ── Helpers ──
  function timeAgoShort(isoStr) {
    if (!isoStr) return '';
    var diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 60) return Math.floor(diff) + 's';
    if (diff < 3600) return Math.floor(diff / 60) + 'm';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h';
    return Math.floor(diff / 86400) + 'd';
  }

  function escHTML(s) {
    if (!s) return '';
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

})();
