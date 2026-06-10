document.addEventListener('DOMContentLoaded', async () => {

  let devices     = [];
  let currentPage = 1;
  let totalPages  = 1;
  const PAGE_SIZE = 50;

  function fmtAlertTypes(types) {
    const entries = Object.entries(types).sort((a, b) => b[1] - a[1]);
    if (!entries.length) return '-';
    return `<div style="display:flex;flex-direction:column;gap:5px;">
      ${entries.map(([type, count]) => `
        <div style="display:flex;align-items:center;gap:6px;">
          ${typeBadge(type)}
          <span style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono);">${Number(count) || 0}</span>
        </div>`).join('')}
    </div>`;
  }

  function getFiltered() {
    const search = document.getElementById('search-input').value.toLowerCase();
    return devices.filter(d => {
      if (!search) return true;
      const hay = [d.mac, d.vendor || '', ...(d.ssids || []), ...(d.nodes || [])].join(' ').toLowerCase();
      return hay.includes(search);
    });
  }

  function renderPage() {
    const filtered = getFiltered();
    const start    = (currentPage - 1) * PAGE_SIZE;
    const end      = start + PAGE_SIZE;
    const page     = filtered.slice(start, end);
    totalPages     = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));

    document.getElementById('filter-count').textContent = `${filtered.length} devices`;

    const tbody = document.getElementById('devices-body');
    if (!page.length) {
      tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state">
        <div class="empty-state-icon">⊡</div>
        <div class="empty-state-title">No devices tracked</div>
        <div class="empty-state-sub">Devices appear here as alerts are received. Run the mock node or connect a sensor to start tracking.</div>
      </div></td></tr>`;
    } else {
      tbody.innerHTML = page.map(d => `
        <tr>
          <td>${fmtMac(d.mac, d.vendor)}</td>
          <td>${d.vendor ? escapeHtml(d.vendor) : '<span style="color:var(--text-muted)">Unknown</span>'}</td>
          <td style="color:var(--text-sub)">${fmtDate(d.first_seen)}</td>
          <td style="color:var(--text-sub)">${fmtDate(d.last_seen)}</td>
          <td><span style="font-family:var(--font-mono);font-weight:600">${Number(d.alert_count) || 0}</span></td>
          <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-sub)">${d.ssids.length ? d.ssids.map(escapeHtml).join(', ') : '-'}</td>
          <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-sub)">${d.nodes.map(escapeHtml).join(', ')}</td>
          <td>${fmtAlertTypes(d.alert_types)}</td>
        </tr>`).join('');
    }

    renderPagination(filtered.length);
  }

  function renderPagination(total) {
    const container = document.getElementById('pagination');
    if (!container) return;
    if (totalPages <= 1) { container.innerHTML = ''; return; }

    const start = (currentPage - 1) * PAGE_SIZE + 1;
    const end   = Math.min(currentPage * PAGE_SIZE, total);

    container.innerHTML = `
      <div class="pagination-info">${start}–${end} of ${total}</div>
      <div class="pagination-controls">
        <button class="page-btn" id="btn-prev" ${currentPage === 1 ? 'disabled' : ''}>← Prev</button>
        <span class="page-indicator">${currentPage} / ${totalPages}</span>
        <button class="page-btn" id="btn-next" ${currentPage === totalPages ? 'disabled' : ''}>Next →</button>
      </div>
    `;

    document.getElementById('btn-prev').addEventListener('click', () => {
      if (currentPage > 1) { currentPage--; renderPage(); }
    });
    document.getElementById('btn-next').addEventListener('click', () => {
      if (currentPage < totalPages) { currentPage++; renderPage(); }
    });
  }

  document.getElementById('search-input').addEventListener('input', () => {
    currentPage = 1;
    renderPage();
  });

  document.getElementById('btn-export-csv').addEventListener('click', () => {
    const headers = ['mac', 'vendor', 'first_seen', 'last_seen', 'alert_count', 'ssids', 'nodes'];
    const rows    = getFiltered().map(d =>
      headers.map(h => {
        const v = d[h];
        return csvCell(Array.isArray(v) ? v.join(';') : v);
      }).join(',')
    );
    downloadFile([headers.join(','), ...rows].join('\n'), `nodesentry-devices-${Date.now()}.csv`, 'text/csv');
  });

  document.getElementById('btn-export-json').addEventListener('click', () => {
    downloadFile(JSON.stringify(getFiltered(), null, 2), `nodesentry-devices-${Date.now()}.json`, 'application/json');
  });

  async function loadDevices() {
    try {
      const res             = await fetch('/api/devices?limit=500');
      const { devices: db } = await res.json();
      devices = db;
      renderPage();
    } catch (e) {
      console.error('[!] Failed to load devices:', e);
    }
  }

  // Trailing-edge debounce: a flood of 'alert' events triggers at most one
  // refetch every 3s instead of one /api/devices request per alert.
  let reloadTimer = null;
  function scheduleReload() {
    if (reloadTimer) return;
    reloadTimer = setTimeout(() => { reloadTimer = null; loadDevices(); }, 3000);
  }

  loadDevices();
  socket.on('alert', scheduleReload);

});