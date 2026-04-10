#!/usr/bin/env bash
# Generate _cards.md index from all entity files in memory/areas/
# Extracts <!-- CARD ... --> headers and concatenates with file paths

set -euo pipefail

AREAS_DIR="${1:-memory/areas}"
OUTPUT="${2:-memory/_index/_cards.md}"

mkdir -p "$(dirname "$OUTPUT")"

cat > "$OUTPUT" << 'EOF'
# Entity Cards Index

Auto-generated index of all entity CARD headers.
Use for LLM-based retrieval routing.

---

EOF

find "$AREAS_DIR" -name "*.md" -type f | sort | while read -r file; do
  card=$(sed -n '/<!-- CARD/,/-->/p' "$file" 2>/dev/null)
  if [[ -n "$card" ]]; then
    echo "## $file"
    echo ""
    echo "$card"
    echo ""
    echo "---"
    echo ""
  fi
done >> "$OUTPUT"

echo "Generated: $OUTPUT ($(grep -c '^## ' "$OUTPUT") entities)"
