const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../BrowserExtension/background.js'), 'utf8');

function helper(tabs, command, namespace = 'chrome') {
  let handler;
  let storage = {};
  const requests = [], api = [], created = [], execution = [];
  let finish;
  const answered = new Promise(resolve => { finish = resolve; });
  const chrome = {
    storage: {local: {get: async () => storage, set: async data => { storage = data; }}},
    tabs: {
      query: async () => tabs,
      get: async id => tabs.find(tab => tab.id === id),
      create: async options => { created.push(options); return {id: 99, url: options.url, status: 'complete'}; }
    },
    scripting: {executeScript: async options => {
      execution.push(options);
      return [{result: await options.func(...options.args)}];
    }},
    runtime: {onMessage: {addListener: fn => { handler = fn; }}},
    alarms: {onAlarm: {addListener: () => {}}, get: async () => null, create: async () => {}}
  };
  const context = vm.createContext({[namespace]: chrome, URL, AbortSignal, Date,
    navigator: {userAgent: namespace === 'browser' ? 'Firefox/128.0' : 'Chrome/145.0'},
    setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 2, clearInterval: () => {},
    location: {protocol: 'https:', hostname: 'vk.ru'},
    window: {vkApi: {api: async (method, args) => {
      api.push({method, args});
      return {response: {count: 1, items: [{conversation_message_id: 1}]}};
    }}},
    fetch: async (url, options) => {
      requests.push({url, options});
      let data;
      if (url.endsWith('/pair')) data = {token: 'local-test-token'};
      else if (url.endsWith('/pending')) data = {command};
      else {
        data = {ok: true};
        finish(JSON.parse(options.body));
      }
      return {ok: true, json: async () => data};
    }
  });
  vm.runInContext(source, context);
  return {answered, requests, created, execution, api, send: (...args) => handler(...args)};
}

test('uses the existing VK tab and current session, returning only the selected history to localhost', async () => {
  const command = {job_id: 'a'.repeat(32), command_id: 'b'.repeat(32), peer_id: 42, offset: 200};
  const instance = helper([{id: 7, url: 'https://vk.ru/im/convo/42?entrypoint=list_all', status: 'complete'}], command);
  await new Promise(setImmediate);
  await new Promise(resolve => instance.send({type: 'pair', nonce: 'n'.repeat(43)}, {tab: {url: 'http://127.0.0.1:5000/browser-connect'}}, resolve));
  const answer = await instance.answered;
  assert.equal(instance.created.length, 0);
  assert.equal(instance.execution[0].target.tabId, 7);
  assert.equal(instance.execution[0].world, 'MAIN');
  assert.deepEqual(instance.api.map(call => call.method), ['messages.getHistory']);
  assert.equal(instance.api[0].args.peer_id, 42);
  assert.equal(instance.api[0].args.offset, 200);
  assert.equal(answer.job_id, command.job_id);
  assert.equal(answer.command_id, command.command_id);
  assert.equal(answer.response.items.length, 1);
  assert(instance.requests.every(request => request.url.startsWith('http://127.0.0.1:5000/')));
  assert.equal(instance.requests.at(-1).options.headers.Authorization, 'Bearer local-test-token');
});

test('opens a Chrome tab for a new conversation without changing the unrelated existing tab', async () => {
  const instance = helper([{id: 8, url: 'https://vk.com/im/convo/999', status: 'complete'}],
    {job_id: 'a'.repeat(32), command_id: 'b'.repeat(32), peer_id: 42, offset: 0});
  await new Promise(setImmediate);
  instance.send({type: 'pair', nonce: 'n'.repeat(43)}, {tab: {url: 'http://127.0.0.1:5000/browser-connect'}}, () => {});
  await instance.answered;
  assert.equal(instance.created.length, 1);
  assert.equal(instance.created[0].url, 'https://vk.ru/im/convo/42');
  assert.equal(instance.execution[0].target.tabId, 99);
});

test('ignores requests to pair or wake from foreign sites', async () => {
  const instance = helper([], null);
  await new Promise(setImmediate);
  assert.equal(instance.send({type: 'pair', nonce: 'n'.repeat(43)}, {tab: {url: 'https://foreign.test'}}, () => {}), false);
  assert.equal(instance.requests.length, 0);
});

test('Firefox namespace reads the same history and uses the paired port instead of 5000', async () => {
  const instance = helper([{id: 7, url: 'https://vk.ru/im/convo/42', status: 'complete'}],
    {job_id: 'a'.repeat(32), command_id: 'b'.repeat(32), peer_id: 42, offset: 0}, 'browser');
  await new Promise(setImmediate);
  await new Promise(resolve => instance.send({type: 'pair', nonce: 'n'.repeat(43)}, {tab: {url: 'http://127.0.0.1:8080/browser-connect'}}, resolve));
  await instance.answered;
  assert(instance.requests.every(request => request.url.startsWith('http://127.0.0.1:8080/')));
  assert.equal(JSON.parse(instance.requests[0].options.body).browser, 'firefox');
  assert.equal(instance.execution[0].world, 'MAIN');
});

test('refuses similarly named foreign origins and URLs containing credentials', async () => {
  const instance = helper([], null, 'browser');
  await new Promise(setImmediate);
  for (const url of ['http://127.0.0.1.evil.test:8080/browser-connect', 'http://localhost.evil.test/browser-connect',
    'http://localhost@evil.test/browser-connect', 'https://localhost/browser-connect']) {
    assert.equal(instance.send({type: 'pair', nonce: 'n'.repeat(43)}, {tab: {url}}, () => {}), false);
  }
  assert.equal(instance.requests.length, 0);
});
