const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function controls(short, long) {
  const elements = new Map();
  for (const [id, checked] of [['downloadVideo', false], ['downloadShort', short], ['downloadLong', long], ['videoChoiceHint', false]]) {
    elements.set(id, {checked, listeners: {}, addEventListener(type, listener) { this.listeners[type] = listener; }});
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../WebApp/static/settings-media.js'), 'utf8'), {
    document: {getElementById: id => elements.get(id)},
  });
  return elements;
}

test('opening settings preserves existing selective video downloads', () => {
  for (const [short, long] of [[true, false], [false, true]]) {
    const elements = controls(short, long);
    assert.equal(elements.get('downloadShort').checked, short);
    assert.equal(elements.get('downloadLong').checked, long);
    assert.equal(elements.get('downloadVideo').indeterminate, true);
    assert.match(elements.get('videoChoiceHint').textContent, /расширенных настройках/);
  }
});

test('main video switch enables or disables both duration ranges', () => {
  const elements = controls(true, false), master = elements.get('downloadVideo');
  for (const checked of [true, false]) {
    master.checked = checked; master.listeners.change();
    assert.equal(elements.get('downloadShort').checked, checked);
    assert.equal(elements.get('downloadLong').checked, checked);
    assert.equal(master.indeterminate, false);
  }
});

test('advanced video choices update the basic switch without losing selection', () => {
  const elements = controls(true, true);
  elements.get('downloadLong').checked = false;
  elements.get('downloadLong').listeners.change();
  assert.equal(elements.get('downloadVideo').indeterminate, true);
  assert.equal(elements.get('downloadShort').checked, true);
  assert.equal(elements.get('downloadLong').checked, false);
});
