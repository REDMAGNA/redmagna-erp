#!/bin/sh
set -eu

password="${POSTGRES_PASSWORD:-}"
password_lower="$(printf '%s' "$password" | tr '[:upper:]' '[:lower:]')"
case "$password_lower" in
  ""|*replace-with*|*change-me*|*changeme*|*local-only*|*example-secret*)
    echo "POSTGRES_PASSWORD falta o conserva un valor de ejemplo; PostgreSQL no inicializará su volumen." >&2
    exit 2
    ;;
esac

if [ "${#password}" -lt 24 ]; then
  echo "POSTGRES_PASSWORD debe tener al menos 24 caracteres; PostgreSQL no inicializará su volumen." >&2
  exit 2
fi
if [ "$password" != "$(printf '%s' "$password" | tr -d '[:space:]')" ]; then
  echo "POSTGRES_PASSWORD no puede contener espacios ni saltos de línea." >&2
  exit 2
fi

unique_characters="$(printf '%s' "$password" | fold -w1 | sort -u | wc -l | tr -d ' ')"
if [ "$unique_characters" -lt 10 ]; then
  echo "POSTGRES_PASSWORD tiene poca variedad de caracteres; PostgreSQL no inicializará su volumen." >&2
  exit 2
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
