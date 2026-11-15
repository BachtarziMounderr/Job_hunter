"""Compatibility entry point; first install the project with pip install -e ."""

from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["collect"]))
