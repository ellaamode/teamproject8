import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# 읽기 전용 계정(api_reader) 주소. prepare_threshold=None: Supabase 커넥션 풀러 호환
pool = ConnectionPool(os.environ.get("DATABASE_URL", ""), min_size=1, max_size=5, open=False,
                      kwargs={"row_factory": dict_row, "prepare_threshold": None})


def q(sql: str, args=()) -> list[dict]:
    with pool.connection() as c:
        return c.execute(sql, args).fetchall()


def one(sql: str, args=()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None
