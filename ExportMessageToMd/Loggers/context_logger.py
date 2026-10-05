"""Attach message and attachment details without changing logger consumers."""
import re

from Loggers.base_logger import BaseLogger


def warning_text(message, exception=None):
    text = str(message)
    if exception is not None:
        text += ': ' + type(exception).__name__ + ': ' + str(exception)
    # Keep signed media addresses useful while excluding account credentials.
    return re.sub(r'(?i)(\b(?:access_token|refresh_token|client_secret|password)=)[^&\s]+',
                  r'\1[скрыто]', text)


class ContextLogger(BaseLogger):
    def __init__(self, logger, context):
        self.logger = logger
        self.context = context

    def LogWarning(self, error_type, exception=None):
        self.logger.LogWarning(self.context + '\n' + str(error_type), exception)


def attachment_description(attachment):
    kind = attachment.get('type', '')
    labels = {'photo': 'Фото', 'video': 'Видео', 'short_video': 'Короткое видео',
              'doc': 'Документ', 'sticker': 'Стикер', 'article': 'Статья',
              'wall': 'Пост', 'post': 'Пост', 'audio': 'Аудио', 'audio_message': 'Голосовое сообщение'}
    data = attachment.get(kind) or {}
    title = ' — '.join(str(data.get(key) or '') for key in ('artist', 'title') if data.get(key))
    identity = str(data.get('owner_id', '')) + '_' + str(data['id']) if data.get('id') is not None else ''
    return labels.get(kind, kind) + (': ' + title if title else '') + (' (ID ' + identity + ')' if identity else '')
