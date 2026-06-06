// Shared formatters used across all pages

function fmtMac(mac, vendor) {
  if (!mac) return '—';
  return vendor
    ? `${mac} <span style="color:var(--text-sub);font-size:10px">[${vendor}]</span>`
    : mac;
}

function fmtRssi(rssi) {
  if (rssi === null || rssi === undefined) return '—';
  let cls = 'rssi-far';
  if (rssi >= -55) cls = 'rssi-close';
  else if (rssi >= -75) cls = 'rssi-medium';
  return `<span class="${cls}">${rssi} dBm</span>`;
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString();
}

function typeBadge(type) {
  return `<span class="type-badge type-${type}">${type.replace('_', ' ')}</span>`;
}

function fmtSeverity(score) {
  if (!score) score = 1;
  const level = score <= 3 ? 'low' : score <= 6 ? 'medium' : 'high';
  const bars  = [1,2,3].map(i => {
    const filled = score >= (i === 1 ? 1 : i === 2 ? 4 : 7);
    return `<span class="severity-bar ${filled ? 'filled ' + level : ''}"></span>`;
  }).join('');
  return `<span class="severity" title="Severity ${score}/10">${bars} ${score}</span>`;
}