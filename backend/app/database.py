from collections.abc import Iterator
import logging

from fastapi import HTTPException
from psycopg import Connection, OperationalError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from .config import get_settings

log = logging.getLogger(__name__)

pool = ConnectionPool(
    conninfo=get_settings().database_url,
    min_size=1,
    max_size=10,
    open=False,
    check=ConnectionPool.check_connection,
    kwargs={"row_factory": dict_row, "connect_timeout": 5},
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
    except OperationalError as error:
        # Preserve SQL errors unrelated to a lost/unavailable connection.
        sqlstate = error.sqlstate
        if sqlstate and not (sqlstate.startswith("08") or sqlstate in {"57P01", "57P02", "57P03"}):
            raise
        log.warning("Database connection interrupted (%s, SQLSTATE=%s)", type(error).__name__, sqlstate)
        # A lost COMMIT acknowledgement does not prove the write was rolled back.
        # Never replay a write automatically after an ambiguous connection loss.
        raise HTTPException(
            status_code=503,
            detail="Связь с базой данных прервалась. Если вы сохраняли изменения, проверьте их после восстановления связи перед повтором.",
            headers={"Retry-After": "5"},
        ) from error

