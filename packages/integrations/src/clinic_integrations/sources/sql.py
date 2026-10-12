from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text


@dataclass
class SqlSource:
    """Read rows from a client's own database (read-only credentials, please).

    ``url`` is any SQLAlchemy URL (postgresql, mysql+pymysql, mssql+pyodbc...);
    the matching driver must be installed. One query per entity type.
    """

    url: str
    query: str
    source_kind: str = "sql"

    def rows(self) -> Iterator[dict[str, Any]]:
        engine = create_engine(self.url)
        try:
            with engine.connect() as conn:
                result = conn.execution_options(stream_results=True).execute(text(self.query))
                for row in result.mappings():
                    yield dict(row)
        finally:
            engine.dispose()
