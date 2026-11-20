from collections.abc import Iterator

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from .config import get_settings


pool = ConnectionPool(
    conninfo=get_settings().database_url,
    min_size=1,
    max_size=10,
    open=False,
    kwargs={"row_factory": dict_row},
)


def open_pool() -> None:
    pool.open(wait=True, timeout=20)


def close_pool() -> None:
    pool.close()


def get_connection() -> Iterator[Connection]:
    try:
        with pool.connection(timeout=5) as connection:
            yield connection
    except PoolTimeout as error:
        raise HTTPException(
            status_code=503,
            detail="Сервер занят. Повторите попытку через несколько секунд.",
            headers={"Retry-After": "5"},
        ) from error

