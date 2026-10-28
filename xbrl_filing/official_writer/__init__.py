"""Inspect installed authoring software without executing the inspected program."""

from .discovery import discover_writers, inspect_writer
from .profiles import profile_for_writer

__all__ = ['discover_writers', 'inspect_writer', 'profile_for_writer']
