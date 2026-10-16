#!/bin/bash
# Generate packages/maluos-meta/debian/control from seeds/*.seed.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
META=$ROOT/packages/maluos-meta/debian
OUT=$META/control

cp "$META/control.head" "$OUT"
for seed in "$ROOT"/seeds/*.seed; do
    name=$(basename "$seed" .seed)
    deps=(); recs=()
    while IFS= read -r line; do
        line=${line%%#*}; line=$(echo "$line" | xargs)
        [ -z "$line" ] && continue
        case "$line" in
            \?*) recs+=("${line#?}") ;;
            *)   deps+=("$line") ;;
        esac
    done < "$seed"
    IFS='|' read -r _ synopsis long < <(grep "^$name|" "$META/descriptions") \
        || { echo "no description for seed '$name' in $META/descriptions" >&2; exit 1; }
    {
        echo
        echo "Package: maluos-$name"
        echo "Architecture: all"
        echo "Depends: \${misc:Depends},"
        printf '         %s,\n' "${deps[@]}" | sed '$ s/,$//'
        if [ ${#recs[@]} -gt 0 ]; then
            echo "Recommends:"
            printf '         %s,\n' "${recs[@]}" | sed '$ s/,$//'
        fi
        echo "Description: $synopsis"
        echo "$long" | fold -s -w 72 | sed 's/^/ /; s/ *$//'
        echo " ."
        echo " This is a metapackage generated from seeds/$name.seed."
    } >> "$OUT"
done
echo "wrote $OUT"
