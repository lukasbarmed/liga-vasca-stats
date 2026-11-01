# Liga Vasca Stats

Aplicación web para analizar estadísticas avanzadas de equipos de la Liga Vasca de baloncesto
(datos de [basketbasko.com](https://basketbasko.com/es/group/?id=2879)).

- **Acceso con usuario y contraseña**, roles `gestor` y `usuario` (misma web; solo el gestor crea usuarios y define métricas).
- **Scraping** de cada partido: estadísticas (resumen + tiros) y jugada a jugada. Botón *Actualizar estadísticas* con la fecha de la última jornada actualizada.
- **Vistas**: comparativa general de la liga, ficha de equipo, comparativa de dos equipos.
- **Estadísticas básicas y avanzadas** (posesiones, eFG%, TS%, ratings, %pérdidas y pérdidas forzadas, %rebote, uso del T3 y T3 permitido, ratio de TL, etc.).
- **Métricas personalizadas** creadas por los gestores a partir de las básicas (fórmulas validadas, sin ejecutar código).
- **Jugadores** (incluye USG%, TS%, +/-) y **combinaciones en pista**: parejas, tríos, cuartetos y quintetos reconstruidos del jugada a jugada.

## Fuente de datos

Por partido se usan tres peticiones (las ves en la pestaña *Network* del navegador):

| Qué | URL |
|---|---|
| Ficha (uid, fecha, jornada) | `https://esb.optimalwayconsulting.com/esf/1/<token>/FCBQWeb/fitxaPartit/<idPartido>` (respuesta en Base64) |
| Estadísticas | `https://msstats.optimalwayconsulting.com/v1/esf/getJsonWithMatchStats/<uid>?currentSeason=true` |
| Jugada a jugada | `https://msstats.optimalwayconsulting.com/v1/esf/getJsonWithMatchMoves/<uid>?currentSeason=true` |

### Listado de partidos de cada jornada

El listado de la web (`group/?id=2879&round=N`) lo carga JavaScript, así que el scraper prueba varias estrategias en este orden
y usa la primera que devuelva partidos (el botón *Actualizar* y `python -m app.cli update` hacen lo mismo):

1. **`MATCHDAY_URL`** (opcional): plantilla propia con `{group_id}` y `{matchday}`, si la copias de la pestaña *Network* (F12 → Fetch/XHR).
2. **Listado del grupo** (`GROUP_MATCHES_URL`): `…/FCBQWeb/getAllGamesByGrupWithMatchRecords/<grupo>`, método de la plataforma OW Basket.
3. **Barrido de fichas** alrededor de `SEED_MATCH_ID` (por defecto 99555, ±`SCAN_RADIUS` ids): se descargan las fichas y se conservan las del mismo
   grupo (categoría + competición + grupo). Los que no son del grupo se recuerdan para no repetirlos.

Las estrategias 2 y 3 no se han podido probar contra la web real desde el entorno de desarrollo (solo con respuestas simuladas).
**Antes de nada ejecuta `python -m app.cli diagnose`**: prueba la ficha, las estadísticas, el jugada a jugada y cada estrategia por separado, e indica
cuál funciona. Si ninguna lo hace, pega la salida y la petición de red de la jornada para ajustar `find_matches()` en `app/scraper.py`.

Cargar un partido suelto: `python -m app.cli import-match 99555 --matchday 7`.

### Supuestos que conviene verificar con datos reales

Se escribió contra la estructura de los JSON, pero sin poder descargarlos desde el entorno de desarrollo. La ingesta avisa en el log
(`Partido …: puntos=… pero tiros suman …`) si los campos no cuadran. Comprobar:

- `shotsOfOne*` = tiros libres, `shotsOfTwo*` / `shotsOfThree*` = T2 / T3 (se valida que puntos = TL + 2·T2 + 3·T3).
- Los totales de equipo se calculan sumando jugadores: **no incluyen rebotes/pérdidas «de equipo»** si la web los registra aparte.
- El reloj del jugada a jugada (cuenta atrás o ascendente) y el orden del array se detectan automáticamente (`matches.clock_mode`).
- Quintetos: parten de `starting` (quinteto inicial) y de los eventos 112/115 (entra/sale). Si faltan sustituciones en el origen, los quintetos se desviarán.
- Las posesiones se estiman: `TC intentados + 0,44·TL − RO + pérdidas`.

## Ejecutar en local (sin Docker)

**Windows**: instala [Python 3.10+](https://www.python.org/downloads/) (marcando *Add python.exe to PATH*), descomprime y haz doble clic en `iniciar.bat`.
**Linux/macOS**: `./iniciar.sh`.
La primera vez crea el entorno, pide el usuario gestor y abre `http://127.0.0.1:8000`. Los datos quedan en `./data`.
Pulsa *Actualizar estadísticas* para descargar los partidos. Para verla desde otros equipos de tu red: `HOST=0.0.0.0` (y usa contraseñas fuertes).

Para desarrollo:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
python -m app.cli diagnose      # comprueba el acceso a los datos reales
```

## Subir el código a GitHub

```bash
git init -b main && git add . && git commit -m "Liga Vasca Stats"
# crea un repositorio vacío en github.com/new (privado recomendado) y:
git remote add origin git@github.com:TU_USUARIO/liga-vasca-stats.git
git push -u origin main
```

## Despliegue permanente

La base de datos es un archivo SQLite, así que **el servidor necesita un disco persistente** (`/data`).
Usa un solo proceso (el estado del botón *Actualizar* vive en memoria; el Dockerfile ya lo hace). Elige una opción:

- **Fly.io** (`fly.toml`): `fly launch --no-deploy --copy-config`, `fly volumes create appdata --size 1 --region mad`,
  `fly secrets set SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))") ADMIN_PASSWORD=... MATCHDAY_URL=...`, `fly deploy`.
- **Render** (`render.yaml`): *New → Blueprint* apuntando al repositorio; el disco persistente requiere plan de pago.
- **VPS propio** (`docker-compose.yml` + `Caddyfile`): cambia `TU_DOMINIO`, crea `.env` y `docker compose up -d --build` (HTTPS automático).

Comprueba precios y planes vigentes de cada proveedor antes de elegir.

**Mantenimiento**: haz copia periódica del volumen (`sqlite3 /data/app.db ".backup /ruta/copia.db"`). Los partidos se pueden volver a
descargar; lo que no se recupera son los usuarios y las métricas personalizadas. Cada `git push` ejecuta los tests (GitHub Actions).

## Seguridad

Contraseñas con scrypt, sesiones firmadas con `SECRET_KEY`, protección CSRF en todos los formularios, límite de intentos de login,
cabeceras CSP y fórmulas de métricas evaluadas con un intérprete restringido (solo `+ - * /`, `min`, `max`, `abs`). Define siempre
`SECRET_KEY` y `COOKIE_SECURE=1` en producción.

## Métricas personalizadas

Menú *Gestión → Métricas avanzadas*. Las variables son totales acumulados (`pts`, `fga`, `fg3m`, `fta`, `orb`, `tov`, `poss`, `games`,
`mins`…) y su versión del rival con prefijo `opp_`. Ejemplos: `pts/poss`, `100*fg3m*3/pts`, `(ast+stl)/tov`.

## Estructura

```
app/main.py      rutas Flask, login, roles, gestión
app/scraper.py   descarga y actualización (+ estado del botón)
app/ingest.py    JSON de partido -> BD, reconstrucción de quintetos
app/stats.py     métricas básicas/avanzadas, jugadores, combinaciones
app/formula.py   evaluador seguro de fórmulas
tests/           pruebas con partidos sintéticos
```
