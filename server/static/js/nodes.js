document.addEventListener('DOMContentLoaded', async () => {

  const nodes = {};

  function renderNodes() {
    const grid    = document.getElementById('nodes-grid');
    const entries = Object.values(nodes);
    if (!entries.length) {
      grid.innerHTML = '<p class="empty-msg">No nodes connected yet.</p>';
      return;
    }
    grid.innerHTML = entries.map(n => `
      <div class="node-card">
        <div class="node-name">◎ ${n.node}</div>
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
    data.forEach(n => { nodes[n.node] = n; });
    renderNodes();
  } catch (e) {
    console.error('[!] Failed to load nodes:', e);
  }

  // Live updates
  socket.on('stats', data => {
    nodes[data.node] = data;
    renderNodes();
  });

});