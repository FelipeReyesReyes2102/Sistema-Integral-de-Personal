#!/usr/bin/env bash
# Respaldo lógico de la base de SIP-O (pg_dump en formato custom), sin detener la aplicación.
# Uso:  ./respaldo.sh [carpeta_destino]     (por defecto /home/jose/sip-o-backups)
# Restaurar: ver deploy/DESPLIEGUE.md, sección "Recuperación".
set -euo pipefail

DESTINO="${1:-/home/jose/sip-o-backups}"
FECHA="$(date +%Y%m%d-%H%M%S)"
ARCHIVO="${DESTINO}/sip_o-${FECHA}.dump"

umask 077
mkdir -p "$DESTINO"
chmod 700 "$DESTINO"

docker exec sip-o-db-1 pg_dump -U sip_o -d sip_o -Fc > "${ARCHIVO}.parcial"
mv "${ARCHIVO}.parcial" "$ARCHIVO"
chmod 600 "$ARCHIVO"
sha256sum "$ARCHIVO" > "${ARCHIVO}.sha256"

# Verifica que el respaldo se pueda leer (lista su contenido sin restaurarlo)
docker exec -i sip-o-db-1 pg_restore --list < "$ARCHIVO" > /dev/null

echo "Respaldo listo: $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"
# Conserva los últimos 30 respaldos de esta carpeta
ls -1t "$DESTINO"/sip_o-*.dump 2>/dev/null | tail -n +31 | while read -r viejo; do rm -f -- "$viejo" "$viejo.sha256"; done
