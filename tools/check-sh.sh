#!/usr/bin/env bash
# Проверка shell-скриптов сборки перед коммитом.
#
# Зачем: sh -n ловит синтаксические ошибки мгновенно, но спотыкается на именах
# функций с дефисом (pre-install(), post-install()) — FreeBSD sh их допускает,
# а dash/POSIX-строгие оболочки нет. Из-за этого проверку легко счесть
# бесполезной и пропустить, а потом получить неразбираемый install.sh в образе.
# Скрипт обходит расхождение заменой дефиса на подчёркивание во временной копии.
#
# Использование:
#   ./tools/check-sh.sh                 # проверить весь набор по умолчанию
#   ./tools/check-sh.sh path/to/file    # проверить конкретные файлы

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
    # Две известные вольности FreeBSD sh, которых не допускает dash:
    #   1) дефис в имени функции: pre-install()
    #   2) пустое тело функции: f() { }
    # Нормализуем во временной копии, чтобы проверка ловила настоящие ошибки,
    # а не расхождение диалектов.
    sed -e 's/^\([a-zA-Z_]*\)-\([a-zA-Z_]*\)()/\1_\2()/' "$f" \
        | awk '{ if (prev ~ /^\{[ \t]*$/ && $0 ~ /^\}[ \t]*$/) print ":"; print; prev=$0 }' > "$tmp"
    if ! err=$(sh -n "$tmp" 2>&1); then
        echo "СИНТАКСИС: $f"
        echo "$err" | sed 's/^/    /' | head -5
        rc=1
    fi
    rm -f "$tmp"
done

if [ "$rc" -eq 0 ]; then
    echo "синтаксис в порядке: проверено файлов $checked"
else
    echo "найдены ошибки — коммитить нельзя"
fi
exit "$rc"
