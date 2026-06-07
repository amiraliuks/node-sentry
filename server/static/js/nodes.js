document.addEventListener('DOMContentLoaded', async () => {

  const nodes  = {};
  const status = {};

  function statusBadge(node) {
    const s = status[node] || 'unknown';
    const color = s === 'online' ? 'var(--success)' : s === 'offline' ? 'var(--danger)' : 'var(--text-muted)';
    const label = s === 'online' ? 'Online' : s === 'offline' ? 'Offline' : 'Unknown';
    return `<span style="display:inline-flex;align-items:center;gap:5px;font-size:11px;color:${color};">
      <span style="width:6px;height:6px;border-radius:50%;background:${color};display:inline-block;"></span>
      ${label}
    </span>`;
  }

  function renderNodes() {
    const grid    = document.getElementById('nodes-grid');
    const entries = Object.values(nodes);
    if (!entries.length) {
      grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
        <div class="empty-state-icon">◎</div>
        <div class="empty-state-title">No nodes connected</div>
        <div class="empty-state-sub">Flash the firmware onto a WeMos D1 Mini Pro and connect it to the same network as the broker. Node stats will appear here automatically.</div>
      </div>`;
      return;
    }
    grid.innerHTML = entries.map(n => `
      <div class="node-card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <div class="node-name" style="margin-bottom:0;">◎ ${n.node}</div>
          ${statusBadge(n.node)}
        </div>
        <div class="node-stat"><span>Uptime</span><span>${n.uptime}s</span></div>
        <div class="node-stat"><span>Packets seen</span><span>${n.packets_seen}</span></div>
        <div class="node-stat"><span>Alerts sent</span><span>${n.alerts_sent}</span></div>
        <div class="node-stat"><span>Free heap</span><span>${n.free_heap} B</span></div>
        <div class="node-stat"><span>RSSI to broker</span><span>${fmtRssi(n.rssi_to_broker)}</span></div>
      </div>`).join('');
  }

  // Load from DB
  try {
    const res  = await fetch('/api/nodes', { headers: { 'X-API-Key': API_KEY } });
    const data = await res.json();
    data.forEach(n => {
      nodes[n.node]  = n;
      status[n.node] = n.status || 'unknown';
    });
    renderNodes();
  } catch (e) {
    console.error('[!] Failed to load nodes:', e);
  }

  // Live stats update
  socket.on('stats', data => {
    nodes[data.node] = data;
    renderNodes();
  });

  // Live status update from LWT
  socket.on('node_status', data => {
    status[data.node] = data.status;
    renderNodes();
  });

});