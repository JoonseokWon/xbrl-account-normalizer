"""Read-only, source-bound DSD document version comparison."""
from .service import KIND_LABELS, STATUS_LABELS, compare_dsd_versions

__all__ = ['KIND_LABELS', 'STATUS_LABELS', 'compare_dsd_versions']
