# Space Apps Mentor — especificación del núcleo (fase 1)

App local de un solo usuario (Ale, mentor de todos los equipos de Space Apps Valencia, 13–15 nov 2026) para seguir equipos, miembros, retos oficiales NASA y notas de mentoría. Sin login. Todo en español (es-ES).

## Restricciones de stack (obligatorias, copiadas de Ventura Studio)
- Python 3.9+ SOLO librería estándar: `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`, `sqlite3`, `json`, `argparse`, `webbrowser`, `re`. Nada de pip, Flask, etc.
- Frontend vanilla HTML/CSS/JS sin build, sin npm, sin frameworks, sin CDN (salvo el `<link>` a Google Fonts con fallback de sistema). Debe funcionar sin internet.
- Pruebas con `unittest`: `python3 -m unittest discover -s . -p 'test_*.py' -v`.
- Compatible con Python 3.9 (nada de `match`, ni `X | Y` en anotaciones de tipos en runtime).

## Estructura
```
server.py            # HTTP + router + estáticos + arranque (argparse: --host 127.0.0.1 --port 8766 --no-browser --data-dir data)
store.py             # capa SQLite: esquema, migración idempotente, seed, CRUD, export/import, búsqueda
seed.json            # retos NASA 2026 + metodologías (lo genera otro agente; formato abajo)
dist/index.html, dist/app.js, dist/styles.css
test_store.py, test_server.py
Iniciar Space Apps.command   # #!/bin/zsh; cd -- "${0:A:h}" || exit 1; python3 server.py; read -r "?Pulsa Intro para cerrar."
README.md, .gitignore (data/, __pycache__/)
data/spaceapps.sqlite3  # creado en runtime
```

## Listas fijas (en store.py, expuestas en /api/state)
- PHASES (orden): `idea`→"Idea", `problema`→"Problema validado", `mvp`→"MVP", `demo`→"Demo", `pitch`→"Pitch listo", `entregado`→"Entregado".
- ROLES: `dev`→"Desarrollo", `diseno`→"Diseño", `negocio`→"Negocio", `ciencia`→"Ciencia/Datos", `otro`→"Otro".
- NOTE_KINDS: `mentoria`→"Mentoría", `pitch`→"Pitch", `otro`→"Otro".

## Esquema SQLite (PRAGMA foreign_keys=ON; fechas ISO 8601 UTC con 'Z', p. ej. `2026-11-13T19:45:00Z`)
```sql
challenges(id INTEGER PRIMARY KEY, num INTEGER, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL, title_en TEXT, category TEXT, summary TEXT, difficulty TEXT, url TEXT)
teams(id INTEGER PRIMARY KEY, name TEXT NOT NULL, table_label TEXT DEFAULT '', idea TEXT DEFAULT '', problem TEXT DEFAULT '', solution TEXT DEFAULT '', phase TEXT NOT NULL DEFAULT 'idea', challenge_id INTEGER REFERENCES challenges(id) ON DELETE SET NULL, links TEXT DEFAULT '', attention INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_visit_at TEXT)
members(id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, name TEXT NOT NULL, role TEXT DEFAULT 'otro', skills TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT NOT NULL)
notes(id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, kind TEXT NOT NULL DEFAULT 'mentoria', body TEXT NOT NULL DEFAULT '', blockers TEXT DEFAULT '', next_steps TEXT DEFAULT '', created_at TEXT NOT NULL)
methods(id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, summary TEXT, when_to_use TEXT, steps TEXT, key_questions TEXT, template TEXT)   -- steps/key_questions = JSON arrays
team_methods(team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE, method_id INTEGER REFERENCES methods(id) ON DELETE CASCADE, status TEXT DEFAULT 'pendiente', PRIMARY KEY(team_id, method_id))  -- reservado para fase 2
```
Seed: al arrancar, upsert por `slug` de challenges y methods desde seed.json (no toca teams). Validar phase/role/kind contra las listas (400 si no válido). Crear una nota actualiza `teams.last_visit_at` y `updated_at`.

## seed.json
```json
{"challenges":[{"num":1,"slug":"nasas-discarded-equipment-storytelling","title":"…es…","title_en":"…","category":"…","summary":"…","difficulty":"Intermedio · Principiante","url":"https://www.spaceappschallenge.org/2026/challenges/<slug>/"}],
 "methods":[{"slug":"lean-canvas","name":"Lean Canvas","summary":"…","when_to_use":"…","steps":["…"],"key_questions":["…"],"template":"texto/markdown"}]}
```

