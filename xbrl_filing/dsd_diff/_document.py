"""Compatibility exports for the shared safe DSD context reader."""
from ..dsd_document import (
    MAX_NARRATIVES, MAX_NARRATIVE_TEXT, digest, display_name,
    extract_dsd_narratives, local_path, read_document,
)

__all__ = ['extract_dsd_narratives', 'read_document']
