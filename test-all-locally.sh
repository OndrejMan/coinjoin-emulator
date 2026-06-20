#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTING_DATA_DIR="${TESTING_DATA_DIR:-${PROJECT_ROOT}/../testing_data}"

if [[ ! -d "${TESTING_DATA_DIR}" ]]; then
    echo "Historical test corpus is required: ${TESTING_DATA_DIR}" >&2
    echo "Clone OndrejMan/testing_data next to coinjoin-emulator, or set TESTING_DATA_DIR." >&2
    exit 1
fi

cd "${PROJECT_ROOT}"
RUN_HISTORICAL_ARCHIVE_INTEGRATION=1 TESTING_DATA_DIR="${TESTING_DATA_DIR}" uv run pytest
