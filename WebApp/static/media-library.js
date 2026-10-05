function filterMedia(items, type, query) {
  const needle = query.trim().toLocaleLowerCase('ru');
  return items.filter(item => (type === 'all' || item.type === type) && (!needle ||
    [item.title, item.filename, ...(item.messages || []).map(message => String(message.cid))]
      .join(' ').toLocaleLowerCase('ru').includes(needle)));
}

function mediaSize(bytes) {
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let index = 0;
  while (bytes >= 1024 && index < units.length - 1) { bytes /= 1024; index++; }
  return new Intl.NumberFormat('ru-RU', {maximumFractionDigits: index ? 1 : 0}).format(bytes) + ' ' + units[index];
}

if (typeof module !== 'undefined') module.exports = {filterMedia, mediaSize};
if (typeof document !== 'undefined') {
  const peer = document.getElementById('mediaLibrary').dataset.peer;
  const grid = document.getElementById('mediaGrid'), search = document.getElementById('mediaSearch');
  const empty = document.getElementById('mediaEmpty'), more = document.getElementById('mediaMore');
  const filters = [...document.querySelectorAll('.filter')], refresh = document.getElementById('mediaRefresh');
  const box = document.getElementById('mediaLightbox'), photo = document.getElementById('mediaPhoto');
  const typeNames = {all: 'Все', photo: 'Фото', video: 'Видео', audio: 'Аудио', file: 'Документы'};
  const date = new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'short', year:'numeric'});
  let items = [], selected = 'all', limit = 60, loading = false, searchTimer;
  function el(tag, className, text) {
    const node = document.createElement(tag); if (className) node.className = className;
    if (text !== undefined) node.textContent = text; return node;
  }
  function showPhoto(item) {
    photo.src = item.src; photo.alt = item.title;
    document.getElementById('photoTitle').textContent = item.title;
    document.getElementById('photoOriginal').href = item.src;
    box.showModal();
  }
  function card(item) {
    const node = el('article', 'card'), preview = el('div', 'preview');
    if (item.type === 'photo') {
      const button = el('button', 'photo-button'); button.setAttribute('aria-label', 'Открыть фото: ' + item.title);
      const image = el('img'); image.src = item.src; image.alt = item.title; image.loading = 'lazy'; image.decoding = 'async';
      image.onerror = () => { button.replaceChildren(el('span', '', 'Превью недоступно')); };
      button.append(image); button.onclick = () => showPhoto(item); preview.append(button);
    } else if (item.type === 'video' || item.type === 'audio') {
      const player = el(item.type); player.controls = true; player.preload = 'none'; player.src = item.src;
      if (item.type === 'video') { player.playsInline = true; if (item.poster) player.poster = item.poster; }
      preview.append(player);
    } else {
      preview.append(el('span', 'file-icon', item.filename.split('.').at(-1).toUpperCase().slice(0, 8)));
    }
    const body = el('div', 'body'); body.append(el('div', 'title', item.title));
    if (item.title !== item.filename) {
      const details = el('details', 'file-details'); details.append(el('summary', '', 'Сведения о файле'), el('div', 'filename', item.filename)); body.append(details);
    }
    const meta = el('div', 'meta'); meta.append(el('span', '', mediaSize(item.size)));
    if (item.date) meta.append(el('span', '', date.format(new Date(item.date * 1000))));
    if (item.shared) meta.append(el('span', 'badge', 'Общий файл'));
    body.append(meta);
    const uses = item.messages || [], actions = el('div', 'actions');
    const fileLink = el('a', '', 'Открыть файл'); fileLink.href = item.src; fileLink.target = '_blank'; fileLink.rel = 'noopener'; actions.append(fileLink);
    if (uses.length === 1) {
      const link = el('a', '', 'Сообщение №' + uses[0].cid); link.href = uses[0].url; actions.append(link);
    } else if (uses.length > 1) {
      const details = el('details', 'uses'); details.append(el('summary', '', 'В сообщениях: ' + uses.length));
      for (const message of uses) { const link = el('a', '', 'Сообщение №' + message.cid); link.href = message.url; details.append(link); }
      body.append(details);
    }
    body.append(actions); node.append(preview, body); return node;
  }
  function render(append = false) {
    const matches = filterMedia(items, selected, search.value);
    const first = append ? grid.children.length : 0;
    if (!append) grid.replaceChildren(); const fragment = document.createDocumentFragment();
    for (const item of matches.slice(first, limit)) fragment.append(card(item));
    grid.append(fragment);
    document.getElementById('mediaResults').textContent = 'Найдено файлов: ' + matches.length + ' · показано: ' + Math.min(limit, matches.length);
    empty.hidden = matches.length > 0;
    empty.classList.remove('error'); empty.textContent = items.length ? 'По этому фильтру ничего не найдено.' : 'В этом диалоге пока нет сохранённых вложений.';
    more.hidden = limit >= matches.length;
  }
  async function load() {
    if (loading) return; loading = true; refresh.disabled = true;
    try {
      const response = await fetch('/api/chat/' + peer + '/attachments', {cache: 'no-store'});
      if (!response.ok) throw new Error('Не удалось открыть библиотеку (' + response.status + ').');
      const data = await response.json(); items = data.items;
      document.title = 'Вложения — ' + data.dialog.name;
      document.getElementById('libraryTitle').textContent = 'Вложения · ' + data.dialog.name;
      document.getElementById('libraryStats').textContent = data.total + ' файлов · ' + mediaSize(data.total_bytes) + ' · Каждый файл показан один раз';
      for (const button of filters) button.textContent = typeNames[button.dataset.type] + ' (' + (button.dataset.type === 'all' ? data.total : data.counts[button.dataset.type]) + ')';
      limit = 60; render();
    } catch (error) {
      empty.hidden = false; empty.classList.add('error'); empty.textContent = error.message + ' Нажмите «Обновить», чтобы повторить.';
      document.getElementById('libraryStats').textContent = 'Библиотека недоступна';
    } finally { loading = false; refresh.disabled = false; }
  }
  for (const button of filters) button.onclick = () => {
    selected = button.dataset.type; limit = 60;
    for (const filter of filters) filter.setAttribute('aria-pressed', String(filter === button)); render();
  };
  search.oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { limit = 60; render(); }, 150); };
  more.onclick = () => { limit += 60; render(true); };
  refresh.onclick = load;
  document.getElementById('closeMediaPhoto').onclick = () => box.close();
  box.onclick = event => { if (event.target === box) box.close(); };
  box.addEventListener('close', () => photo.removeAttribute('src'));
  load();
}
