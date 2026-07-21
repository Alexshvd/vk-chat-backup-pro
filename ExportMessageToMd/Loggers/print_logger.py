from typing import Optional

from Loggers.base_logger import BaseLogger


class PrintLogger(BaseLogger):
    def LogWarning(self, error_type: str, exception: Optional[Exception] = None) -> None:
        if exception:
            print(f"[Warning] {error_type}.{exception}")
        else:
            print(f"[Warning] {error_type}")
