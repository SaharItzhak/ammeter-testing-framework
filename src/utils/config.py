import yaml
from typing import Any, Dict


def load_config(config_path: str) -> Dict[str, Any]:
    """Load a configuration file."""
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML configuration '{config_path}': {error}") from error
    if not isinstance(config, dict):
        raise ValueError(f"Configuration must contain a YAML mapping: {config_path}")
    return config
