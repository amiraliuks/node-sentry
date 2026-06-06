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