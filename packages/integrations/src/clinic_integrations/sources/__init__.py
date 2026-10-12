"""Data sources.

EMR/practice-management API connectors (Boulevard, Zenoti, Mindbody, Jane,
Nextech, ...) go in ``sources/emr/<vendor>.py`` and implement ``Source`` per
entity. Until a client's EMR has a connector, onboard them from its CSV export.
"""

from clinic_integrations.sources.base import Source
from clinic_integrations.sources.files import CsvSource, ExcelSource
from clinic_integrations.sources.sql import SqlSource

__all__ = ["CsvSource", "ExcelSource", "Source", "SqlSource"]
