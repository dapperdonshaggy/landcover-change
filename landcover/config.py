"""
Loads settings from config.yaml.
"""
from pathlib import Path
import yaml


def load_config(config_path="config.yaml"):
    """
    Read config.yaml and return a simple settings dictionary.

    All paths are converted to absolute Path objects so that the rest
    of the code doesn't need to worry about relative paths.
    """
    config_path = Path(config_path).resolve()

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Make sure you run the script from the project folder."
        )

    # The project root is the folder containing config.yaml
    root = config_path.parent

    with open(config_path, "r") as f:
        settings = yaml.safe_load(f)

    # Convert path strings to absolute Paths
    settings["input_dir"] = (root / settings["input_dir"]).resolve()
    settings["aligned_dir"] = (root / settings["aligned_dir"]).resolve()
    settings["output_dir"] = (root / settings["output_dir"]).resolve()
    settings["class_csv"] = (root / settings["class_csv"]).resolve()
    settings["root"] = root

    return settings