import os
from pathlib import Path
from dataclasses import dataclass, field

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

@dataclass
class Config:
    db_path: str = field(default_factory=lambda: os.getenv("DATABASE_URL", str(PROJECT_ROOT / "data" / "achilles.db")))
    raw_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "raw")
    log_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "log")

    def ensure_dirs(self):
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

config = Config()
