/* Only the trusted local application can wake or pair this helper. */
const ext = typeof browser !== 'undefined' ? browser : chrome;
let pairing = false;
async function connect() {
  const nonce = location.pathname === '/browser-connect' ? location.hash.slice(1) : '';
  if (!/^[A-Za-z0-9_-]{43}$/.test(nonce) || pairing) return;
  pairing = true;
  try {
    const result = await ext.runtime.sendMessage({type: 'pair', nonce});
    window.postMessage({type: 'vk-backup-connected', ok: result?.ok === true}, location.origin);
    if (result?.ok) history.replaceState(null, '', location.pathname);
  } catch (_) {
    window.postMessage({type: 'vk-backup-connected', ok: false}, location.origin);
  } finally { pairing = false; }
}
window.addEventListener('vk-backup-wake', () => {
  ext.runtime.sendMessage({type: 'wake'}).catch(() => {});
});
window.addEventListener('vk-backup-pair', connect);
connect();
ext.runtime.sendMessage({type: 'wake'}).catch(() => {});
