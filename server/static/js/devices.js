document.addEventListener('DOMContentLoaded', async () => {

  let devices = [];

  function fmtDate(ts) {
    if (!ts) return '-';
    return new Date(ts * 1000).toLocaleString();
  }

  function fmtAlertTypes(types) {
    return Object.entries(types)
      .sort((a, b) => b[1] - a[1])
      .map(([type, count]) => `${typeBadge(type)} <span style="color:var(--text-muted);font-size:11px">${count}</span>`)
      .join(' ');
  }

  function applyFilters() {
    const search = document.getElementById('search-input').value.toLowerCase();

    const filtered = devices.filter(d => {
      if (!search) return true;
      const hay = [d.mac, d.vendor || '', ...(d.ssids || []), ...(d.nodes || [])].join(' ').toLowerCase();
      return hay.includes(search);
    });

    document.getElementById('filter-count').textContent = `${filtered.length} of ${devices.length} devices`;

    const tbody = document.getElementById('devices-body');
    if (!filtered.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="8">No devices match the current filter.</td></tr>';
      return;
    }

    tbody.innerHTML = filtered.map(d => `
      <tr>
        <td>${fmtMac(d.mac, d.vendor)}</td>
        <td>${d.vendor || '<span style="color:var(--text-muted)">Unknown</span>'}</td>
        <td style="color:var(--text-sub)">${fmtDate(d.first_seen)}</td>
        <td style="color:var(--text-sub)">${fmtDate(d.last_seen)}</td>
        <td><span style="font-family:var(--font-mono);font-weight:600">${d.alert_count}</span></td>
        <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-sub)">${d.ssids.length ? d.ssids.join(', ') : '-'}</td>
        <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-sub)">${d.nodes.join(', ')}</td>
        <td>${fmtAlertTypes(d.alert_types)}</td>
      </tr>`).join('');
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

  document.getElementById('btn-export-csv').addEventListener('click', () => {
    const headers = ['mac', 'vendor', 'first_seen', 'last_seen', 'alert_count', 'ssids', 'nodes'];
    const rows    = devices.map(d =>
      headers.map(h => {
        const v = d[h];
        return JSON.stringify(Array.isArray(v) ? v.join(';') : (v ?? ''));
      }).join(',')
    );
    downloadFile([headers.join(','), ...rows].join('\n'), `nodesentry-devices-${Date.now()}.csv`, 'text/csv');
  });

  document.getElementById('btn-export-json').addEventListener('click', () => {
    downloadFile(JSON.stringify(devices, null, 2), `nodesentry-devices-${Date.now()}.json`, 'application/json');
  });

  async function loadDevices() {
    try {
      const res             = await fetch('/api/devices?limit=500', { headers: { 'X-API-Key': API_KEY } });
      const { devices: db } = await res.json();
      devices = db;
      applyFilters();
    } catch (e) {
      console.error('[!] Failed to load devices:', e);
    }
  }

  loadDevices();

  socket.on('alert', () => loadDevices());

});