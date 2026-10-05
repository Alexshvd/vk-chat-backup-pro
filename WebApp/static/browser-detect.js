/* Detection only: no browser launches, profile access or account data. */
(function(root) {
  function identify(userAgent, brands, brave) {
    const signature = userAgent + ' ' + (brands || []).map(item => item.brand).join(' ');
    const choices = [
      ['firefox', 'Mozilla Firefox', 'firefox', 'about:debugging#/runtime/this-firefox', /Firefox\//],
      ['edge', 'Microsoft Edge', 'chromium', 'edge://extensions', /Edg\/|Microsoft Edge/],
      ['yandex', 'Яндекс Браузер', 'chromium', 'browser://extensions', /YaBrowser\/|Yandex/],
      ['opera', 'Opera / Opera GX', 'chromium', 'opera://extensions', /OPR\/|Opera/],
      ['vivaldi', 'Vivaldi', 'chromium', 'vivaldi://extensions', /Vivaldi/],
      ['brave', 'Brave', 'chromium', 'brave://extensions', /Brave/],
      ['chrome', 'Google Chrome', 'chromium', 'chrome://extensions', /Chrome\/|Google Chrome/]
    ];
    if (brave) return {id:'brave', name:'Brave', family:'chromium', page:'brave://extensions'};
    for (const [id, name, family, page, pattern] of choices) {
      if (pattern.test(signature)) return {id, name, family, page};
    }
    if (/Chromium\//.test(signature)) return {id:'default', name:'Chromium-браузер', family:'chromium', page:'chrome://extensions'};
    return {id:'manual', name:/Safari\//.test(signature) ? 'Safari' : 'Этот браузер', family:'other', page:''};
  }
  async function detect(nav) {
    let brave = false;
    try { brave = await nav.brave?.isBrave() === true; } catch (_) {}
    return identify(nav.userAgent || '', nav.userAgentData?.brands || [], brave);
  }
  const api = {identify, detect};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.VkBrowser = api;
})(typeof window !== 'undefined' ? window : this);
