"""superharness pack — export and import portable .superharness project state."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="pack",
        description="Export and import portable .superharness project state.",
    )
    sub = parser.add_subparsers(dest="subcmd")

    # export
    p_export = sub.add_parser(
        "export",
        help="Export portable .superharness state to a pack file.",
    )
    p_export.add_argument(
        "--project", "-p", default=None,
        help="Project root (default: cwd)",
    )
    p_export.add_argument(
        "--output", "-o", default=None,
        help="Output file path (default: <project>-<timestamp>.superharness.pack.tar.gz)",
    )
    p_export.add_argument(
        "--scrub", action="store_true", default=False,
        help="Redact secrets (API keys, tokens, private keys) from all exported text files.",
    )

    # import
    p_import = sub.add_parser(
        "import",
        help="Import a .superharness pack into a project directory.",
    )
    p_import.add_argument(
        "pack_file",
        help="Path to the .superharness.pack.tar.gz file",
    )
    p_import.add_argument(
        "--project", "-p", default=None,
        help="Destination project root (default: cwd)",
    )
    p_import.add_argument(
        "--collision",
        choices=["skip", "overwrite", "fail"],
        default="skip",
        help=(
            "How to handle existing files: "
            "skip (default) = keep existing; "
            "overwrite = replace with pack version; "
            "fail = abort if any collision"
        ),
    )

    opts = parser.parse_args(argv)
    if not opts.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    from superharness.engine.pack import export_pack, import_pack

    if opts.subcmd == "export":
        project_dir = os.path.realpath(opts.project or os.getcwd())
        try:
            output = export_pack(project_dir, output_path=opts.output, scrub=opts.scrub)
            label = " (scrubbed)" if opts.scrub else ""
            print(f"Exported pack{label}: {output}")
            sys.exit(0)
        except FileNotFoundError as e:
            _abort(str(e))
        except Exception as e:
            _abort(f"Export failed: {e}")

    elif opts.subcmd == "import":
        project_dir = os.path.realpath(opts.project or os.getcwd())
        try:
            result = import_pack(opts.pack_file, project_dir, collision=opts.collision)
            imported = len(result["imported"])
            skipped = len(result["skipped"])
            print(f"Imported {imported} file(s), skipped {skipped} existing file(s).")
            if result["imported"]:
                for f in result["imported"]:
                    print(f"  + {f}")
            if result["skipped"] and skipped <= 10:
                for f in result["skipped"]:
                    print(f"  ~ {f} (skipped, already exists)")
            elif skipped > 10:
                print(f"  ~ ...and {skipped} more skipped")
            sys.exit(0)
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            _abort(str(e))
        except Exception as e:
            _abort(f"Import failed: {e}")


if __name__ == "__main__":
    main()
