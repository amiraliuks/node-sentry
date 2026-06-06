document.addEventListener('DOMContentLoaded', async () => {

  let probes  = [];
  const nodes = new Set();

  function applyFilters() {
    const search  = document.getElementById('search-input').value.toLowerCase();
    const nodeVal = document.getElementById('node-filter').value;

    const filtered = [...probes].reverse().filter(p => {
      if (nodeVal && p.node !== nodeVal) return false;
      if (search) {
        const hay = `${p.mac} ${p.ssid} ${p.node} ${p.vendor}`.toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });

    document.getElementById('filter-count').textContent =
      `${filtered.length} of ${probes.length}`;

    const tbody = document.getElementById('probe-body');
    if (!filtered.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="5">No probe requests match the current filter.</td></tr>';
      return;
    }
    tbody.innerHTML = filtered.map(p => `
      <tr>
        <td>${fmtTime(p.timestamp)}</td>
        <td>${p.node}</td>
        <td>${fmtMac(p.mac, p.vendor)}</td>
        <td>${p.ssid || '(hidden)'}</td>
        <td>${fmtRssi(p.rssi)}</td>
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
  document.getElementById('node-filter').addEventListener('change', applyFilters);

  try {
    const res            = await fetch('/api/alerts?limit=500&type=probe', { headers: { 'X-API-Key': API_KEY } });
    const { alerts: db } = await res.json();
    db.reverse().forEach(p => {
      probes.push(p);
      addNode(p.node);
    });
    applyFilters();
  } catch (e) {
    console.error('[!] Failed to load probes:', e);
  }

  socket.on('alert', data => {
    if (data.type === 'probe') {
      probes.push(data);
      addNode(data.node);
      applyFilters();
    }
  });

});