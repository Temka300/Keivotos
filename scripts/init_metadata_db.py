"""Create or additively migrate the library index before server startup."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import config  # noqa: E402
from schema import ensure_data_schema  # noqa: E402


def main() -> None:
    config.migrate_legacy_default_metadata()
    config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATA_DB_PATH)
    try:
        ensure_data_schema(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"metadata database ready: {config.DATA_DB_PATH}")


if __name__ == "__main__":
    main()
