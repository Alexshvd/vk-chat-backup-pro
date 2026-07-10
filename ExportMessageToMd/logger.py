from typing import Optional


class Logger:
    @staticmethod
    def LogWarning(error_type: str, exception: Optional[Exception] = None) -> None:
        if exception:
            print(f"[Warning] {error_type}.{exception}")
        else:
            print(f"[Warning] {error_type}")
