#!/bin/sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="${1:-$PROJECT_DIR/.env}"
ERRORS=0
WARNINGS=0

fail() { printf 'ERROR: %s\n' "$1" >&2; ERRORS=$((ERRORS + 1)); }
warn() { printf 'AVISO: %s\n' "$1" >&2; WARNINGS=$((WARNINGS + 1)); }
ok() { printf 'OK: %s\n' "$1"; }

if [ ! -f "$ENV_FILE" ]; then
  printf 'ERROR: No se encontró el archivo .env indicado.\n' >&2
  exit 2
fi

env_count() {
  awk -v key="$1" '$0 !~ /^[[:space:]]*#/ { line=$0; sub(/^[[:space:]]*/, "", line); if (line ~ ("^" key "[[:space:]]*=")) count++ } END { print count+0 }' "$ENV_FILE"
}

env_value() {
  awk -v key="$1" '
    $0 !~ /^[[:space:]]*#/ {
      line=$0
      sub(/^[[:space:]]*/, "", line)
      if (line ~ ("^" key "[[:space:]]*=")) {
        sub(/^[^=]*=/, "", line)
        sub(/\r$/, "", line)
        sub(/^[[:space:]]*/, "", line)
        sub(/[[:space:]]*$/, "", line)
        if (length(line) >= 2 && substr(line, 1, 1) == "\"" && substr(line, length(line), 1) == "\"") line=substr(line, 2, length(line)-2)
        print line
        exit
      }
    }
  ' "$ENV_FILE"
}

check_secret() {
  name="$1"
  minimum="$2"
  count="$(env_count "$name")"
  value="$(env_value "$name")"
  if [ "$count" -ne 1 ]; then
    fail "$name debe aparecer exactamente una vez en .env."
    return
  fi
  lowered="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  case "$lowered" in
    ""|*replace-with*|*change-me*|*changeme*|*example-secret*|*local-only*)
      fail "$name falta o conserva un valor de ejemplo."
      return
      ;;
  esac
  if [ "${#value}" -lt "$minimum" ]; then
    fail "$name debe tener al menos $minimum caracteres."
    return
  fi
  if [ "$value" != "$(printf '%s' "$value" | tr -d '[:space:]')" ]; then
    fail "$name no debe contener espacios ni saltos de línea."
    return
  fi
  ok "$name tiene formato y longitud mínimos; su valor no se muestra."
}

check_secret POSTGRES_PASSWORD 24
check_secret DJANGO_SECRET_KEY 50
if [ "$(env_value POSTGRES_PASSWORD)" = "$(env_value DJANGO_SECRET_KEY)" ]; then
  fail "POSTGRES_PASSWORD y DJANGO_SECRET_KEY deben ser secretos distintos."
fi

proxy_enabled="$(env_value DJANGO_USE_HTTPS_PROXY | tr '[:upper:]' '[:lower:]')"
[ -n "$proxy_enabled" ] || proxy_enabled=false
secure_cookies="$(env_value DJANGO_SECURE_COOKIES | tr '[:upper:]' '[:lower:]')"
[ -n "$secure_cookies" ] || secure_cookies=false
ssl_redirect="$(env_value DJANGO_SECURE_SSL_REDIRECT | tr '[:upper:]' '[:lower:]')"
[ -n "$ssl_redirect" ] || ssl_redirect=false
public_leads="$(env_value ERP_PUBLIC_LEADS_ENABLED | tr '[:upper:]' '[:lower:]')"
[ -n "$public_leads" ] || public_leads=false
publish_address="$(env_value APP_BIND_ADDRESS)"
[ -n "$publish_address" ] || publish_address=0.0.0.0
hsts_seconds="$(env_value DJANGO_SECURE_HSTS_SECONDS)"
[ -n "$hsts_seconds" ] || hsts_seconds=0

for setting in DJANGO_USE_HTTPS_PROXY DJANGO_SECURE_COOKIES DJANGO_SECURE_SSL_REDIRECT ERP_PUBLIC_LEADS_ENABLED; do
  case "$setting" in
    DJANGO_USE_HTTPS_PROXY) value="$proxy_enabled" ;;
    DJANGO_SECURE_COOKIES) value="$secure_cookies" ;;
    DJANGO_SECURE_SSL_REDIRECT) value="$ssl_redirect" ;;
    ERP_PUBLIC_LEADS_ENABLED) value="$public_leads" ;;
  esac
  case "$value" in
    true|false) ;;
    *) fail "$setting debe ser true o false." ;;
  esac
done

if [ "$proxy_enabled" = true ] && [ "$publish_address" != 127.0.0.1 ]; then
  fail "DJANGO_USE_HTTPS_PROXY=true requiere APP_BIND_ADDRESS=127.0.0.1 para limitar el puerto del NAS al proxy DSM."
fi
if [ "$ssl_redirect" = true ] && [ "$proxy_enabled" != true ]; then
  fail "DJANGO_SECURE_SSL_REDIRECT=true requiere DJANGO_USE_HTTPS_PROXY=true."
fi
if [ "$secure_cookies" = true ] && [ "$proxy_enabled" != true ]; then
  fail "DJANGO_SECURE_COOKIES=true requiere DJANGO_USE_HTTPS_PROXY=true."
fi
case "$hsts_seconds" in
  ""|*[!0-9]*) fail "DJANGO_SECURE_HSTS_SECONDS debe ser un entero no negativo." ;;
  *)
    if [ "$hsts_seconds" -gt 0 ] && { [ "$proxy_enabled" != true ] || [ "$secure_cookies" != true ]; }; then
      fail "HSTS requiere DJANGO_USE_HTTPS_PROXY=true y DJANGO_SECURE_COOKIES=true."
    fi
    ;;
