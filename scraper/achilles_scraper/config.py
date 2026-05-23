import os
from pathlib import Path
from dataclasses import dataclass, field

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_db_path() -> str:
    raw = os.getenv("DATABASE_URL", "")
    if not raw:
        return str(PROJECT_ROOT / "data" / "achilles.db")
    p = Path(raw)
    # Relative paths in DATABASE_URL are resolved from project root, not cwd.
    return str(p if p.is_absolute() else PROJECT_ROOT / p)


@dataclass
class Config:
    db_path: str = field(default_factory=_resolve_db_path)
    raw_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "raw")
    log_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "log")

    def ensure_dirs(self):
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

config = Config()
