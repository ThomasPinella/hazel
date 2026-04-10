#!/usr/bin/env bash
# Generate a PEP 503 simple package index from wheel files in dist/.
#
# This creates a static directory structure that can be served by any HTTP
# server (nginx, S3, GitHub Pages, Caddy, etc.) and used as:
#
#   uv tool install hazel-ai --index https://your-host.com/simple/
#
# Output: packages/simple/  (ready to upload as-is)
#
# Directory layout after running:
#   packages/
#   ├── simple/
#   │   ├── index.html           ← root index listing all packages
#   │   └── hazel-ai/
#   │       └── index.html       ← per-package index with links to wheels
#   └── wheels/
#       └── hazel_ai-*.whl       ← the actual wheel files

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
PKG_DIR="$REPO_ROOT/packages"
SIMPLE_DIR="$PKG_DIR/simple"
WHEELS_DIR="$PKG_DIR/wheels"
PACKAGE_NAME="hazel-ai"

if ! ls "$DIST_DIR"/*.whl &>/dev/null; then
    echo "ERROR: no wheel files found in dist/. Run build-release.sh first." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Set up directory structure
# ---------------------------------------------------------------------------
rm -rf "$SIMPLE_DIR"
mkdir -p "$SIMPLE_DIR/$PACKAGE_NAME"
mkdir -p "$WHEELS_DIR"

# Copy wheels into the packages directory
cp "$DIST_DIR"/*.whl "$WHEELS_DIR/"

# ---------------------------------------------------------------------------
# Generate root index.html
# ---------------------------------------------------------------------------
cat > "$SIMPLE_DIR/index.html" <<'ROOTEOF'
<!DOCTYPE html>
<html>
<head><title>Hazel Package Index</title></head>
<body>
  <a href="hazel-ai/">hazel-ai</a>
</body>
</html>
ROOTEOF

# ---------------------------------------------------------------------------
# Generate per-package index.html
# ---------------------------------------------------------------------------
{
    echo '<!DOCTYPE html>'
    echo '<html>'
    echo '<head><title>hazel-ai</title></head>'
    echo '<body>'
    for whl in "$WHEELS_DIR"/*.whl; do
        filename="$(basename "$whl")"
        sha256="$(sha256sum "$whl" | cut -d' ' -f1)"
        echo "  <a href=\"../../wheels/${filename}#sha256=${sha256}\" data-requires-python=\"&gt;=3.11\">${filename}</a><br/>"
    done
    echo '</body>'
    echo '</html>'
} > "$SIMPLE_DIR/$PACKAGE_NAME/index.html"

echo "==> PEP 503 index generated at: $PKG_DIR/"
echo ""
echo "Directory structure:"
find "$PKG_DIR" -type f | sort | sed "s|$REPO_ROOT/||"
echo ""
echo "To serve locally for testing:"
echo "  cd $PKG_DIR && python3 -m http.server 8080"
echo "  uv tool install hazel-ai --index http://localhost:8080/simple/"
echo ""
echo "To deploy: upload the entire packages/ directory to your static file host."
