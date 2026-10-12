from collections.abc import Iterator
from typing import Any, Protocol


class Source(Protocol):
    """Anything that yields flat rows for one entity type.

    CSV/Excel exports, a query against a client's database, or an EMR API
    connector all reduce to this. Mapping and loading are the same for all of them.
    """

    source_kind: str  # csv, excel, sql, emr_api

    def rows(self) -> Iterator[dict[str, Any]]: ...
