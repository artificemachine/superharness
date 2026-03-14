"""install-wrapper command — symlink superharness into PATH."""
from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="install-wrapper")
    p.add_argument("-t", "--target-dir", default=os.path.join(os.path.expanduser("~"), ".local", "bin"))
    opts = p.parse_args(argv)

    # locate the repo root (this file is src/superharness/commands/install_wrapper.py)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    source = os.path.join(root, "superharness")
    target = os.path.join(opts.target_dir, "superharness")

    if not os.path.isfile(source):
        sys.exit(f"Missing superharness entry point: {source}")

    os.makedirs(opts.target_dir, exist_ok=True)
    if os.path.lexists(target):
        os.remove(target)
    os.symlink(source, target)

    print(f"Installed superharness wrapper: {target} -> {source}")
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if opts.target_dir in path_dirs:
        print(f"PATH already contains {opts.target_dir}")
    else:
        print(f'Add to PATH: export PATH="{opts.target_dir}:$PATH"')


if __name__ == "__main__":
    main()