esac
if [ "$public_leads" = true ]; then
  privacy_url="$(env_value ERP_PRIVACY_URL)"
  case "$privacy_url" in
    https://*) ;;
    *) fail "ERP_PUBLIC_LEADS_ENABLED=true requiere ERP_PRIVACY_URL con HTTPS." ;;
  esac
  if [ "$proxy_enabled" != true ] || [ "$publish_address" != 127.0.0.1 ]; then
    fail "ERP_PUBLIC_LEADS_ENABLED=true requiere proxy HTTPS y APP_BIND_ADDRESS=127.0.0.1."
  fi
fi

check_directory() {
  name="$1"
  value="$(env_value "$name")"
  if [ -z "$value" ]; then
    fail "$name está vacío."
    return
  fi
  case "$value" in
    /*) ;;
    *) fail "$name debe ser una ruta absoluta del NAS."; return ;;
  esac
  if [ ! -d "$value" ]; then
    fail "$name no existe como carpeta; créala antes del primer arranque."
  elif [ ! -w "$value" ]; then
    fail "$name no permite escritura al usuario que ejecuta esta revisión; confirma también los permisos del usuario ContainerManager."
  else
    ok "$name existe y permite escritura al usuario de esta revisión."
  fi
}

check_directory POSTGRES_DATA_PATH
check_directory BACKUP_PATH
check_directory MEDIA_PATH

gid="$(env_value ERP_DATA_GID)"
case "$gid" in
  ""|*[!0-9]*|0) fail "ERP_DATA_GID debe ser el GID numérico positivo del grupo DSM dedicado." ;;
  *) ok "ERP_DATA_GID es numérico; confirma en DSM que corresponde al grupo dedicado." ;;
esac

environment="$(env_value FEL_ENVIRONMENT | tr '[:upper:]' '[:lower:]')"
allow_production="$(env_value FEL_ALLOW_PRODUCTION | tr '[:upper:]' '[:lower:]')"
allow_cancellation="$(env_value FEL_ALLOW_CANCELLATION | tr '[:upper:]' '[:lower:]')"
[ -n "$environment" ] || environment=test
[ -n "$allow_production" ] || allow_production=false
[ -n "$allow_cancellation" ] || allow_cancellation=false
case "$environment" in
  test|production) ok "FEL_ENVIRONMENT usa un valor reconocido." ;;
  *) fail "FEL_ENVIRONMENT debe ser test o production." ;;
esac
case "$allow_production" in
  true|false) ;;
  *) fail "FEL_ALLOW_PRODUCTION debe ser true o false." ;;
esac
if [ "$environment" = "production" ] && [ "$allow_production" != "true" ]; then
  fail "La producción FEL requiere FEL_ALLOW_PRODUCTION=true además de la revisión operativa y contable."
fi
if [ "$environment" = "production" ]; then
  fel_user="$(env_value FEL_TIMBRADO_USER)"
  fel_password="$(env_value FEL_TIMBRADO_PASSWORD)"
  if [ "${#fel_user}" -lt 12 ] || [ "${#fel_user}" -gt 13 ]; then
    fail "FEL_TIMBRADO_USER debe tener entre 12 y 13 caracteres en producción."
  fi
  if [ "${#fel_password}" -lt 6 ]; then
    fail "FEL_TIMBRADO_PASSWORD debe tener al menos 6 caracteres en producción."
  fi
fi
case "$allow_cancellation" in
  true)
    if [ "$environment" != "production" ] || [ "$allow_production" != "true" ]; then
      fail "FEL_ALLOW_CANCELLATION=true requiere producción FEL habilitada."
    fi
    if [ -z "$(env_value FEL_CANCEL_PFX_BASE64)" ] || [ -z "$(env_value FEL_CANCEL_PFX_PASSWORD)" ]; then
      fail "Las cancelaciones FEL requieren FEL_CANCEL_PFX_BASE64 y FEL_CANCEL_PFX_PASSWORD."
    fi
    ;;
  false) ;;
  *) fail "FEL_ALLOW_CANCELLATION debe ser true o false." ;;
esac

csd_path="$(env_value CFDI_CSD_HOST_PATH)"
if [ -n "$csd_path" ] && [ -d "$csd_path" ]; then
  for file in redmagna.cer redmagna.key csd_password; do
    if [ ! -r "$csd_path/$file" ]; then
      fail "No se puede leer el archivo CSD requerido: $file."
    fi
  done
elif [ "$environment" = "production" ]; then
  fail "La carpeta CFDI_CSD_HOST_PATH no existe para la configuración productiva."
else
  warn "No se encontró la carpeta CSD; se requiere para firmar CFDI, incluso en pruebas."
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  if (cd "$PROJECT_DIR" && docker compose --env-file "$ENV_FILE" config --quiet); then
    ok "docker compose config no reporta errores."
  else
    fail "docker compose encontró errores en la configuración."
  fi
elif command -v docker-compose >/dev/null 2>&1; then
  if (cd "$PROJECT_DIR" && docker-compose --env-file "$ENV_FILE" config -q); then
    ok "docker-compose config no reporta errores."
  else
    fail "docker-compose encontró errores en la configuración."
  fi
else
  warn "No está disponible el comando Compose; carga docker-compose.yml en Container Manager y revisa el análisis antes de crear el proyecto."
fi

printf '\nResultado: %s error(es), %s aviso(s).\n' "$ERRORS" "$WARNINGS"
printf 'Esta revisión no inicia contenedores, no modifica archivos y no valida credenciales con FEL.\n'
if [ "$ERRORS" -gt 0 ]; then exit 1; fi
