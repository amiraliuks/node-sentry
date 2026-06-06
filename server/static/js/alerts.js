document.addEventListener('DOMContentLoaded', async () => {

  let alerts  = [];
  const nodes = new Set();

  function applyFilters() {
    const search   = document.getElementById('search-input').value.toLowerCase();
    const typeVal  = document.getElementById('type-filter').value;
    const nodeVal  = document.getElementById('node-filter').value;

    const filtered = [...alerts].reverse().filter(a => {
      if (typeVal && a.type !== typeVal) return false;
      if (nodeVal && a.node !== nodeVal) return false;
      if (search) {
        const hay = `${a.mac} ${a.ssid} ${a.node} ${a.vendor}`.toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });

    document.getElementById('filter-count').textContent =
      `${filtered.length} of ${alerts.length}`;

    const tbody = document.getElementById('all-alerts-body');
    if (!filtered.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="6">No alerts match the current filter.</td></tr>';
      return;
    }
    tbody.innerHTML = filtered.map(a => `
      <tr>
        <td>${fmtTime(a.timestamp)}</td>
        <td>${a.node}</td>
        <td>${typeBadge(a.type)}</td>
        <td>${fmtMac(a.mac, a.vendor)}</td>
        <td>${a.ssid || '—'}</td>
        <td>${fmtRssi(a.rssi)}</td>
      </tr>`).join('');
  }

  function addNode(node) {
    if (nodes.has(node)) return;
    nodes.add(node);
    const sel = document.getElementById('node-filter');
    const opt = document.createElement('option');
    opt.value = node;
    opt.textContent = node;
    sel.appendChild(opt);
  }

  document.getElementById('search-input').addEventListener('input', applyFilters);
  document.getElementById('type-filter').addEventListener('change', applyFilters);
  document.getElementById('node-filter').addEventListener('change', applyFilters);

  try {
    const res            = await fetch('/api/alerts?limit=500', { headers: { 'X-API-Key': API_KEY } });
    const { alerts: db } = await res.json();
    db.reverse().forEach(a => {
      alerts.push(a);
      addNode(a.node);
    });
    applyFilters();
  } catch (e) {
    console.error('[!] Failed to load alerts:', e);
  }

  socket.on('alert', data => {
    alerts.push(data);
    addNode(data.node);
    applyFilters();
  });

  document.getElementById('btn-clear-alerts').addEventListener('click', () => {
    alerts = [];
    applyFilters();
  });

});