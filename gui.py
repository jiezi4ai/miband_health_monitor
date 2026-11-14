#!/usr/bin/env python3
"""Compatibility entry point for launching the Mi Band 6 interactive Web GUI."""

from __future__ import annotations

import sys

from miband_monitor.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
