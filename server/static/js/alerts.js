document.addEventListener('DOMContentLoaded', async () => {

  let allAlerts  = [];
  let currentPage = 1;
  let totalPages  = 1;
  const PAGE_SIZE = 50;
  const nodes     = new Set();

  function getFiltered() {
    const search  = document.getElementById('search-input').value.toLowerCase();
    const typeVal = document.getElementById('type-filter').value;
    const nodeVal = document.getElementById('node-filter').value;
    return allAlerts.filter(a => {
      if (typeVal && a.type !== typeVal) return false;
      if (nodeVal && a.node !== nodeVal) return false;
      if (search) {
        const hay = `${a.mac} ${a.ssid} ${a.node} ${a.vendor}`.toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });
  }

  function renderPage() {
    const filtered = getFiltered();
    const start    = (currentPage - 1) * PAGE_SIZE;
    const end      = start + PAGE_SIZE;
    const page     = filtered.slice(start, end);
    totalPages     = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));

    document.getElementById('filter-count').textContent =
      `${filtered.length} alerts`;

    const tbody = document.getElementById('all-alerts-body');
    if (!page.length) {
      tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state">
        <div class="empty-state-icon">⚑</div>
        <div class="empty-state-title">No alerts</div>
        <div class="empty-state-sub">No alerts match the current filter. Try adjusting your search or run the mock node to generate data.</div>
      </div></td></tr>`;
    } else {
      tbody.innerHTML = page.map(a => `
        <tr>
          <td>${fmtTime(a.timestamp)}</td>
          <td>${escapeHtml(a.node)}</td>
          <td>${typeBadge(a.type)}</td>
          <td>${fmtMac(a.mac, a.vendor)}</td>
          <td>${a.ssid ? escapeHtml(a.ssid) : '-'}</td>
          <td>${fmtRssi(a.rssi)}</td>
          <td>${fmtSeverity(a.severity)}</td>
        </tr>`).join('');
    }

    renderPagination(filtered.length);
  }

  function renderPagination(total) {
    const container = document.getElementById('pagination');
    if (!container) return;

    if (totalPages <= 1) {
      container.innerHTML = '';
      return;
    }

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

  function addNode(node) {
    if (nodes.has(node)) return;
    nodes.add(node);
    const sel = document.getElementById('node-filter');
    const opt = document.createElement('option');
    opt.value = node;
    opt.textContent = node;
    sel.appendChild(opt);
  }

  function onFilterChange() {
    currentPage = 1;
    renderPage();
  }

  document.getElementById('search-input').addEventListener('input', onFilterChange);
  document.getElementById('type-filter').addEventListener('change', onFilterChange);
  document.getElementById('node-filter').addEventListener('change', onFilterChange);

  document.getElementById('btn-export-csv').addEventListener('click', () => {
    const data    = getFiltered();
    const headers = ['timestamp', 'node', 'type', 'mac', 'vendor', 'ssid', 'rssi', 'severity'];
    const rows    = data.map(a => headers.map(h => csvCell(a[h])).join(','));
    downloadFile([headers.join(','), ...rows].join('\n'), `nodesentry-alerts-${Date.now()}.csv`, 'text/csv');
  });

  document.getElementById('btn-export-json').addEventListener('click', () => {
    downloadFile(JSON.stringify(getFiltered(), null, 2), `nodesentry-alerts-${Date.now()}.json`, 'application/json');
  });

  document.getElementById('btn-clear-alerts').addEventListener('click', () => {
    allAlerts = [];
    currentPage = 1;
    renderPage();
  });

  try {
    const res            = await fetch('/api/alerts?limit=500');
    const { alerts: db } = await res.json();
    db.reverse().forEach(a => {
      allAlerts.push(a);
      addNode(a.node);
    });
    renderPage();
  } catch (e) {
    console.error('[!] Failed to load alerts:', e);
  }

  socket.on('alert', data => {
    allAlerts.push(data);
    if (allAlerts.length > 5000) allAlerts.splice(0, allAlerts.length - 5000);
    addNode(data.node);
    renderPage();
  });

});