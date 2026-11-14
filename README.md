# Space Apps Mentor

CRM para que los mentores de Space Apps Valencia 2026 sigan equipos, miembros, retos NASA y sus notas de mentoría.

- **Equipos, miembros, reto, fase, visitas** → compartidos entre todos los mentores (servidor).
- **Notas de sesión y notas sobre miembros** → privadas, solo en el navegador de cada mentor (localStorage). Nunca llegan al servidor.

## Dos modos

| | Local | Compartido (Render) |
|---|---|---|
| Base de datos | SQLite en `data/` | Postgres (`DATABASE_URL`) |
| Acceso | Sin login, solo 127.0.0.1 | Contraseña común + nombre de mentor |
| Dependencias | Ninguna (Python 3.9+) | `requirements.txt` |

## Arrancar en local

- macOS: doble clic en `Iniciar Space Apps.command` (la primera vez, clic derecho > Abrir).
- Terminal: `python3 server.py` y abre http://127.0.0.1:8766/

## Desplegar en Render (gratis)

1. Sube esta carpeta a un repo de GitHub (puede ser privado). `data/` está ignorada, no se sube.
2. En https://dashboard.render.com: **New > Blueprint**, conecta GitHub y elige el repo. Render lee `render.yaml` y crea:
   - `spaceapps-mentores`: web service gratuito (Frankfurt).
   - `spaceapps-db`: Postgres gratuito.
3. Te pedirá **MENTOR_PASSWORD**: la contraseña común que compartirás con los mentores. `SECRET_KEY` se genera solo.
4. Espera al primer deploy y abre `https://spaceapps-mentores.onrender.com` (o el nombre que te asigne).
5. **Dominio**: en el servicio > Settings > Custom Domains > añade `mentores.spaceappsvalencia.es`. Render te dará un destino; el organizador crea en el DNS de OVH un registro `CNAME mentores → spaceapps-mentores.onrender.com`. El HTTPS se activa solo.

Cada `git push` a la rama principal redespliega automáticamente.

### Límites del plan gratuito

- **Se duerme tras 15 min sin visitas**; el primer acceso tarda ~1 min. Para evitarlo durante el evento, crea un monitor gratuito (p. ej. UptimeRobot) que pida `https://mentores.spaceappsvalencia.es/healthz` cada 5 min. Las 750 h gratuitas al mes cubren un servicio encendido 24/7.
- **El Postgres gratuito caduca a los 30 días** (más 14 de gracia) y no tiene copias. De sobra para el finde: exporta los equipos al terminar (menú de datos > Exportar equipos JSON).

### Variables de entorno

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | Postgres. Si falta, usa SQLite local. |
| `MENTOR_PASSWORD` | Activa el login. Si falta, no hay login (solo para local). |
| `SECRET_KEY` | Firma las cookies de sesión (7 días). |
| `ALLOWED_HOSTS` | Dominios aceptados, separados por comas; `.onrender.com` acepta subdominios. |
| `PORT` | Lo pone Render; activa modo nube (escucha en 0.0.0.0, no abre navegador). |

## Notas privadas: qué contar a los mentores

- Se guardan solo en el navegador donde las escriben. Otro navegador u ordenador = notas vacías.
- Si borran los datos del navegador o usan modo incógnito, se pierden.
- Menú de datos (icono de descarga) > **Descargar copia de mis notas** / **Recuperar mis notas**.
- Guardar una nota marca la visita al equipo para todos ("Última visita · por Marta"), sin revelar el contenido.

## Refrescar equipos desde NASA

La web oficial (https://www.spaceappschallenge.org/2026/local-events/valencia/?tab=teams) es la fuente de la verdad. En el CRM: **Equipos > ⟳ Refrescar desde NASA** (o menú de datos).

1. Solo la primera vez: arrastra el botón «📡 Equipos NASA → CRM» del modal a la barra de marcadores.
2. Abre la página de equipos de Valencia y pulsa el marcador: carga la lista entera (scroll infinito), lee la pestaña Members de cada equipo (~2 s por equipo) y comprueba que tiene tantos como dice la página («Currently returning N teams»). Si falta alguno, no genera nada.
3. «Copiar JSON», vuelve al CRM, pégalo y pulsa **Revisar cambios**: verás equipos nuevos, cambios (nombre, reto, miembros + / −) y los que **se borrarán**.
4. Marca la casilla de confirmación y pulsa **Sobrescribir**.

Qué manda NASA: qué equipos existen, nombre, reto y lista de miembros. Qué se conserva: fase, ★, mesa, idea/problema/solución/enlaces, visitas, métodos y el rol/skills de quien siga en el equipo. Los equipos que no estén en NASA (también los creados a mano) se borran. Si otro mentor cambia algo entre la revisión y la confirmación, pide revisar de nuevo. Un JSON con menos equipos de los que anuncia la web se rechaza.

Desde la terminal (mismo comportamiento): `python3 import_nasa.py` muestra los cambios con `nasa/teams_valencia.json`, `--yes` los aplica (con `DATABASE_URL` va contra Render).

## Backups

- Local: al arrancar se copia `data/spaceapps.sqlite3` a `data/backups/` (se guardan las 10 últimas).
- Compartido: menú de datos > Exportar equipos JSON. "Importar equipos JSON" reemplaza los equipos de todos.

## Tests

```
python3 -m unittest discover -s . -p 'test_*.py' -v
# Repetir contra Postgres:
TEST_DATABASE_URL="postgresql://usuario@host/bd" python3 -m unittest discover -s . -p 'test_*.py'
```
