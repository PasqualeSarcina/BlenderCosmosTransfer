import argparse
import json
import subprocess
import sys
from pathlib import Path

from config_utils import load_validate_config


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path al file json di configurazione"
    )

    parser.add_argument(
        "--run-index",
        type=int,
        default=0,
        help="Indice run (default: 0)"
    )

    #return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    return parser.parse_args()

def main():
    args = parse_args()

    project_dir = Path(__file__).resolve().parent
    config = load_validate_config(args.config)
    blender_exe = Path(config["blender_exe_path"])
    blend_file = Path(config["blend_input_file"])

    if not(blender_exe.exists()):
        raise FileNotFoundError(f"Blender executable not found: {blender_exe}")

    command = [
        str(blender_exe),
        "--background",
        str(blend_file),
        "--python-exit-code", "1",
        "--python", str(project_dir / "main.py"),
        "--",
        "--config", str(args.config),
        "--run-index", str(args.run_index),
    ]

    result = subprocess.run(
        command,
        cwd=project_dir,
        check=False,
    )

    return result.returncode



if __name__ == "__main__":
    sys.exit(main())
