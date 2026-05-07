"""superharness — multi-agent session handoff framework."""
from importlib.metadata import version as _version, PackageNotFoundError as _PNF

try:
    __version__ = _version("superharness")
except _PNF:
    __version__ = "0.0.0.dev"
