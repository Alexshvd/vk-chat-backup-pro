const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function renderer() {
  const html = fs.readFileSync(path.join(__dirname, '../WebApp/templates/export.html'), 'utf8');
  const code = html.slice(html.indexOf('function updateVkConnectButton()'), html.indexOf('async function pollVkJob()'));
  const elements = new Map();
  function element() {
    return {style: {}, textContent: '', hidden: false, children: [],
      append(...nodes) { this.children.push(...nodes); },
      replaceChildren(...nodes) { this.children = nodes; }};
  }
  const context = vm.createContext({
    document: {createElement: element, getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    }},
    vkTerminalStates: ['complete', 'failed', 'cancelled', 'interrupted'],
    vkStopRequested: false,
    vkBrowserConnected: null,
    vkImportRunning: false,
    vkConnecting: false,
    vkDetectedBrowser: Promise.resolve({family: 'chromium', name: 'Google Chrome'}),
    setTimeout() { return 1; },
    pollVkJob() {},
  });
  vm.runInContext(code, context);
  vm.runInContext(html.slice(html.indexOf('async function checkVkBrowser()'), html.indexOf('\ncheckVkBrowser();')), context);
  return {render: context.renderVkJob, elements, context, check: context.checkVkBrowser};
}

test('early warnings stay visible after progress and are rendered as text', () => {
  const {render, elements} = renderer();
  render({state: 'complete', warnings: 1, warning_messages: ['<img src=x onerror=alert(1)>'], lines: ['Done'], chat_url: '/chat/42'});
  assert.equal(elements.get('vkJobWarnings').hidden, false);
  assert.equal(elements.get('vkJobWarningsLog').textContent, '<img src=x onerror=alert(1)>');
  assert.match(elements.get('vkJobMessage').textContent, /Предупреждений: 1/);
  assert.doesNotMatch(elements.get('vkJobMessage').textContent, /не удалось скачать/);
  assert.equal(elements.get('vkOpenChat').href, '/chat/42');
});

test('older exports explicitly explain why warning details are unavailable', () => {
  const {render, elements} = renderer();
  render({state: 'complete', warnings: 4, lines: ['Done']});
  assert.match(elements.get('vkJobWarningsLog').textContent, /не сохранены/);
  assert.match(elements.get('vkJobWarningsTitle').textContent, /4/);
});

test('next successful job hides warnings from the previous export', () => {
  const {render, elements} = renderer();
  render({state: 'complete', warnings: 1, warning_messages: ['Old warning']});
  render({state: 'complete', warnings: 0, lines: [], message: 'Готово'});
  assert.equal(elements.get('vkJobWarnings').hidden, true);
  assert.equal(elements.get('vkJobMessage').textContent, 'Готово');
});

test('recovered attachment references are safe, actionable, and cleared on the next job', () => {
  const {render, elements} = renderer();
  render({state: 'complete', warnings: 7, warning_details_legacy: true, warning_attachments: [
    {cid: 947, title: '<img onerror=alert(1)>', filename: 'Audio.Id947.md',
      url: 'https://cdn.test/music?sig=visible', message_url: '/chat/42?message=947'},
    {cid: 10, title: 'Invalid URL', url: 'javascript:alert(1)', message_url: '//foreign.test'},
  ]});
  const cards = elements.get('vkWarningAttachments').children;
  assert.equal(cards.length, 2);
  assert.equal(cards[0].children[0].textContent, 'Сообщение №947 · <img onerror=alert(1)>');
  assert.equal(cards[0].children[2].href, 'https://cdn.test/music?sig=visible');
  assert.equal(cards[0].children[4].href, '/chat/42?message=947');
  assert.equal(cards[1].children[2].href, undefined);
  assert.equal(cards[1].children[4].href, undefined);
  assert.equal(elements.get('vkWarningDetailsNote').hidden, false);
  render({state: 'complete', warnings: 0});
  assert.equal(elements.get('vkWarningAttachments').children.length, 0);
  assert.equal(elements.get('vkWarningDetailsNote').hidden, true);
});

test('connection status disables pairing and job updates cannot enable it again', async () => {
  const {render, elements, context, check} = renderer();
  context.fetch = async () => ({ok: true, json: async () => ({connected: true, browser: 'Google Chrome'})});
  await check();
  assert.equal(elements.get('vkConnect').disabled, true);
  assert.equal(elements.get('vkConnect').textContent, 'Браузер подключён');
  assert.equal(elements.get('vkQuickStart').disabled, false);
  render({state: 'downloading'});
  assert.equal(elements.get('vkQuickStart').disabled, true);
  render({state: 'complete'});
  assert.equal(elements.get('vkConnect').disabled, true);
  assert.equal(elements.get('vkQuickStart').disabled, false);
  assert.match(elements.get('vkBrowserStatus').textContent, /Google Chrome подключён/);
});

test('lost connection enables pairing only after an active import ends', async () => {
  const {render, elements, context, check} = renderer();
  context.fetch = async () => ({ok: true, json: async () => ({connected: false})});
  render({state: 'downloading'});
  await check();
  assert.equal(elements.get('vkConnect').disabled, true);
  render({state: 'failed'});
  assert.equal(elements.get('vkConnect').disabled, false);
  assert.equal(elements.get('vkConnect').textContent, 'Подключить браузер');
  assert.equal(elements.get('vkQuickStart').disabled, true);
});

test('unknown server status prevents pairing until a successful connection check', async () => {
  const {render, elements, context, check} = renderer();
  render({state: 'complete'});
  assert.equal(elements.get('vkConnect').disabled, true);
  context.fetch = async () => { throw new Error('offline'); };
  await check();
  assert.equal(elements.get('vkConnect').disabled, true);
  assert.equal(elements.get('vkBrowserStatus').textContent, 'Нет связи с приложением.');
  context.fetch = async () => ({ok: true, json: async () => ({connected: false})});
  await check();
  assert.equal(elements.get('vkConnect').disabled, false);
});

test('status polling cannot enable the pairing button during a connection attempt', async () => {
  const {elements, context, check} = renderer();
  context.vkConnecting = true;
  context.fetch = async () => ({ok: true, json: async () => ({connected: false})});
  await check();
  assert.equal(elements.get('vkConnect').disabled, true);
  assert.equal(elements.get('vkConnect').textContent, 'Подключаю браузер…');
});
