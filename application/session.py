from dataclasses import dataclass,field
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
    input_paths: tuple=()
    job_path: object=None
    support_config: dict=field(default_factory=dict)
    support_bundle: object=None
    support_setup: dict=field(default_factory=dict)
