from typing import Optional

from Loggers.base_logger import BaseLogger


class AggregationLogger(BaseLogger):
    def __init__(self, loggers: list[BaseLogger]):
        self._loggers = loggers

    def LogWarning(self, error_type: str, exception: Optional[Exception] = None) -> None:
        for logger in self._loggers:
            logger.LogWarning(error_type, exception)
