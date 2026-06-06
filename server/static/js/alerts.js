document.addEventListener('DOMContentLoaded', async () => {

  let alerts  = [];
  const nodes = new Set();

  function applyFilters() {
    const search  = document.getElementById('search-input').value.toLowerCase();
    const typeVal = document.getElementById('type-filter').value;
    const nodeVal = document.getElementById('node-filter').value;

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

  function getFiltered() {
    const search  = document.getElementById('search-input').value.toLowerCase();
    const typeVal = document.getElementById('type-filter').value;
    const nodeVal = document.getElementById('node-filter').value;
    return [...alerts].reverse().filter(a => {
      if (typeVal && a.type !== typeVal) return false;
      if (nodeVal && a.node !== nodeVal) return false;
      if (search) {
        const hay = `${a.mac} ${a.ssid} ${a.node} ${a.vendor}`.toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });
  }

  function downloadFile(content, filename, mime) {
    const blob = new Blob([content], { type: mime });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  document.getElementById('search-input').addEventListener('input', applyFilters);
  document.getElementById('type-filter').addEventListener('change', applyFilters);
  document.getElementById('node-filter').addEventListener('change', applyFilters);

  document.getElementById('btn-export-csv').addEventListener('click', () => {
    const data    = getFiltered();
    const headers = ['timestamp', 'node', 'type', 'mac', 'vendor', 'ssid', 'rssi'];
    const rows    = data.map(a => headers.map(h => JSON.stringify(a[h] ?? '')).join(','));
    downloadFile([headers.join(','), ...rows].join('\n'), `nodesentry-alerts-${Date.now()}.csv`, 'text/csv');
  });

  document.getElementById('btn-export-json').addEventListener('click', () => {
    downloadFile(JSON.stringify(getFiltered(), null, 2), `nodesentry-alerts-${Date.now()}.json`, 'application/json');
  });

  document.getElementById('btn-clear-alerts').addEventListener('click', () => {
    alerts = [];
    applyFilters();
  });

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

});