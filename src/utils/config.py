import yaml
from typing import Any, Dict


def load_config(config_path: str) -> Dict[str, Any]:
    """
    טעינת קובץ הקונפיגורציה
    """
    with open(config_path, "r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        raise ValueError(f"Configuration must contain a YAML mapping: {config_path}")
    return config
