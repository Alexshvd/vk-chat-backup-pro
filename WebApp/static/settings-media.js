/* Keep existing duration choices until the user changes the main video switch. */
function syncVideoChoice(master, short, long, hint) {
  master.checked = short.checked && long.checked;
  master.indeterminate = short.checked !== long.checked;
  hint.textContent = master.indeterminate
    ? 'Выбраны только некоторые видео. Подробности — в расширенных настройках.'
    : 'Чтобы смотреть сохранённые видео без интернета. Видео с YouTube останутся ссылками.';
}
if (typeof module !== 'undefined') module.exports = {syncVideoChoice};
if (typeof document !== 'undefined') {
  const master = document.getElementById('downloadVideo');
  const short = document.getElementById('downloadShort'), long = document.getElementById('downloadLong');
  const hint = document.getElementById('videoChoiceHint');
  const sync = () => syncVideoChoice(master, short, long, hint);
  master.addEventListener('change', () => { short.checked = long.checked = master.checked; sync(); });
  short.addEventListener('change', sync); long.addEventListener('change', sync);
  sync();
}
