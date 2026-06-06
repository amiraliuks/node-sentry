document.addEventListener('DOMContentLoaded', async () => {

  const state = {
    counts: { total: 0, deauth: 0, evil_twin: 0, probe: 0, karma: 0 },
  };

  const isDark = () => document.documentElement.getAttribute('data-theme') !== 'light';
  const gridColor  = () => isDark() ? '#1e2430' : '#e1e5ec';
  const tickColor  = () => isDark() ? '#48556a' : '#6b7585';

  const typeChart = new Chart(document.getElementById('chart-types'), {
    type: 'doughnut',
    data: {
      labels: ['Deauth', 'Evil Twin', 'Probe', 'Karma'],
      datasets: [{
        data: [0, 0, 0, 0],
        backgroundColor: ['#ff6b6b', '#ffb347', '#45ffbc', '#ffd47a'],
        borderWidth: 0,
        hoverOffset: 4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: tickColor(),
            font: { family: 'Be Vietnam Pro, sans-serif', size: 11 },
            padding: 12,
            boxWidth: 10,
          }
        }
      },
      cutout: '70%',
    }
  });

  const timelineChart = new Chart(document.getElementById('chart-timeline'), {
    type: 'bar',
    data: {
      labels: [],
      datasets: [{
        label: 'Alerts',
        data: [],
        backgroundColor: 'rgba(69,255,188,0.2)',
        borderColor: '#45ffbc',
        borderWidth: 1,
        borderRadius: 2,
        maxBarThickness: 40,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: tickColor(), font: { family: 'Be Vietnam Pro, sans-serif', size: 11 } },
          grid:  { color: gridColor() }
        },
        y: {
          ticks: { color: tickColor(), font: { family: 'Be Vietnam Pro, sans-serif', size: 11 } },
          grid:  { color: gridColor() },
          beginAtZero: true,
          suggestedMax: 5,
        },
      }
    }
  });

  const timelineBuckets = {};

  function addToTimeline(ts) {
    const d   = new Date(ts * 1000);
    const key = `${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
    timelineBuckets[key] = (timelineBuckets[key] || 0) + 1;
    const keys = Object.keys(timelineBuckets).slice(-15);
    timelineChart.data.labels = keys;
    timelineChart.data.datasets[0].data = keys.map(k => timelineBuckets[k]);
    timelineChart.update('none');
  }

  function updateStats() {
    document.getElementById('stat-total').textContent    = state.counts.total;
    document.getElementById('stat-deauth').textContent   = state.counts.deauth;
    document.getElementById('stat-eviltwin').textContent = state.counts.evil_twin;
    document.getElementById('stat-probe').textContent    = state.counts.probe;
    document.getElementById('stat-karma').textContent    = state.counts.karma;
    typeChart.data.datasets[0].data = [
      state.counts.deauth,
      state.counts.evil_twin,
      state.counts.probe,
      state.counts.karma,
    ];
    typeChart.update('none');
  }

  const alerts = [];

  function renderRecentAlerts() {
    const tbody  = document.getElementById('recent-alerts-body');
    const recent = alerts.slice(-20).reverse();
    if (!recent.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Waiting for alerts...</td></tr>';
      return;
    }
    tbody.innerHTML = recent.map(a => `
      <tr>
        <td>${fmtTime(a.timestamp)}</td>
        <td>${a.node}</td>
        <td>${typeBadge(a.type)}</td>
        <td>${fmtMac(a.mac, a.vendor)}</td>
        <td>${a.ssid || '—'}</td>
        <td>${fmtRssi(a.rssi)}</td>
      </tr>`).join('');
  }

  try {
    const [alertsRes, statsRes, nodesRes] = await Promise.all([
      fetch('/api/alerts?limit=200', { headers: { 'X-API-Key': API_KEY } }),
      fetch('/api/stats',            { headers: { 'X-API-Key': API_KEY } }),
      fetch('/api/nodes',            { headers: { 'X-API-Key': API_KEY } }),
    ]);

    const { alerts: dbAlerts } = await alertsRes.json();
    const stats                = await statsRes.json();
    const nodes                = await nodesRes.json();

    dbAlerts.reverse().forEach(a => {
      alerts.push(a);
      const d   = new Date(a.timestamp * 1000);
      const key = `${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
      timelineBuckets[key] = (timelineBuckets[key] || 0) + 1;
    });

    const keys = Object.keys(timelineBuckets).slice(-15);
    timelineChart.data.labels = keys;
    timelineChart.data.datasets[0].data = keys.map(k => timelineBuckets[k]);
    timelineChart.update('none');

    state.counts.total     = stats.total     || 0;
    state.counts.deauth    = stats.deauth    || 0;
    state.counts.evil_twin = stats.evil_twin || 0;
    state.counts.probe     = stats.probe     || 0;
    state.counts.karma     = stats.karma     || 0;

    document.getElementById('stat-nodes').textContent = nodes.length;

    updateStats();
    renderRecentAlerts();
  } catch (e) {
    console.error('[!] Failed to load dashboard data:', e);
  }

  socket.on('alert', data => {
    alerts.push(data);
    state.counts.total++;
    if (state.counts[data.type] !== undefined) state.counts[data.type]++;
    addToTimeline(data.timestamp);
    updateStats();
    renderRecentAlerts();
  });

});