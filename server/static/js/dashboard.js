const socket = io();

// ── State ──
const state = {
  alerts: [],
  probes: [],
  nodes: {},
  counts: { total: 0, deauth: 0, evil_twin: 0, probe: 0, karma: 0 },
  timeline: [],
};

// ── Clock ──
function updateClock() {
  const now = new Date();
  document.getElementById('current-time').textContent = now.toLocaleString();
}
setInterval(updateClock, 1000);
updateClock();

// ── Nav ──
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', e => {
    e.preventDefault();
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    item.classList.add('active');
    const sec = item.dataset.section;
    document.getElementById(`section-${sec}`).classList.add('active');
    document.getElementById('page-title').textContent =
      sec.charAt(0).toUpperCase() + sec.slice(1).replace('-', ' ');
  });
});

// ── Charts ──
const typeChart = new Chart(document.getElementById('chart-types'), {
  type: 'doughnut',
  data: {
    labels: ['Deauth', 'Evil Twin', 'Probe', 'Karma'],
    datasets: [{
      data: [0, 0, 0, 0],
      backgroundColor: ['#ef4444', '#f59e0b', '#38bdf8', '#fb923c'],
      borderWidth: 0,
      hoverOffset: 6,
    }]
  },
  options: {
    responsive: true,
    plugins: {
      legend: {
        position: 'bottom',
        labels: { color: '#64748b', font: { family: 'IBM Plex Mono', size: 11 }, padding: 14 }
      }
    },
    cutout: '68%',
  }
});

const timelineChart = new Chart(document.getElementById('chart-timeline'), {
  type: 'line',
  data: {
    labels: [],
    datasets: [{
      label: 'Alerts',
      data: [],
      borderColor: '#38bdf8',
      backgroundColor: 'rgba(56,189,248,0.08)',
      borderWidth: 2,
      fill: true,
      tension: 0.4,
      pointRadius: 3,
      pointBackgroundColor: '#38bdf8',
    }]
  },
  options: {
    responsive: true,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#64748b', font: { family: 'IBM Plex Mono', size: 10 } }, grid: { color: '#1c2030' } },
      y: { ticks: { color: '#64748b', font: { family: 'IBM Plex Mono', size: 10 } }, grid: { color: '#1c2030' }, beginAtZero: true },
    }
  }
});

