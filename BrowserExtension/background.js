const ext = typeof browser !== 'undefined' ? browser : chrome;
const LEGACY_BASE = 'http://127.0.0.1:5000';
const VK_URLS = ['https://vk.ru/*', 'https://vk.com/*', 'https://www.vk.ru/*', 'https://www.vk.com/*'];
let polling = false;
let timer;
let activeUntil = 0;
let selectedTab = null;

function localBase(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(parsed.hostname)
      && !parsed.username && !parsed.password ? parsed.origin : null;
  } catch (_) { return null; }
}

async function local(base, path, token, body) {
  const response = await fetch(base + path, {
    method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
    headers: {'Content-Type': 'application/json', ...(token ? {Authorization: 'Bearer ' + token} : {})},
    ...(body === undefined ? {} : {body: JSON.stringify(body)}), signal: AbortSignal.timeout(10000)
  });
  if (!response.ok) throw new Error('LOCAL_' + response.status);
  return response.json();
}

function peerOf(url) {
  try {
    const parsed = new URL(url);
    if (!['vk.ru', 'vk.com', 'www.vk.ru', 'www.vk.com'].includes(parsed.hostname) || parsed.protocol !== 'https:') return null;
    const match = /^\/im\/convo\/(-?\d+)\/?$/.exec(parsed.pathname);
    if (match) return Number(match[1]);
    if (!['/im', '/im/'].includes(parsed.pathname)) return null;
    const selected = parsed.searchParams.get('sel') || '';
    if (/^c\d+$/.test(selected)) return 2000000000 + Number(selected.slice(1));
    return /^-?\d+$/.test(selected) ? Number(selected) : null;
  } catch (_) { return null; }
}

async function dialogTab(peer) {
  const tabs = await ext.tabs.query({url: VK_URLS});
  const matching = tabs.find(tab => peerOf(tab.url) === peer);
  if (matching) { selectedTab = {peer, id: matching.id}; return matching; }
  // Retain our own tab while VK redirects through sign-in; never navigate a user's unrelated tab.
  if (selectedTab?.peer === peer) {
    try {
      const tab = await ext.tabs.get(selectedTab.id);
      // The browser hides the URL on the VK ID sign-in host; keep our existing tab while it redirects.
      if (!tab.url) return tab;
      if (/^https:\/\/(?:www\.)?vk\.(?:ru|com)\/feed(?:[/?#]|$)/.test(tab.url || '')) {
        return ext.tabs.update(tab.id, {url: 'https://vk.ru/im/convo/' + peer});
      }
      if (peerOf(tab.url) === peer || /^https:\/\/(?:id\.vk\.com|(?:www\.)?vk\.(?:ru|com))\//.test(tab.url || '')) return tab;
    } catch (_) {}
  }
  const tab = await ext.tabs.create({url: 'https://vk.ru/im/convo/' + peer, active: true});
  selectedTab = {peer, id: tab.id};
  return tab;
}

// The only site-side operation is reading a page of the explicitly selected conversation.
async function readHistory({peer, offset}) {
  if (location.protocol !== 'https:' || !['vk.ru', 'vk.com', 'www.vk.ru', 'www.vk.com'].includes(location.hostname)) return {waiting_login: true};
  if (typeof window.vkApi?.api !== 'function') return {waiting_login: true};
  let timeout;
  try {
    const result = await Promise.race([
      window.vkApi.api('messages.getHistory', {peer_id: peer, offset, count: 200, extended: 1, v: '5.199'}),
      new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error('timeout')), 45000); })
    ]);
    const data = result?.response ?? result;
    const code = data?.error?.error_code;
    if (code === 5 || code === 27 || code === 28) return {waiting_login: true};
    if (data?.error || !Array.isArray(data?.items)) return {error: 'ВК не вернул историю. Код: ' + (code ?? 'RESPONSE')};
    return {response: data};
  } catch (_) { return {error: 'ВК не ответил на запрос истории. Повторите загрузку.'}; }
  finally { clearTimeout(timeout); }
}

async function poll() {
  if (polling) return;
  polling = true;
  // A slow VK response must not outlive the browser's idle service-worker timer.
  const keepAlive = setInterval(() => { ext.storage.local.get('token').catch(() => {}); }, 20000);
  clearTimeout(timer);
  try {
    const {token, base: storedBase} = await ext.storage.local.get(['token', 'base']);
    if (!token) return;
    const base = localBase(storedBase || LEGACY_BASE);
    if (!base) return;
    const {command} = await local(base, '/api/vk/bridge/pending', token);
    if (command) {
      if (!/^[a-f0-9]{32}$/.test(command.job_id) || !/^[a-f0-9]{32}$/.test(command.command_id) ||
          !Number.isInteger(command.peer_id) || !command.peer_id || Math.abs(command.peer_id) > 2147483648 ||
          !Number.isInteger(command.offset) || command.offset < 0) throw new Error('Invalid command');
      activeUntil = Date.now() + 20000;
      const tab = await dialogTab(command.peer_id);
      let answer;
      if (tab.status !== 'complete' || !VK_URLS.some(pattern => (tab.url || '').startsWith(pattern.slice(0, -1)))) {
        answer = {waiting_login: true};
      } else {
        try {
          const result = await ext.scripting.executeScript({target: {tabId: tab.id}, world: 'MAIN',
            func: readHistory, args: [{peer: command.peer_id, offset: command.offset}]});
          answer = result[0]?.result || {waiting_login: true};
        } catch (_) { answer = {waiting_login: true}; }
      }
      await local(base, '/api/vk/bridge/response', token, {job_id: command.job_id, command_id: command.command_id, ...answer});
    }
  } catch (_) { /* Server may be closed; the alarm retries when it starts again. */ }
  finally {
    clearInterval(keepAlive);
    polling = false;
    if (Date.now() < activeUntil) timer = setTimeout(poll, 1000);
  }
}

ext.runtime.onMessage.addListener((message, sender, reply) => {
  const base = localBase(sender.tab?.url);
  if (!base) return false;
  if (message.type === 'pair' && /^[A-Za-z0-9_-]{43}$/.test(message.nonce)) {
    (async () => {
      try {
        const agent = typeof navigator !== 'undefined' ? navigator.userAgent : '';
        let detected = /Firefox\//.test(agent) ? 'firefox' : /Edg\//.test(agent) ? 'edge'
          : /YaBrowser\//.test(agent) ? 'yandex' : /OPR\//.test(agent) ? 'opera'
          : /Vivaldi\//.test(agent) ? 'vivaldi' : /Chrome\//.test(agent) ? 'chrome' : null;
        const {token} = await local(base, '/api/vk/bridge/pair', null, {nonce: message.nonce, browser: detected});
        await ext.storage.local.set({token, base});
        reply({ok: true});
        activeUntil = Date.now() + 20000;
        poll();
      } catch (_) { reply({ok: false}); }
    })();
    return true;
  }
  if (message.type === 'wake') {
    ext.storage.local.get(['base', 'token']).then(stored => {
      if (stored.token && base === (stored.base || LEGACY_BASE)) { activeUntil = Date.now() + 20000; poll(); }
    });
    reply({ok: true});
  }
  return false;
});
ext.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'vk-backup') poll(); });
async function ensureAlarm() {
  if (!(await ext.alarms.get('vk-backup'))) await ext.alarms.create('vk-backup', {periodInMinutes: 0.5});
}
ensureAlarm();
poll();
