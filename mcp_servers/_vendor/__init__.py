"""Vendored third-party packages without proper PyPI distributions.

Currently:
- yars/  -- https://github.com/datavorous/yars (Reddit scraper, no API key needed)
"""
import os
import sys

_VENDOR_DIR = os.path.dirname(os.path.abspath(__file__))
if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)
