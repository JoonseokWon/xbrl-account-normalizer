"""Read-only DSD/IXD comparison using explicit, reviewed correspondences."""
from .service import build_mapping, compare_disclosures, inspect_disclosures
from .suggestions import suggest_correspondences

__all__ = ['build_mapping', 'compare_disclosures', 'inspect_disclosures', 'suggest_correspondences']
