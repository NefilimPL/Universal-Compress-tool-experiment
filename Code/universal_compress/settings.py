from dataclasses import dataclass


@dataclass
class AppSettings:
    simple_mode: bool = True
    theme: str = "system"
    max_parallel_jobs: int = 1
