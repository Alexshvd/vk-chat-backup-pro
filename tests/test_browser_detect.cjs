const test = require('node:test');
const assert = require('node:assert/strict');
const {detect} = require('../WebApp/static/browser-detect.js');

test('Firefox gets its own package; Chromium variants keep their extension pages', async () => {
  for (const [ua, id, family] of [
    ['Mozilla/5.0 Gecko/20100101 Firefox/143.0','firefox','firefox'],
    ['Chrome/140.0 Safari/537.36 Edg/140.0','edge','chromium'],
    ['Chrome/140.0 Safari/537.36 OPR/124.0','opera','chromium'],
    ['Chrome/140.0 YaBrowser/25.0','yandex','chromium'],
    ['Chrome/140.0 Vivaldi/7.0','vivaldi','chromium'],
    ['Chrome/140.0 Safari/537.36','chrome','chromium']
  ]) {
    const result = await detect({userAgent:ua});
    assert.equal(result.id,id);
    assert.equal(result.family,family);
    assert.ok(result.page);
  }
});
test('client-hint brand identifies Edge even with a generic Chrome user agent', async () => {
  const result = await detect({userAgent:'Chrome/140.0 Safari/537.36',userAgentData:{brands:[{brand:'Chromium'}, {brand:'Microsoft Edge'}]}});
  assert.equal(result.id,'edge');
});
test('Brave uses its browser API when its user agent only says Chrome', async () => {
  const result = await detect({userAgent:'Chrome/140.0',brave:{isBrave:async()=>true}});
  assert.equal(result.id,'brave');
  assert.equal(result.page,'brave://extensions');
});
test('a failed optional Brave API does not break detection', async () => {
  const result = await detect({userAgent:'Chrome/140.0',brave:{isBrave:async()=>{throw Error('unavailable');}}});
  assert.equal(result.id,'chrome');
});
test('Safari and unknown browsers get manual JSON instead of Chromium instructions', async () => {
  for (const userAgent of ['Version/26.0 Safari/605.1.15', '', 'OtherBrowser/1.0']) {
    const result = await detect({userAgent});
    assert.equal(result.family,'other');
    assert.equal(result.id,'manual');
    assert.equal(result.page,'');
  }
});
