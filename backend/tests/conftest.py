import os
import sys
import tempfile
from pathlib import Path

_db = Path(tempfile.gettempdir()) / "vacaciones_test.db"
if _db.exists():
    _db.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_db.as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
