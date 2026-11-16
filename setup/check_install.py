"""Smoke-test the installed environment and local detector."""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from detector import find_default_model, load_detector


def main():
    for module in ("tkinter", "psd_tools"):
        importlib.import_module(module)

    model = find_default_model()
    if model is None:
        raise FileNotFoundError("Local SCRFD model is missing.")
    load_detector(model, sys.argv[1], print)
    print("Model inference OK.", flush=True)


if __name__ == "__main__":
    main()
