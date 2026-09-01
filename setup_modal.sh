#!/usr/bin/env bash
set -euo pipefail

# Modal is already installed in the current workspace. This is the reproducible
# setup for a fresh local machine.
python3 -m pip install modal
modal setup
