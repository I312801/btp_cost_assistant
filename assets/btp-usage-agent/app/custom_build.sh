#!/bin/bash
# custom_build.sh — builds /outputs with app source + targeted gen_ai_hub packages only.
#
# WHY selective copy:
#   The platform base image (dhi.io/python:3.12) already has fastapi, starlette,
#   uvicorn, httpx, anyio, etc. pre-installed. uvicorn loads starlette/anyio before
#   main.py runs, caching them in sys.modules. If we copy conflicting versions of
#   those packages into /app/dependencies and prepend sys.path, we get a version
#   mismatch on already-loaded modules → CrashLoopBackOff.
#
#   Solution: ONLY copy packages that are NOT in the base image (gen_ai_hub stack).
#   These are then added to sys.path at runtime via main.py's bootstrap block.
set -e

echo "=== custom_build.sh: starting ==="

mkdir -p /outputs /outputs/dependencies

# ── 1. Copy app source files to /outputs/ ─────────────────────────────────────
echo "Copying app source files..."
find /app -maxdepth 1 \( \
    -name "*.py"   \
    -o -name ".env"   \
    -o -name "*.env"  \
    -o -name "*.json" \
    -o -name "*.yaml" \
    -o -name "*.txt"  \
    -o -name "*.cfg"  \
    -o -name "*.ini"  \
\) -exec cp {} /outputs/ \; 2>/dev/null || true

# ── 2. Copy gen_ai_hub and its UNIQUE dependencies only ───────────────────────
# Packages in this list are NOT pre-installed in the base image.
# Web-framework packages (fastapi, starlette, uvicorn, httpx, anyio, httpcore,
# h11, click, pyyaml, websockets, watchfiles, uvloop, httptools, python-dotenv,
# typing-extensions, packaging, annotated-types) are deliberately excluded.

DEPS=/app/dependencies
DST=/outputs/dependencies

copy_pkg() {
    local name="$1"
    local copied=0
    # package directory
    if [ -d "$DEPS/$name" ]; then
        cp -r "$DEPS/$name" "$DST/"
        echo "  + $name/"
        copied=1
    fi
    # single-file module
    if [ -f "$DEPS/$name.py" ]; then
        cp "$DEPS/$name.py" "$DST/"
        echo "  + $name.py"
        copied=1
    fi
    # dist-info (try common name patterns)
    for d in "$DEPS"/${name}-*.dist-info "$DEPS"/${name//-/_}-*.dist-info; do
        if [ -d "$d" ]; then
            cp -r "$d" "$DST/"
            echo "  + $(basename $d)"
        fi
    done
    return 0
}

echo "Copying gen_ai_hub stack..."

# SAP AI Core packages
copy_pkg gen_ai_hub
copy_pkg ai_core_sdk
copy_pkg ai_api_client_sdk
# generative_ai_hub_sdk dist-info (package name vs module name differ)
for d in "$DEPS"/generative_ai_hub_sdk-*.dist-info; do
    [ -d "$d" ] && cp -r "$d" "$DST/" && echo "  + $(basename $d)"
done

# gen_ai_hub direct dependencies
copy_pkg overloading       # single-file or package
copy_pkg dacite
copy_pkg aenum
copy_pkg humps             # pyhumps installs its module as 'humps'
for d in "$DEPS"/pyhumps-*.dist-info; do
    [ -d "$d" ] && cp -r "$d" "$DST/" && echo "  + $(basename $d)"
done

# pydantic 2.9.2 + pydantic_core 2.23.4
# Required because gen_ai_hub may need pydantic <2.10; base image may have newer.
# sys.path.insert(0, /app/dependencies) in main.py ensures THIS version is used.
copy_pkg pydantic
copy_pkg pydantic_core
for d in "$DEPS"/pydantic-*.dist-info "$DEPS"/pydantic_core-*.dist-info; do
    [ -d "$d" ] && cp -r "$d" "$DST/" && echo "  + $(basename $d)"
done

# openai (required by gen_ai_hub as an AI Core proxy client)
copy_pkg openai
copy_pkg jiter             # C extension used by openai for JSON parsing
copy_pkg tqdm
copy_pkg distro
copy_pkg sniffio

# requests + its deps (required by ai_api_client_sdk)
copy_pkg requests
copy_pkg certifi
copy_pkg urllib3
copy_pkg charset_normalizer  # requests dep (has C extension)
copy_pkg idna

# Handle top-level C extension modules (.so files) that install as bare .so
# (e.g. jiter.cpython-312-x86_64-linux-gnu.so when not packaged as a directory)
for so_file in "$DEPS"/jiter*.so "$DEPS"/charset_normalizer*.so; do
    [ -f "$so_file" ] && cp "$so_file" "$DST/" && echo "  + $(basename $so_file)"
done

echo "=== /outputs/ ==="
ls /outputs/
echo ""
echo "=== /outputs/dependencies/ ($(ls $DST | wc -l) entries) ==="
ls "$DST"
echo "=== custom_build.sh: complete ==="
