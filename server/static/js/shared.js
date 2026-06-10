// Shared formatters and helpers used across all pages.
//
// SECURITY: every value rendered here can originate from attacker-controlled
// input (SSIDs/MACs/node-ids arrive over RF and the MQTT broker), so anything
// interpolated into innerHTML MUST be passed through escapeHtml() first.

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function fmtMac(mac, vendor) {
  if (!mac) return '-';
  const m = escapeHtml(mac);
  return vendor
    ? `${m} <span style="color:var(--text-sub);font-size:10px">[${escapeHtml(vendor)}]</span>`
    : m;
}

function fmtRssi(rssi) {
  const r = Number(rssi);
  if (!Number.isFinite(r)) return '-';
  let cls = 'rssi-far';
  if (r >= -55) cls = 'rssi-close';
  else if (r >= -75) cls = 'rssi-medium';
  return `<span class="${cls}">${r} dBm</span>`;
}

function fmtTime(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return '-';
  // Accept both second- and millisecond-epoch timestamps.
  const ms = n > 1e12 ? n : n * 1000;
  return new Date(ms).toLocaleTimeString();
}

function fmtDate(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return '-';
  const ms = n > 1e12 ? n : n * 1000;
  return new Date(ms).toLocaleString();
}

const KNOWN_ALERT_TYPES = new Set(['deauth', 'deauth_flood', 'probe', 'evil_twin', 'karma']);

function typeBadge(type) {
  const t   = String(type ?? '');
  const cls = KNOWN_ALERT_TYPES.has(t) ? `type-${t}` : 'type-unknown';
  return `<span class="type-badge ${cls}">${escapeHtml(t.replace('_', ' '))}</span>`;
}

function fmtSeverity(score) {
  let s = Number(score);
  if (!Number.isFinite(s) || s < 1) s = 1;
  const level = s <= 3 ? 'low' : s <= 6 ? 'medium' : 'high';
  const bars  = [1, 2, 3].map(i => {
    const filled = s >= (i === 1 ? 1 : i === 2 ? 4 : 7);
    return `<span class="severity-bar ${filled ? 'filled ' + level : ''}"></span>`;
  }).join('');
  return `<span class="severity" title="Severity ${s}/10">${bars} ${s}</span>`;
}

// Trigger a client-side file download (shared by the CSV/JSON export buttons).
function downloadFile(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Render one CSV field: neutralize spreadsheet formula injection (leading
// = + - @ tab/CR) and apply RFC-4180 quoting.
function csvCell(value) {
  let s = value === null || value === undefined ? '' : String(value);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  if (/[",\r\n]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
  return s;
}
