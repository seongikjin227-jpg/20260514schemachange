"""Add SQL classification columns to NEXT_SQL_INFO.

Run:
  python scripts/add_sql_info_classification_columns.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts._bootstrap import ROOT_DIR

load_dotenv(ROOT_DIR / ".env")

from server.services.sql.db_runtime import get_connection, get_oracle_schema, get_result_table


COLUMNS = {
    "SQL_LENGTH": "VARCHAR2(10)",
    "MAP_TYPE": "VARCHAR2(20)",
}


def column_exists(cur, table_name: str, column_name: str) -> bool:
    owner = get_oracle_schema()
    if owner:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM ALL_TAB_COLUMNS
            WHERE OWNER = :1 AND TABLE_NAME = :2 AND COLUMN_NAME = :3
            """,
            (owner, table_name.upper(), column_name.upper()),
        )
    else:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM USER_TAB_COLUMNS
            WHERE TABLE_NAME = :1 AND COLUMN_NAME = :2
            """,
            (table_name.upper(), column_name.upper()),
        )
    return cur.fetchone()[0] > 0


def main() -> None:
    table_name = get_result_table()
    short_table_name = table_name.split(".")[-1].upper()
    with get_connection() as conn:
        cur = conn.cursor()
        for column_name, ddl in COLUMNS.items():
            if column_exists(cur, short_table_name, column_name):
                print(f"{column_name} already exists.")
                continue
            cur.execute(f"ALTER TABLE {table_name} ADD ({column_name} {ddl})")
            print(f"Added {column_name}.")
        conn.commit()
    print("Done.")


if __name__ == "__main__":
    main()
