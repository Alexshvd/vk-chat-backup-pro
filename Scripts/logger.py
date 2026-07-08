class Logger:
    @staticmethod
    def LogWarning(error_type: str, exception: Exception) -> None:
        print(f"[Warning] {error_type}.{exception}")
