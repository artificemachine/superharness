"""superharness — multi-agent session handoff framework."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("superharness")
except PackageNotFoundError:
    __version__ = "unknown"
