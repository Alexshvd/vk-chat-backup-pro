# VkChatBackup

Локальный инструмент для экспорта диалогов VK в Markdown с сохранением всех вложений.

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![Flask](https://img.shields.io/badge/Flask-3.1-green)
![Requests](https://img.shields.io/badge/Requests-2.32-orange)
![Mistune](https://img.shields.io/badge/Mistune-3.3-purple)
![License](https://img.shields.io/badge/License-MIT-yellow)

## О проекте

VK не предоставляет удобного способа сохранить историю диалога целиком — вместе с фото, видео, стикерами и документами. **VkChatBackup** решает эту задачу: выгружает сообщения, конвертирует их в Markdown и скачивает все вложения.

Приложение полностью локальное — все данные (исходные JSON, медиафайлы, готовые Markdown-документы) остаются только на вашем компьютере и не передаются на внешние сервисы.

Работает в двух режимах:
- **CLI** — разовая конвертация из командной строки
- **Веб-приложение** — веб-редактор для полного цикла: конвертация, просмотр и редактирование сообщений прямо в браузере, без правки файлов вручную

> ### ⚠️ Дисклеймер об ответственности
> Автор не несёт ответственности за возможные последствия использования этого кода. Проект был написан в личных целях, без злого умысла.

> ### 🤖 Дисклеймер об AI
> Код написан через AI-агента **opencode** (модель **big-pickle / opencode/big-pickle**). Качество кода оставляет желать лучшего :)

## Схема использования

1. **Экспорт из VK.** В браузере (vk.com) открывается нужный диалог, в консоли запускается подготовленный скрипт. Он имитирует запросы к API VK и последовательно выгружает историю сообщений, после чего скачивается файл `messages.json`.

2. **Конвертация в Markdown.** Файл `messages.json` кладётся в папку `Sources/`. Приложение разбивает историю на отдельные сообщения и создаёт для каждого Markdown-файл с автором, датой и текстом, а также скачивает все вложения — фото, видео, стикеры, документы, записи на стене. Конвертация запускается кнопкой в веб-редакторе или командой в CLI. При экспорте доступны фильтры по `min_cid` и `min_date`, позволяющие исключить старые сообщения.

3. **Редактирование.** Готовые файлы открываются в веб-редакторе: переименование сообщений и вложений, удаление лишних, ручная группировка по папкам. Всё сохраняется в Markdown и структуре каталогов.

4. **Хранение.** Итоговый результат загружается в приватное веб-хранилище, умеющее отображать Markdown и хранить файлы вложений, — например, личный репозиторий на GitHub.

## Инструкции в веб-редакторе

В приложении есть две инструкции, и стоит следовать им:

- **Главная страница** — перечисляет главные этапы работы: настройка → экспорт → диалоги
- **Страница «Экспорт»** — детальная инструкция от формирования скрипта до просмотра списка сообщений

## Возможности

- Поддержка всех типов вложений: фото, видео (mp4 + fallback VK Player), стикеры, документы, ссылки, аудио, записи на стене, пересланные сообщения
- Авторы с аватарами и типом (пользователь / сообщество)
- Фильтры `min_cid` и `min_date` при экспорте
- Веб-редактор: просмотр и переименование сообщений, вложений и диалогов, удаление, перемещение по подпапкам, массовые операции
- Контроль длины путей к файлам (ограничение 254 символа)
- Полностью офлайн

## Скриншоты

| | |
|---|---|
| ![Главная страница](docs/screenshots/main.png) | ![Экспорт](docs/screenshots/export.png) |
| ![Список диалогов](docs/screenshots/dialogs.png) | ![Просмотр диалога](docs/screenshots/dialog.png) |
| ![Настройки](docs/screenshots/settings.png) | |

## Требования и установка

- Python 3.9 или новее

```sh
pip install -r requirements.txt
```

Зависимости: `requests`, `flask`, `mistune`.

## Быстрый старт

1. Создайте `config.json` в корне проекта:

```json
{
  "export_root": "Temp/ExportMessages",
  "download_short_video": true,
  "download_long_video": false,
  "long_video_threshold": 180,
  "overwrite_existing_md": false,
  "overwrite_existing_original_message_json": false
}
```

2. Запустите нужный режим:

```sh
# Генерация MD из командной строки
python run.py --mode cli --config config.json

# Веб-редактор
python run.py --mode web --config config.json
```

Веб-редактор доступен по адресу `http://127.0.0.1:5000`.

## Как получить messages.json

1. Откройте VK в браузере и войдите в аккаунт (vk.com, vk.ru)
2. Откройте интересующий диалог, скопируйте его `peer_id` из адресной строки (число в конце `https://vk.ru/im/convo/123456789`)
3. Откройте консоль браузера (F12 → Console)
4. Скопируйте скрипт ниже, подставив параметры, и запустите его в консоли

```js
async function getHistory(peerId, fromDate, fromMessageId) {
  debugLog("getting history started...")
  const limit = 200;
  let items = [];
  let groups = new Map();
  let profiles = new Map();

  while (true) {
    let response = await window.vkApi.api("messages.getHistory", {
      peer_id: peerId,
      offset: items.length,
      count: limit,
      extended: 1,
      v: "5.199"
    });

    if(!response) break;
    if(!response.items?.length) break;

    let filteredItems = response.items.filter(i =>
        (fromMessageId == null || i.id > fromMessageId)
        && (fromDate == null || i.date > fromDate)
    );
    items.push(...filteredItems);
    if(response.groups) response.groups.forEach(i => groups.set(i.id, i));
    if(response.profiles) response.profiles.forEach(i => profiles.set(i.id, i));

    console.log(`Loaded ${items.length}/${response.count}`);

    let isAnyItemFiltered = filteredItems.length != response.items.length;
    if(isAnyItemFiltered) break;
    if(items.length >= response.count) break;

    await new Promise(r => setTimeout(r, 350));
  }
  return { peer_id: peerId, items: items, groups: Array.from(groups.values()), profiles: Array.from(profiles.values()) };
}

function saveToFile(data, filename) {
  let blob = new Blob([JSON.stringify(data, null, 0)], {type: 'application/json'});
  let a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

let peerId = 123456789;                       // Peer ID диалога
let fromDate = null;                          // Дата начала (или null)
let fromMessageId = null;                     // ID сообщения, с которого начать (или null)

let fromDateUnixTimestamp = fromDate != null ? Math.floor(fromDate.getTime() / 1000) : null;
let data = await getHistory(peerId, fromDateUnixTimestamp, fromMessageId);

let currentDate = Date.now();
let filename = `messages_peerId_${peerId}_${currentDate}.json`;
data.currentDate = currentDate;
saveToFile(data, filename);
```

5. Полученный JSON-файл переместите в папку `Sources/` (кнопка загрузки есть на странице «Экспорт»)

## Настройки config.json

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `export_root` | string | `{каталог конфига}/Temp/ExportMessages` | Корневой каталог экспорта |
| `download_short_video` | bool | `true` | Скачивать короткие видео |
| `download_long_video` | bool | `false` | Скачивать длинные видео |
| `long_video_threshold` | int | `180` | Порог длинного видео, сек |
| `overwrite_existing_md` | bool | `false` | Перезаписывать существующие MD-файлы (удаляются старые MD, RawData и LargeRawData) |
| `overwrite_existing_original_message_json` | bool | `false` | Перезаписывать существующие JSON-файлы сообщений |
| `dialog_name_by_peer_id` | dict | `{}` | Кастомные имена папок диалогов: `{peer_id: "имя_папки"}` |
| `min_cid_by_peer_id` | dict | `{}` | Фильтр: пропускать сообщения с `conversation_message_id <= значение` |
| `min_date_by_peer_id` | dict | `{}` | Фильтр по дате: `{peer_id: "yyyy-mm-dd-hh-mm-ss"}` |

## Структура выходных файлов

```
{export_root}/
├── ExportMessages/
│   ├── Sources/                              # Исходные JSON-файлы сообщений
│   │   └── messages.json
│   └── Dialogs/
│       ├── AutorImages/                      # Аватары авторов
│       │   └── photo_12345.jpg
│       └── dialog_{peer_id}/ (или {custom_name})
│           ├── RawData/                      # Малые вложения (фото, стикеры, доки)
│           │   └── {cid}/
│           │       ├── 1.jpg
│           │       └── 2.webp
│           ├── OriginalMessages/             # Исходные JSON по одному сообщению
│           │   └── 2026-01-15_1234.json
│           └── MdFiles/                      # Сконвертированные Markdown-файлы
│               └── Привет.Id1234.md
└── LargeRawData/                             # Большие файлы (видео)
    └── dialog_{peer_id}/
        └── {cid}/
            └── 1.mp4
```

## Пример выходного MD

```markdown
# Привет, как дела?

<table>
  <tr>
    <td style="vertical-align:middle">
      <img width="55" height="55" src="../../AutorImages/photo_12345.jpg">
    </td>
    <td style="vertical-align:middle">
      <b>Иван Иванов</b> [Пользователь]<br>
      <b>Дата:</b> 2026-01-15 12:34:56<br>
      <b>Ник:</b> ivanov<br>
      <b>Id:</b> 12345
    </td>
  </tr>
</table>

Привет, как дела?

## Вложения

**Фото:** <a href="../../RawData/1234/1.jpg"><img src="../../RawData/1234/1.jpg" width="300" alt="Фото"></a>

## Источники

| Тип | Относительная ссылка | Ссылка |
|-----|---------------------|--------|
| Исходный файл | [../OriginalMessages/2026-01-15-12-34-56_1234.json](../OriginalMessages/2026-01-15-12-34-56_1234.json) | |
| Аватар автора | [../../AutorImages/photo_12345.jpg](../../AutorImages/photo_12345.jpg) | [url](https://vk.com) |
| Фото | [../../RawData/1234/1.jpg](../../RawData/1234/1.jpg) | [url](https://vk.com) |
```

## Лицензия

MIT. Автор: saigor33.
