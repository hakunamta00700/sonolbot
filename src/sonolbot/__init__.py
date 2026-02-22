"""Core package for Sonolbot command interface."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sonolbot")
except PackageNotFoundError:
    __version__ = "0.0.0"
