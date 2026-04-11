#!/usr/bin/env bash
# Build a release wheel + sdist for Hazel.
#
# Usage:
#   ./scripts/build-release.sh              # build only
#   ./scripts/build-release.sh --publish    # build + update the PEP 503 index
#
# Prerequisites: uv (https://docs.astral.sh/uv/)
#
# Output lands in dist/  — upload the .whl to wherever you host packages
# (GitHub Releases, S3, any static file server).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Clean previous builds
# ---------------------------------------------------------------------------
rm -rf dist/ build/

# ---------------------------------------------------------------------------
# Build wheel + sdist
# ---------------------------------------------------------------------------
echo "==> Building wheel and sdist..."
if command -v uv &>/dev/null; then
    uv build
else
    python -m build
fi

# ---------------------------------------------------------------------------
# Show what we built
# ---------------------------------------------------------------------------
echo ""
echo "==> Build artifacts:"
ls -lh dist/

WHL=$(ls dist/*.whl 2>/dev/null | head -1)
if [[ -z "$WHL" ]]; then
    echo "ERROR: no wheel found in dist/" >&2
    exit 1
fi

# Show wheel contents summary
echo ""
echo "==> Wheel contents ($(basename "$WHL")):"
python3 -c "
import zipfile, sys
with zipfile.ZipFile(sys.argv[1]) as zf:
    names = zf.namelist()
    exts = {}
    for n in names:
        ext = n.rsplit('.', 1)[-1] if '.' in n else '(dir)'
        exts[ext] = exts.get(ext, 0) + 1
    print(f'   {len(names)} files total')
    for ext, count in sorted(exts.items(), key=lambda x: -x[1]):
        print(f'   .{ext}: {count}')
" "$WHL"

# Compute SHA-256 for the index
SHA256=$(sha256sum "$WHL" | cut -d' ' -f1)
echo ""
echo "==> SHA-256: $SHA256"
echo "==> Wheel:   $(basename "$WHL")"

# ---------------------------------------------------------------------------
# Optionally regenerate the PEP 503 simple index
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--publish" ]]; then
    echo ""
    echo "==> Regenerating PEP 503 index..."
    bash "$REPO_ROOT/scripts/generate-index.sh"
fi

echo ""
echo "Done. Next steps:"
echo "  1. Upload dist/*.whl to your file host (GitHub Releases, S3, etc.)"
echo "  2. If using a PEP 503 index, run: ./scripts/generate-index.sh"
echo "  3. Users install with:"
echo "     curl -LsSf https://your-host.com/install.sh | bash"
