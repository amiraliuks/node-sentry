document.addEventListener('DOMContentLoaded', async () => {

  let probes      = [];
  let currentPage = 1;
  let totalPages  = 1;
  const PAGE_SIZE = 50;
  const nodes     = new Set();

  function getFiltered() {
    const search  = document.getElementById('search-input').value.toLowerCase();
    const nodeVal = document.getElementById('node-filter').value;
    return probes.filter(p => {
      if (nodeVal && p.node !== nodeVal) return false;
      if (search) {
        const hay = `${p.mac} ${p.ssid} ${p.node} ${p.vendor}`.toLowerCase();
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

    document.getElementById('filter-count').textContent = `${filtered.length} probes`;

    const tbody = document.getElementById('probe-body');
    if (!page.length) {
      tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state">
        <div class="empty-state-icon">⊹</div>
        <div class="empty-state-title">No probe requests</div>
        <div class="empty-state-sub">Probe requests from nearby devices will appear here once a node is scanning.</div>
      </div></td></tr>`;
    } else {
      tbody.innerHTML = page.map(p => `
        <tr>
          <td>${fmtTime(p.timestamp)}</td>
          <td>${escapeHtml(p.node)}</td>
          <td>${fmtMac(p.mac, p.vendor)}</td>
          <td>${p.ssid ? escapeHtml(p.ssid) : '(hidden)'}</td>
          <td>${fmtRssi(p.rssi)}</td>
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

  function addNode(node) {
    if (nodes.has(node)) return;
    nodes.add(node);
    const sel = document.getElementById('node-filter');
    const opt = document.createElement('option');
    opt.value = node;
    opt.textContent = node;
    sel.appendChild(opt);
  }

  document.getElementById('search-input').addEventListener('input', () => {
    currentPage = 1;
    renderPage();
  });
  document.getElementById('node-filter').addEventListener('change', () => {
    currentPage = 1;
    renderPage();
  });

  try {
    const res            = await fetch('/api/alerts?limit=500&type=probe');
    const { alerts: db } = await res.json();
    db.reverse().forEach(p => {
      probes.push(p);
      addNode(p.node);
    });
    renderPage();
  } catch (e) {
    console.error('[!] Failed to load probes:', e);
  }

  socket.on('alert', data => {
    if (data.type === 'probe') {
      probes.push(data);
      if (probes.length > 5000) probes.splice(0, probes.length - 5000);
      addNode(data.node);
      renderPage();
    }
  });

});