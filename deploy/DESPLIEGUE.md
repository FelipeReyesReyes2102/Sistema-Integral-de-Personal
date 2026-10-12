# Despliegue de SIP-O en otkmex-server

| Elemento | Valor |
|---|---|
| URL | https://sip-o.otek.internal |
| Proyecto Compose | `sip-o` (servicios `db`, `api`, `web`) |
| Imágenes | `sip-o-api:<sha7>`, `sip-o-web:<sha7>`, `postgres:16-bookworm` |
| Puerto | `127.0.0.1:8085` → contenedor `web:8080` (solo loopback; lo expone Nginx) |
| Red | `sip-o_red` (172.29.0.0/24) |
| Volumen | `sip-o_pgdata` (datos de PostgreSQL: incluye fotos, firmas y consultas) |
| Código por versión | `/home/jose/sip-o-<sha7>/` (se conservan las versiones anteriores) |
| Paquetes | `/home/jose/sip-o-releases/sip-o-<sha7>.tar.gz` + `.sha256` |
| Secretos | `/home/jose/sip-o-secrets/` (700): `app.env`, `db.env` (600) — **no están en Git** |
| Configuración de versión | `/home/jose/sip-o-<sha7>/deploy/despliegue.env` (sin secretos) |
| Respaldos | `/home/jose/sip-o-backups/` (700) |
| Nginx | `/etc/nginx/sites-available/sip-o` |
| Certificado | `/etc/nginx/ssl/sip-o/` (`fullchain.crt`, `server.key` 600), firmado por la CA interna |

## Comandos seguros de consulta

```bash
cd /home/jose/sip-o-<sha7>/deploy
C="docker compose -p sip-o --env-file despliegue.env -f compose.yaml"
$C ps                                   # estado y salud
$C logs --tail 100 api                  # registros de la API
curl -s http://127.0.0.1:8085/api/health   # salud (no muestra secretos)
$C config --quiet && echo "compose válido"  # nunca sin --quiet: mostraría secretos
```

## Actualizar a una nueva versión

1. En Windows: `git archive --format=tar.gz --prefix=sip-o-<sha7>/ -o sip-o-<sha7>.tar.gz <sha>`, calcular SHA256 y `scp` a `/home/jose/sip-o-releases/`.
2. En el servidor: comparar `sha256sum`, extraer en `/home/jose/` (crea `sip-o-<sha7>/`), copiar `deploy/despliegue.env` de la versión anterior y cambiar `SIP_VERSION`.
3. **Respaldo:** `bash deploy/respaldo.sh`.
4. `$C build` (las imágenes nuevas quedan junto a las anteriores).
5. `$C run --rm api python -m app.migrar` (migración controlada).
6. `$C up -d api web` y verificar `$C ps`, `/api/health` y el inicio de sesión.

## Reversión

1. `cd /home/jose/sip-o-<sha7_anterior>/deploy` y `$C up -d api web` (sus imágenes siguen etiquetadas).
2. Si la versión nueva hizo una migración incompatible, restaurar el respaldo tomado antes de actualizar (ver abajo).

## Respaldo y recuperación

- Respaldo: `bash /home/jose/sip-o-<sha7>/deploy/respaldo.sh` → `/home/jose/sip-o-backups/sip_o-AAAAMMDD-HHMMSS.dump` (+ `.sha256`).
  Recomendado: programarlo diario con `crontab -e` (p. ej. `30 2 * * * bash /home/jose/sip-o-<sha7>/deploy/respaldo.sh`).
- Recuperación (reemplaza los datos actuales; hacerlo solo con autorización):
  ```bash
  $C stop api web
  sha256sum -c /home/jose/sip-o-backups/sip_o-XXXX.dump.sha256
  docker exec -i sip-o-db-1 pg_restore -U sip_o -d sip_o --clean --if-exists < /home/jose/sip-o-backups/sip_o-XXXX.dump
  $C start api web
  ```

## Primer arranque (referencia)

```bash
$C up -d db                                   # base primero; esperar "healthy"
$C run --rm api python -m app.migrar          # crea las tablas
$C run --rm api python -m app.seed --solo-catalogos
$C run --rm api python -m app.crear_superadmin --email ... --nombre "..." --nomina ...   # pide la contraseña
$C up -d api web
```

## Notas

- La API corre con **un solo proceso** (tareas de rotación y avisos de los viernes); no escalar `api`.
- Zona horaria de la aplicación: `America/Mexico_City`.
- Microsoft Entra ID: registrar `https://sip-o.otek.internal/api/auth/microsoft/callback` (plataforma Web).
- Prohibido: `docker compose down -v`, `docker volume rm sip-o_pgdata`, `prune`.
