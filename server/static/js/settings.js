document.addEventListener('DOMContentLoaded', async () => {

  let currentConfig = {};

  async function loadSettings() {
    try {
      const res     = await fetch('/api/config', { headers: { 'X-API-Key': API_KEY } });
      currentConfig = await res.json();

      document.getElementById('tg-enabled').checked  = currentConfig.notifications.telegram.enabled;
      document.getElementById('tg-token').value       = currentConfig.notifications.telegram.bot_token;
      document.getElementById('tg-chatid').value      = currentConfig.notifications.telegram.chat_id;

      document.getElementById('dc-enabled').checked  = currentConfig.notifications.discord.enabled;
      document.getElementById('dc-webhook').value     = currentConfig.notifications.discord.webhook_url;

      document.getElementById('th-deauth-count').value  = currentConfig.thresholds.deauth_count;
      document.getElementById('th-deauth-window').value = currentConfig.thresholds.deauth_window_seconds;
      document.getElementById('th-cooldown').value      = currentConfig.thresholds.cooldown_seconds;

      renderWhitelist(currentConfig.whitelist || []);
    } catch (e) {
      console.error('[!] Failed to load settings:', e);
    }
  }

  function renderWhitelist(entries) {
    const container = document.getElementById('whitelist-entries');
    if (!entries.length) {
      container.innerHTML = '<p class="empty-msg" style="margin-top:8px">No whitelisted MACs.</p>';
      return;
    }
    container.innerHTML = entries.map(mac => `
      <div class="whitelist-entry">
        <span>${mac}</span>
        <button class="whitelist-remove" data-mac="${mac}">✕</button>
      </div>
    `).join('');
    container.querySelectorAll('.whitelist-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        currentConfig.whitelist = currentConfig.whitelist.filter(m => m !== btn.dataset.mac);
        renderWhitelist(currentConfig.whitelist);
      });
    });
  }

  document.getElementById('btn-add-mac').addEventListener('click', () => {
    const input = document.getElementById('whitelist-input');
    const mac   = input.value.trim().toUpperCase();
    if (!mac) return;
    if (!currentConfig.whitelist) currentConfig.whitelist = [];
    if (!currentConfig.whitelist.includes(mac)) {
      currentConfig.whitelist.push(mac);
      renderWhitelist(currentConfig.whitelist);
    }
    input.value = '';
  });

  document.getElementById('btn-save-settings').addEventListener('click', async () => {
    const result = document.getElementById('save-result');

    currentConfig.notifications.telegram.enabled   = document.getElementById('tg-enabled').checked;
    currentConfig.notifications.telegram.bot_token = document.getElementById('tg-token').value.trim();
    currentConfig.notifications.telegram.chat_id   = document.getElementById('tg-chatid').value.trim();

    currentConfig.notifications.discord.enabled     = document.getElementById('dc-enabled').checked;
    currentConfig.notifications.discord.webhook_url = document.getElementById('dc-webhook').value.trim();

    currentConfig.thresholds.deauth_count          = parseInt(document.getElementById('th-deauth-count').value);
    currentConfig.thresholds.deauth_window_seconds = parseInt(document.getElementById('th-deauth-window').value);
    currentConfig.thresholds.cooldown_seconds      = parseInt(document.getElementById('th-cooldown').value);

    try {
      const res  = await fetch('/api/config', {
        method:  'POST',
        headers: { 'X-API-Key': API_KEY, 'Content-Type': 'application/json' },
        body:    JSON.stringify(currentConfig),
      });
      const data = await res.json();
      result.className   = 'test-result';
      result.textContent = data.success ? 'Settings saved.' : 'Failed to save.';
    } catch (e) {
      result.className   = 'test-result error';
      result.textContent = 'Error saving settings.';
    }
    setTimeout(() => { result.textContent = ''; }, 3000);
  });

  document.getElementById('btn-test-telegram').addEventListener('click', async () => {
    const result = document.getElementById('tg-result');
    result.className   = 'test-result';
    result.textContent = 'Sending...';
    try {
      const res  = await fetch('/api/config/test/telegram', {
        method: 'POST', headers: { 'X-API-Key': API_KEY },
      });
      const data = await res.json();
      result.textContent = data.success ? 'Message sent!' : 'Failed - check token and chat ID.';
      if (!data.success) result.className = 'test-result error';
    } catch (e) {
      result.className   = 'test-result error';
      result.textContent = 'Request failed.';
    }
    setTimeout(() => { result.textContent = ''; }, 4000);
  });

  document.getElementById('btn-test-discord').addEventListener('click', async () => {
    const result = document.getElementById('dc-result');
    result.className   = 'test-result';
    result.textContent = 'Sending...';
    try {
      const res  = await fetch('/api/config/test/discord', {
        method: 'POST', headers: { 'X-API-Key': API_KEY },
      });
      const data = await res.json();
      result.textContent = data.success ? 'Message sent!' : 'Failed - check webhook URL.';
      if (!data.success) result.className = 'test-result error';
    } catch (e) {
      result.className   = 'test-result error';
      result.textContent = 'Request failed.';
    }
    setTimeout(() => { result.textContent = ''; }, 4000);
  });

  loadSettings();

});