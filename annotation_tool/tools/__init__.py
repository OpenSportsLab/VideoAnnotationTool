"""
annotation_tool.tools
~~~~~~~~~~~~~~~~~~~~~

Conversion utilities for OSL annotation datasets.

Public API
----------
convert_json_to_parquet
    Convert an OSL JSON file → Parquet + WebDataset TAR shards.

convert_parquet_to_json
    Convert Parquet + WebDataset TAR shards → OSL JSON file.
"""

from .osl_json_to_parquet import (
    convert_json_to_parquet,
)
from .parquet_to_osl_json import (
    convert_parquet_to_json,
)

__all__ = [
    "convert_json_to_parquet",
    "convert_parquet_to_json",
]
