from dataclasses import dataclass
from pathlib import Path

@dataclass
class Session:
    input_path: Path
    profile: dict
    catalog: dict
    raw: dict
    mappings: list
    matrices: dict
    source: dict
    result: dict
    history: object
    history_enabled: bool=True
    dirty: bool=False
