from typing import Optional

from Loggers.base_logger import BaseLogger


class BufferLogger(BaseLogger):
    def __init__(self):
        self._buffer: list[str] = []

    def LogWarning(self, error_type: str, exception: Optional[Exception] = None) -> None:
        if exception:
            msg = f"[Warning] {error_type}.{exception}"
        else:
            msg = f"[Warning] {error_type}"
        self._buffer.append(msg)

    def ConsumeMessages(self) -> list[str]:
        messages = self._buffer[:]
        self._buffer.clear()
        return messages