// ── Timeline helpers ──
const timelineBuckets = {};
function addToTimeline(ts) {
  const d = new Date(ts * 1000);
  const key = `${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
  timelineBuckets[key] = (timelineBuckets[key] || 0) + 1;
  const keys = Object.keys(timelineBuckets).slice(-15);
  timelineChart.data.labels = keys;
  timelineChart.data.datasets[0].data = keys.map(k => timelineBuckets[k]);
  timelineChart.update('none');
}

// ── Formatters ──
function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString();
}

function typeBadge(type) {
  return `<span class="type-badge type-${type}">${type.replace('_', ' ')}</span>`;
}

// ── Render tables ──
function renderRecentAlerts() {
  const tbody = document.getElementById('recent-alerts-body');
  const recent = state.alerts.slice(-20).reverse();
  if (!recent.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Waiting for alerts...</td></tr>';
    return;
  }
  tbody.innerHTML = recent.map(a => `
    <tr>
      <td>${fmtTime(a.timestamp)}</td>
      <td>${a.node}</td>
      <td>${typeBadge(a.type)}</td>
      <td>${a.mac || '—'}</td>
      <td>${a.ssid || '—'}</td>
      <td>${a.rssi ?? '—'} dBm</td>
    </tr>
  `).join('');
}

function renderAllAlerts() {
  const tbody = document.getElementById('all-alerts-body');
  const all = [...state.alerts].reverse();
  if (!all.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="6">No alerts yet.</td></tr>';
    return;
  }
  tbody.innerHTML = all.map(a => `
    <tr>
      <td>${fmtTime(a.timestamp)}</td>
      <td>${a.node}</td>
      <td>${typeBadge(a.type)}</td>
      <td>${a.mac || '—'}</td>
      <td>${a.ssid || '—'}</td>
      <td>${a.rssi ?? '—'} dBm</td>
    </tr>
  `).join('');
}

function renderProbes() {
  const tbody = document.getElementById('probe-body');
  const probes = [...state.probes].reverse();
  if (!probes.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="5">No probe requests logged yet.</td></tr>';
    return;
  }
  tbody.innerHTML = probes.map(p => `
    <tr>
      <td>${fmtTime(p.timestamp)}</td>
      <td>${p.node}</td>
      <td>${p.mac}</td>
      <td>${p.ssid || '(hidden)'}</td>
      <td>${p.rssi} dBm</td>
    </tr>
  `).join('');
}

function renderNodes() {
  const grid = document.getElementById('nodes-grid');
  const nodes = Object.values(state.nodes);
  if (!nodes.length) {
    grid.innerHTML = '<p class="empty-msg">No nodes connected yet.</p>';
    document.getElementById('stat-nodes').textContent = '0';
    return;
  }
  document.getElementById('stat-nodes').textContent = nodes.length;
  grid.innerHTML = nodes.map(n => `
    <div class="node-card">
      <div class="node-name">◎ ${n.node}</div>
      <div class="node-stat"><span>Uptime</span><span>${n.uptime}s</span></div>
      <div class="node-stat"><span>Packets seen</span><span>${n.packets_seen}</span></div>
      <div class="node-stat"><span>Alerts sent</span><span>${n.alerts_sent}</span></div>
      <div class="node-stat"><span>Free heap</span><span>${n.free_heap} B</span></div>
      <div class="node-stat"><span>RSSI to broker</span><span>${n.rssi_to_broker} dBm</span></div>
    </div>
  `).join('');
}

// ── Update stat cards ──
function updateStats() {
  document.getElementById('stat-total').textContent   = state.counts.total;
  document.getElementById('stat-deauth').textContent  = state.counts.deauth;
  document.getElementById('stat-eviltwin').textContent= state.counts.evil_twin;
  document.getElementById('stat-probe').textContent   = state.counts.probe;
  document.getElementById('stat-karma').textContent   = state.counts.karma;
  document.getElementById('total-alerts-badge').textContent = `${state.counts.total} alerts`;

  typeChart.data.datasets[0].data = [
    state.counts.deauth,
    state.counts.evil_twin,
    state.counts.probe,
    state.counts.karma,
  ];
  typeChart.update('none');
}

// ── Socket events ──
socket.on('connect', () => {
  document.getElementById('conn-dot').className = 'status-dot connected';
  document.getElementById('conn-label').textContent = 'Connected';
});

socket.on('disconnect', () => {
  document.getElementById('conn-dot').className = 'status-dot disconnected';
  document.getElementById('conn-label').textContent = 'Disconnected';
});

socket.on('alert', data => {
  state.alerts.push(data);
  state.counts.total++;
  if (state.counts[data.type] !== undefined) state.counts[data.type]++;
  if (data.type === 'probe') state.probes.push(data);
  addToTimeline(data.timestamp);
  updateStats();
  renderRecentAlerts();
  renderAllAlerts();
  renderProbes();
});

socket.on('stats', data => {
  state.nodes[data.node] = data;
  renderNodes();
});

// ── Clear alerts ──
document.getElementById('btn-clear-alerts').addEventListener('click', () => {
  state.alerts = [];
  state.probes = [];
  state.counts = { total: 0, deauth: 0, evil_twin: 0, probe: 0, karma: 0 };
  updateStats();
  renderRecentAlerts();
  renderAllAlerts();
  renderProbes();
});


// ── Load persisted data on page load ──
async function loadFromDB() {
  try {
    const [alertsRes, statsRes, nodesRes] = await Promise.all([
      fetch('/api/alerts'),
      fetch('/api/stats'),
      fetch('/api/nodes'),
    ]);

    const { alerts } = await alertsRes.json();
    const stats  = await statsRes.json();
    const nodes  = await nodesRes.json();

    // Load alerts in reverse (DB returns newest first)
    alerts.reverse().forEach(a => {
      state.alerts.push(a);
      if (a.type === 'probe') state.probes.push(a);
      addToTimeline(a.timestamp);
    });

    // Load counts from DB
    state.counts.total    = stats.total    || 0;
    state.counts.deauth   = stats.deauth   || 0;
    state.counts.evil_twin= stats.evil_twin|| 0;
    state.counts.probe    = stats.probe    || 0;
    state.counts.karma    = stats.karma    || 0;

    // Load nodes
    nodes.forEach(n => { state.nodes[n.node] = n; });

    updateStats();
    renderRecentAlerts();
    renderAllAlerts();
    renderProbes();
    renderNodes();

    console.log(`[*] Loaded ${alerts.length} alerts from DB`);
  } catch (e) {
    console.error('[!] Failed to load from DB:', e);
  }
}

loadFromDB();