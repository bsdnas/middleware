#!/usr/bin/env bash
# Syntax check for the build shell scripts, to be run before committing.
#
# Why: sh -n catches syntax errors instantly, but it trips over function names
# containing a hyphen (pre-install(), post-install()) -- FreeBSD sh accepts them
# while dash and other strictly POSIX shells do not. That makes it easy to
# dismiss the check as useless and skip it, only to end up with an unparsable
# install.sh in the image. This script works around the discrepancy by replacing
# the hyphen with an underscore in a temporary copy.
#
# Usage:
#   ./tools/check-sh.sh                 # check the whole default set
#   ./tools/check-sh.sh path/to/file    # check specific files

set -u

FILES=("$@")
if [ ${#FILES[@]} -eq 0 ]; then
    mapfile -t FILES < <(
        find src/freenas-installer -name '*.sh' 2>/dev/null
        find nas_ports -name 'pkg-install*' -o -name 'pkg-deinstall*' 2>/dev/null
        find src/freenas/etc/rc.d -type f 2>/dev/null | head -50
    )
fi

rc=0
checked=0
for f in "${FILES[@]}"; do
    [ -f "$f" ] || continue
    checked=$((checked + 1))
    tmp=$(mktemp)
    # Two known liberties of FreeBSD sh that dash does not allow:
    #   1) a hyphen in a function name: pre-install()
    #   2) an empty function body: f() { }
    # They are normalized in a temporary copy so that the check catches real
    # errors rather than a difference between dialects.
    sed -e 's/^\([a-zA-Z_]*\)-\([a-zA-Z_]*\)()/\1_\2()/' "$f" \
        | awk '{ if (prev ~ /^\{[ \t]*$/ && $0 ~ /^\}[ \t]*$/) print ":"; print; prev=$0 }' > "$tmp"
    if ! err=$(sh -n "$tmp" 2>&1); then
        echo "SYNTAX: $f"
        echo "$err" | sed 's/^/    /' | head -5
        rc=1
    fi
    rm -f "$tmp"
done

if [ "$rc" -eq 0 ]; then
    echo "syntax is fine: files checked: $checked"
else
    echo "errors found, do not commit"
fi
exit "$rc"