## API JSON (todas las respuestas `application/json; charset=utf-8`; errores `{"error":"mensaje en español"}` con 400/404/405)
- `GET /api/state` → `{phases:[{key,label}], roles:[…], note_kinds:[…], challenges:[{…challenge, team_count}], teams:[{…team, member_count, challenge_title, challenge_num, last_note:{body,created_at}|null}], methods:[{…, steps:[…], key_questions:[…]}]}`
- `GET /api/teams/<id>` → `{…team, challenge:{…}|null, members:[…], notes:[… más reciente primero]}`
- `POST /api/teams` body `{name (obligatorio), table_label?, idea?, problem?, solution?, phase?, challenge_id?, links?, attention?, members?:[{name, role?, skills?, notes?}]}` → 201 + detalle del equipo
- `PATCH /api/teams/<id>` campos parciales de los anteriores (sin members) → detalle
- `DELETE /api/teams/<id>` → `{ok:true}`
- `POST /api/teams/<id>/members` `{name, role?, skills?, notes?}` → 201 miembro; `PATCH /api/members/<id>`; `DELETE /api/members/<id>`
- `POST /api/teams/<id>/notes` `{kind?, body, blockers?, next_steps?}` (body o blockers o next_steps no vacíos) → 201 nota; `PATCH /api/notes/<id>`; `DELETE /api/notes/<id>`
- `GET /api/challenges/<id>` → `{…challenge, teams:[…]}`
- `GET /api/search?q=texto` → `{teams:[…], members:[{…, team_name}], notes:[{…, team_name}]}` (LIKE, sin distinguir mayúsculas, máx. 20 por tipo)
- `GET /api/export` → volcado completo `{version:1, exported_at, teams, members, notes, team_methods}` con `Content-Disposition: attachment; filename="spaceapps-YYYYMMDD-HHMM.json"`
- `POST /api/import` body = un export → reemplaza teams/members/notes/team_methods en una transacción (conserva ids) → `{ok:true, teams:n}`
- Estáticos: `/` → dist/index.html; `/app.js`, `/styles.css` y cualquier fichero de dist/ (evitar path traversal). Cache-Control: no-store.
- Seguridad mínima como Studio: rechazar (403) si la cabecera Host no es localhost/127.0.0.1(:puerto); en POST/PATCH/DELETE rechazar si hay Origin y no coincide con el host. Body JSON máx. 5 MB.
- Al arrancar: imprimir la URL y abrir el navegador (`webbrowser.open`) salvo `--no-browser`. Backup: al arrancar copiar la BD existente a `data/backups/spaceapps-<timestamp>.sqlite3` (conservar las 10 últimas).

## UI (SPA con hash routing, dist/)
Cabecera fija estilo `.navbar-space`: marca "SPACE APPS" + `.brand-badge` "VALENCIA 2026" + "MENTOR"; nav: Tablero (#/), Equipos (#/equipos), Retos (#/retos), Metodologías (#/metodologias); buscador global (atajo `/`); botón primario "+ Equipo" (atajo `n`). Pill tipo telemetría con hora actual y cuenta atrás al pitch final (2026-11-15 16:00 Europe/Madrid = 15:00Z).

1. **Tablero `#/`**: kanban con una columna por fase. Tarjeta de equipo (glass-card compacta): nombre, mesa, nº/título corto del reto, nº miembros, "última visita hace X" (rojo/naranja si > 90 min o nunca), estrella de atención. Ordenar por atención primero y luego visita más antigua. Arrastrar tarjeta a otra columna = PATCH phase. Clic → ficha. Contadores por columna. Filtro por reto.
2. **Equipos `#/equipos`**: tabla con todos los equipos (nombre, mesa, reto, fase, miembros, última visita), ordenable.
3. **Ficha `#/equipos/<id>`**: cabecera con nombre, mesa, selector de fase (pills clicables), selector de reto, estrella atención, borrar (con confirmación). Bloques editables con autoguardado al salir del campo (blur): idea en una frase, problema, solución, enlaces. Panel de miembros: lista con nombre, rol (select), skills, notas libres; añadir en línea; borrar. Panel de **notas de sesión**: formulario arriba (tipo, nota, bloqueos, siguientes pasos; Ctrl/Cmd+Enter guarda) y cronología debajo (más reciente primero, hora local, editar/borrar). Mostrar resumen del reto con enlace a la NASA.
4. **Alta rápida (modal)**: nombre, mesa, reto (select con nº + título), idea, y filas de miembros (nombre + rol + skills) añadibles con Enter. Objetivo: alta en < 1 min. Tras guardar, ir a la ficha.
5. **Retos `#/retos`**: rejilla de 14 tarjetas (nº, categoría, título, resumen, dificultad como chips, nº de equipos, enlace "Ver reto ↗"). `#/retos/<id>`: detalle + equipos que lo trabajan.
6. **Metodologías `#/metodologias`**: lista de fichas (solo lectura) con resumen, cuándo usarla, pasos, preguntas clave y plantilla (botón copiar).
7. **Ajustes/datos** (pequeño menú o pie): Exportar JSON, Importar JSON (con confirmación de reemplazo).

Detalles: textos en español, fechas en hora local con `Intl` es-ES, toasts para guardado/errores, estados vacíos útiles ("Aún no hay equipos — pulsa n"), accesible por teclado, `Escape` cierra modales. Diseño pensado para portátil (≥ 1280 px), usable a 1024 px. Refresco automático del tablero cada 60 s para actualizar los "hace X min".
