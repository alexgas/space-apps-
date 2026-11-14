"""Capa de datos de Space Apps Mentor.

Dos motores con el mismo SQL:
- SQLite (por defecto, uso local, solo librería estándar).
- Postgres si se pasa `database_url` (despliegue compartido; requiere psycopg).

Las notas de mentoría NO se guardan aquí: son privadas de cada mentor y viven
en el navegador (localStorage). El servidor solo guarda datos compartidos.
"""
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

log = logging.getLogger("spaceapps.store")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SEED = os.path.join(HERE, "seed.json")
DB_NAME = "spaceapps.sqlite3"
BACKUPS_TO_KEEP = 10
EXPORT_VERSION = 2
IMPORT_VERSIONS = (1, 2)

PHASES = [
    ("idea", "Idea"),
    ("problema", "Problema validado"),
    ("mvp", "MVP"),
    ("demo", "Demo"),
    ("pitch", "Pitch listo"),
    ("entregado", "Entregado"),
]
ROLES = [
    ("dev", "Desarrollo"),
    ("diseno", "Diseño"),
    ("negocio", "Negocio"),
    ("ciencia", "Ciencia/Datos"),
    ("otro", "Otro"),
]
NOTE_KINDS = [  # solo etiquetas para el front; las notas viven en el navegador
    ("mentoria", "Mentoría"),
    ("pitch", "Pitch"),
    ("otro", "Otro"),
]

TEAM_TEXT_FIELDS = ("name", "table_label", "idea", "problem", "solution", "links")
TEAM_COLUMNS = ("id", "name", "table_label", "idea", "problem", "solution", "phase",
                "challenge_id", "links", "attention", "created_at", "updated_at",
                "last_visit_at", "updated_by", "last_visit_by", "nasa_slug")
MEMBER_COLUMNS = ("id", "team_id", "name", "role", "skills", "created_at")

SCHEMA = """
CREATE TABLE IF NOT EXISTS challenges(
    id INTEGER PRIMARY KEY, num INTEGER, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
    title_en TEXT, category TEXT, summary TEXT, difficulty TEXT, url TEXT);
CREATE TABLE IF NOT EXISTS teams(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, table_label TEXT DEFAULT '',
    idea TEXT DEFAULT '', problem TEXT DEFAULT '', solution TEXT DEFAULT '',
    phase TEXT NOT NULL DEFAULT 'idea',
    challenge_id INTEGER REFERENCES challenges(id) ON DELETE SET NULL,
    links TEXT DEFAULT '', attention INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_visit_at TEXT,
    updated_by TEXT DEFAULT '', last_visit_by TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS members(
    id INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    name TEXT NOT NULL, role TEXT DEFAULT 'otro', skills TEXT DEFAULT '',
    notes TEXT DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS methods(
    id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
    summary TEXT, when_to_use TEXT, steps TEXT, key_questions TEXT, template TEXT);
CREATE TABLE IF NOT EXISTS team_methods(
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    method_id INTEGER REFERENCES methods(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'pendiente', PRIMARY KEY(team_id, method_id));
"""
# Columnas añadidas después de la v1 (para BDs ya creadas).
MIGRATIONS = [("teams", "updated_by", "TEXT DEFAULT ''"),
              ("teams", "last_visit_by", "TEXT DEFAULT ''"),
              ("teams", "nasa_slug", "TEXT DEFAULT ''")]  # ficha en spaceappschallenge.org
PG_SCHEMA = SCHEMA.replace("id INTEGER PRIMARY KEY", "id SERIAL PRIMARY KEY") + """
CREATE OR REPLACE FUNCTION fold(t text) RETURNS text LANGUAGE sql IMMUTABLE
    AS $$ SELECT lower(coalesce(t, '')) $$;
"""


class StoreError(Exception):
    """Error base con mensaje en español pensado para mostrarse al usuario."""


class ValidationError(StoreError):
    """Datos no válidos (HTTP 400)."""


class NotFound(StoreError):
    """Recurso inexistente (HTTP 404)."""


# ---------------------------------------------------------------- utilidades

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _keys(pairs):
    return [key for key, _ in pairs]


def _labelled(pairs):
    return [{"key": key, "label": label} for key, label in pairs]


def _fold(value):
    """Minúsculas con soporte Unicode (SQLite solo pliega ASCII)."""
    return value.casefold() if isinstance(value, str) else ""


def _like_pattern(text):
    escaped = text.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%"


def _text(data, key, default=""):
    """Lee un campo de texto (recortado) o devuelve `default` si no viene."""
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, str):
        raise ValidationError("El campo '%s' debe ser texto." % key)
    return value.strip()


def _choice(data, key, valid, default, label):
    value = _text(data, key, default)
    if value not in valid:
        raise ValidationError("%s no válido: '%s'. Valores permitidos: %s." %
                              (label, value, ", ".join(valid)))
    return value


def _flag(data, key, default=0):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if isinstance(value, bool) or value in (0, 1):
        return 1 if value else 0
    raise ValidationError("El campo '%s' debe ser verdadero o falso." % key)


def _row(row):
    return dict(row) if row is not None else None


def _json_list(raw):
    try:
        value = json.loads(raw) if raw else []
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _list_of_str(value):
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


# ------------------------------------------------------------------ motores

class _PgResult(object):
    """Imita lo que el código usa de un cursor sqlite3 (lastrowid, fetch*, iterar)."""

    def __init__(self, cur, want_id):
        self._cur = cur
        self.lastrowid = cur.fetchone()["id"] if want_id else None

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur.fetchall())


class _PgConn(object):
    """Adaptador: acepta el SQL estilo sqlite (`?`) y lo traduce a psycopg (`%s`)."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        upper = sql.lstrip().upper()
        want_id = (upper.startswith("INSERT") and " RETURNING " not in upper
                   and "TEAM_METHODS" not in upper)
        if want_id:
            sql += " RETURNING id"
        cur = self.raw.cursor()
        cur.execute(sql, tuple(params))
        return _PgResult(cur, want_id)

    def executescript(self, script):
        self.raw.execute(script)


# --------------------------------------------------------------------- Store

class Store:
    def __init__(self, data_dir=None, seed_path=None, backup=True, database_url=None):
        self.seed_path = seed_path if seed_path is not None else DEFAULT_SEED
        self._lock = threading.RLock()
        self.database_url = database_url
        self.is_pg = bool(database_url)
        if self.is_pg:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            self._pool = ConnectionPool(
                database_url, min_size=1, max_size=6, open=True, timeout=15,
                kwargs={"row_factory": dict_row},
                check=ConnectionPool.check_connection)
        else:
            self.data_dir = os.path.abspath(data_dir or os.path.join(HERE, "data"))
            self.db_path = os.path.join(self.data_dir, DB_NAME)
            os.makedirs(self.data_dir, exist_ok=True)
            if backup:
                self.backup_database()
        self.init_schema()
        self.seed()

    def close(self):
        if self.is_pg:
            self._pool.close()

    # -- conexión y esquema

    @contextmanager
    def _conn(self):
        if self.is_pg:
            with self._pool.connection() as raw:  # commit al salir, rollback si error
                yield _PgConn(raw)
            return
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.create_function("fold", 1, _fold)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write(self):
        """Transacción de escritura: commit al salir, rollback si hay error."""
        with self._lock:
            with self._conn() as conn:
                if self.is_pg:
                    yield conn
                else:
                    with conn:
                        yield conn

    def init_schema(self):
        with self._write() as conn:
            if self.is_pg:
                conn.executescript(PG_SCHEMA)
                for table, col, decl in MIGRATIONS:
                    conn.execute("ALTER TABLE %s ADD COLUMN IF NOT EXISTS %s %s" % (table, col, decl))
            else:
                conn.executescript(SCHEMA)
                for table, col, decl in MIGRATIONS:
                    cols = [r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)]
                    if col not in cols:
                        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))

    # -- backup (solo SQLite)

    def backup_database(self):
        """Copia la BD existente a data/backups/ y conserva las 10 últimas."""
        if self.is_pg or not os.path.exists(self.db_path):
            return None
        folder = os.path.join(self.data_dir, "backups")
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = os.path.join(folder, "spaceapps-%s.sqlite3" % stamp)
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        self._prune_backups(folder)
        return target

    @staticmethod
    def _prune_backups(folder):
        files = sorted(f for f in os.listdir(folder)
                       if f.startswith("spaceapps-") and f.endswith(".sqlite3"))
        for old in files[:-BACKUPS_TO_KEEP]:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                log.warning("No se pudo borrar la copia antigua %s", old)

    # -- seed

    def seed(self):
        data = self._load_seed()
        if not data:
            return
        with self._write() as conn:
            for item in data.get("challenges", []):
                self._upsert_challenge(conn, item)
            for item in data.get("methods", []):
                self._upsert_method(conn, item)

    def _load_seed(self):
        if not os.path.exists(self.seed_path):
            log.warning("No se encuentra seed.json (%s); se continúa sin retos ni metodologías.",
                        self.seed_path)
            return None
        try:
            with open(self.seed_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            log.warning("seed.json no se pudo leer (%s); se continúa sin él.", exc)
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _upsert_challenge(conn, item):
        slug, title = item.get("slug"), item.get("title")
        if not slug or not title:
            log.warning("Reto del seed sin slug o título, se ignora: %r", item)
            return
        values = [item.get(k) for k in ("num", "title", "title_en", "category",
                                        "summary", "difficulty", "url")]
        found = conn.execute("SELECT id FROM challenges WHERE slug=?", (slug,)).fetchone()
        if found:
            conn.execute("UPDATE challenges SET num=?, title=?, title_en=?, category=?, "
                         "summary=?, difficulty=?, url=? WHERE id=?", values + [found["id"]])
        else:
            conn.execute("INSERT INTO challenges(num,title,title_en,category,summary,"
                         "difficulty,url,slug) VALUES(?,?,?,?,?,?,?,?)", values + [slug])

    @staticmethod
    def _upsert_method(conn, item):
        slug, name = item.get("slug"), item.get("name")
        if not slug or not name:
            log.warning("Metodología del seed sin slug o nombre, se ignora: %r", item)
            return
        values = [name, item.get("summary"), item.get("when_to_use"),
                  json.dumps(_list_of_str(item.get("steps")), ensure_ascii=False),
                  json.dumps(_list_of_str(item.get("key_questions")), ensure_ascii=False),
                  item.get("template")]
        found = conn.execute("SELECT id FROM methods WHERE slug=?", (slug,)).fetchone()
        if found:
            conn.execute("UPDATE methods SET name=?, summary=?, when_to_use=?, steps=?, "
                         "key_questions=?, template=? WHERE id=?", values + [found["id"]])
        else:
            conn.execute("INSERT INTO methods(name,summary,when_to_use,steps,key_questions,"
                         "template,slug) VALUES(?,?,?,?,?,?,?)", values + [slug])

    # ------------------------------------------------------------- lecturas

    def state(self):
        with self._conn() as conn:
            return {
                "phases": _labelled(PHASES),
                "roles": _labelled(ROLES),
                "note_kinds": _labelled(NOTE_KINDS),
                "challenges": self._challenges_with_counts(conn),
                "teams": self._team_summaries(conn),
                "methods": self._methods(conn),
            }

    @staticmethod
    def _challenges_with_counts(conn):
        rows = conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM teams t WHERE t.challenge_id=c.id) AS team_count "
            "FROM challenges c ORDER BY c.num, c.id").fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _team_summaries(conn):
        rows = conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM members m WHERE m.team_id=t.id) AS member_count, "
            "c.title AS challenge_title, c.num AS challenge_num "
            "FROM teams t LEFT JOIN challenges c ON c.id=t.challenge_id ORDER BY t.id").fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _methods(conn):
        result = []
        for row in conn.execute("SELECT * FROM methods ORDER BY id").fetchall():
            method = dict(row)
            method["steps"] = _json_list(method["steps"])
            method["key_questions"] = _json_list(method["key_questions"])
            result.append(method)
        return result

    def get_team(self, team_id):
        with self._conn() as conn:
            return self._team_detail(conn, team_id)

    def _team_detail(self, conn, team_id):
        team = _row(conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone())
        if team is None:
            raise NotFound("No existe el equipo %s." % team_id)
        challenge = conn.execute("SELECT * FROM challenges WHERE id=?",
                                 (team["challenge_id"],)).fetchone()
        team["challenge"] = _row(challenge)
        team["members"] = [self._member_out(r) for r in conn.execute(
            "SELECT * FROM members WHERE team_id=? ORDER BY id", (team_id,))]
        return team

    @staticmethod
    def _member_out(row):
        member = dict(row)
        member.pop("notes", None)  # columna heredada de la v1; las notas son privadas
        return member

    def get_challenge(self, challenge_id):
        with self._conn() as conn:
            challenge = _row(conn.execute("SELECT * FROM challenges WHERE id=?",
                                          (challenge_id,)).fetchone())
            if challenge is None:
                raise NotFound("No existe el reto %s." % challenge_id)
            challenge["teams"] = [dict(r) for r in conn.execute(
                "SELECT id, name, table_label, phase, attention, last_visit_at FROM teams "
                "WHERE challenge_id=? ORDER BY name", (challenge_id,))]
            return challenge

    # --------------------------------------------------------------- equipos

    def create_team(self, data, actor=""):
        fields = self._team_fields(data, partial=False)
        members = self._member_list(data.get("members"))
        now = now_iso()
        with self._write() as conn:
            self._check_challenge(conn, fields["challenge_id"])
            fields["updated_by"] = actor or ""
            cols = list(fields) + ["created_at", "updated_at"]
            vals = list(fields.values()) + [now, now]
            cur = conn.execute("INSERT INTO teams(%s) VALUES(%s)" %
                               (",".join(cols), ",".join("?" * len(cols))), vals)
            team_id = cur.lastrowid
            for member in members:
                self._insert_member(conn, team_id, member, now)
            return self._team_detail(conn, team_id)

    def update_team(self, team_id, data, actor=""):
        fields = self._team_fields(data, partial=True)
        with self._write() as conn:
            self._require(conn, "teams", team_id, "equipo")
            if "challenge_id" in fields:
                self._check_challenge(conn, fields["challenge_id"])
            fields["updated_at"] = now_iso()
            fields["updated_by"] = actor or ""
            sets = ", ".join("%s=?" % col for col in fields)
            conn.execute("UPDATE teams SET %s WHERE id=?" % sets,
                         list(fields.values()) + [team_id])
            return self._team_detail(conn, team_id)

    def mark_visit(self, team_id, actor=""):
        """Registra que un mentor ha pasado por el equipo (dato compartido)."""
        now = now_iso()
        with self._write() as conn:
            self._require(conn, "teams", team_id, "equipo")
            conn.execute("UPDATE teams SET last_visit_at=?, last_visit_by=? WHERE id=?",
                         (now, actor or "", team_id))
            return self._team_detail(conn, team_id)

    def delete_team(self, team_id):
        with self._write() as conn:
            self._require(conn, "teams", team_id, "equipo")
            conn.execute("DELETE FROM teams WHERE id=?", (team_id,))

    def _touch(self, conn, team_id, actor):
        conn.execute("UPDATE teams SET updated_at=?, updated_by=? WHERE id=?",
                     (now_iso(), actor or "", team_id))

    @staticmethod
    def _team_fields(data, partial):
        """Valida y normaliza los campos de equipo. En parcial solo los presentes."""
        fields = {}

        def wanted(key):
            return (not partial) or key in data

        for key in TEAM_TEXT_FIELDS:
            if wanted(key):
                fields[key] = _text(data, key)
        if "name" in fields and not fields["name"]:
            raise ValidationError("El nombre del equipo es obligatorio.")
        if wanted("phase"):
            fields["phase"] = _choice(data, "phase", _keys(PHASES), "idea", "Fase")
        if wanted("challenge_id"):
            fields["challenge_id"] = Store._challenge_id(data.get("challenge_id"))
        if wanted("attention"):
            fields["attention"] = _flag(data, "attention")
        return fields

    @staticmethod
    def _challenge_id(value):
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError("El reto debe indicarse con su identificador numérico.")
        return value

    @staticmethod
    def _check_challenge(conn, challenge_id):
        if challenge_id is None:
            return
        found = conn.execute("SELECT 1 AS x FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        if not found:
            raise ValidationError("El reto %s no existe." % challenge_id)

    @staticmethod
    def _require(conn, table, row_id, label):
        found = conn.execute("SELECT 1 AS x FROM %s WHERE id=?" % table, (row_id,)).fetchone()
        if not found:
            raise NotFound("No existe el %s %s." % (label, row_id))

    # -------------------------------------------------------------- miembros

    @staticmethod
    def _member_fields(data, partial):
        fields = {}
        if (not partial) or "name" in data:
            fields["name"] = _text(data, "name")
            if not fields["name"]:
                raise ValidationError("El nombre del miembro es obligatorio.")
        if (not partial) or "role" in data:
            fields["role"] = _choice(data, "role", _keys(ROLES), "otro", "Rol")
        if (not partial) or "skills" in data:
            fields["skills"] = _text(data, "skills")
        return fields

    def _member_list(self, raw):
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ValidationError("'members' debe ser una lista.")
        members = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValidationError("Cada miembro debe ser un objeto.")
            members.append(self._member_fields(item, partial=False))
        return members

    @staticmethod
    def _insert_member(conn, team_id, fields, now):
        cur = conn.execute(
            "INSERT INTO members(team_id,name,role,skills,created_at) VALUES(?,?,?,?,?)",
            (team_id, fields["name"], fields["role"], fields["skills"], now))
        return cur.lastrowid

    def _get_member(self, conn, member_id):
        return self._member_out(conn.execute("SELECT * FROM members WHERE id=?",
                                             (member_id,)).fetchone())

    def create_member(self, team_id, data, actor=""):
        fields = self._member_fields(data, partial=False)
        now = now_iso()
        with self._write() as conn:
            self._require(conn, "teams", team_id, "equipo")
            member_id = self._insert_member(conn, team_id, fields, now)
            self._touch(conn, team_id, actor)
            return self._get_member(conn, member_id)

    def update_member(self, member_id, data, actor=""):
        fields = self._member_fields(data, partial=True)
        with self._write() as conn:
            current = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
            if current is None:
                raise NotFound("No existe el miembro %s." % member_id)
            if fields:
                sets = ", ".join("%s=?" % col for col in fields)
                conn.execute("UPDATE members SET %s WHERE id=?" % sets,
                             list(fields.values()) + [member_id])
                self._touch(conn, current["team_id"], actor)
            return self._get_member(conn, member_id)

    def delete_member(self, member_id, actor=""):
        with self._write() as conn:
            current = conn.execute("SELECT team_id FROM members WHERE id=?",
                                   (member_id,)).fetchone()
            if current is None:
                raise NotFound("No existe el miembro %s." % member_id)
            conn.execute("DELETE FROM members WHERE id=?", (member_id,))
            self._touch(conn, current["team_id"], actor)

    # -------------------------------------------------------------- búsqueda

    def search(self, query, limit=20):
        query = (query or "").strip()
        if not query:
            return {"teams": [], "members": []}
        pattern = _like_pattern(query)
        with self._conn() as conn:
            return {
                "teams": self._search_table(
                    conn, "SELECT * FROM teams WHERE {where} ORDER BY updated_at DESC, id DESC",
                    ("name", "table_label", "idea", "problem", "solution", "links"),
                    pattern, limit),
                "members": [self._member_out(r) for r in self._search_table(
                    conn, "SELECT m.*, t.name AS team_name FROM members m "
                          "JOIN teams t ON t.id=m.team_id WHERE {where} ORDER BY m.id",
                    ("m.name", "m.role", "m.skills"), pattern, limit)],
            }

    @staticmethod
    def _search_table(conn, sql, columns, pattern, limit):
        where = " OR ".join("fold(%s) LIKE ? ESCAPE '\\'" % col for col in columns)
        rows = conn.execute(sql.format(where=where) + " LIMIT ?",
                            [pattern] * len(columns) + [limit]).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------- exportar / importar

    def export_all(self):
        with self._conn() as conn:
            return {
                "version": EXPORT_VERSION,
                "exported_at": now_iso(),
                "teams": [dict(r) for r in conn.execute("SELECT * FROM teams ORDER BY id")],
                "members": [self._member_out(r) for r in conn.execute(
                    "SELECT * FROM members ORDER BY id")],
                "team_methods": [dict(r) for r in conn.execute(
                    "SELECT * FROM team_methods ORDER BY team_id, method_id")],
            }

    def import_all(self, data):
        teams, members, links = self._validate_import(data)
        with self._write() as conn:
            for table in ("members", "team_methods", "teams"):
                conn.execute("DELETE FROM %s" % table)
            self._insert_rows(conn, "teams", TEAM_COLUMNS, teams)
            self._insert_rows(conn, "members", MEMBER_COLUMNS, members)
            for link in links:
                if conn.execute("SELECT 1 AS x FROM methods WHERE id=?",
                                (link["method_id"],)).fetchone():
                    conn.execute("DELETE FROM team_methods WHERE team_id=? AND method_id=?",
                                 (link["team_id"], link["method_id"]))
                    conn.execute("INSERT INTO team_methods(team_id,method_id,status) "
                                 "VALUES(?,?,?)",
                                 (link["team_id"], link["method_id"], link["status"]))
            conn.execute("UPDATE teams SET challenge_id=NULL WHERE challenge_id IS NOT NULL AND "
                         "challenge_id NOT IN (SELECT id FROM challenges)")
            if self.is_pg:
                for table in ("teams", "members"):
                    # Nunca retrocede: un id ya usado no se reasigna (las notas privadas
                    # de los navegadores van por id de equipo/miembro).
                    conn.execute(
                        "SELECT setval(pg_get_serial_sequence('{t}','id'), GREATEST("
                        "COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, "
                        "nextval(pg_get_serial_sequence('{t}','id'))), false) AS v".format(t=table))
        return len(teams)

    @staticmethod
    def _insert_rows(conn, table, columns, rows):
        sql = "INSERT INTO %s(%s) VALUES(%s)" % (
            table, ",".join(columns), ",".join("?" * len(columns)))
        for row in rows:
            conn.execute(sql, [row.get(col) for col in columns])

    def _validate_import(self, data):
        if not isinstance(data, dict) or data.get("version") not in IMPORT_VERSIONS:
            raise ValidationError("El fichero no es una exportación válida de Space Apps.")
        lists = {}
        for key in ("teams", "members"):
            lists[key] = data.get(key)
            if not isinstance(lists[key], list) or not all(isinstance(r, dict) for r in lists[key]):
                raise ValidationError("La exportación no contiene una lista válida de '%s'." % key)
        raw_links = data.get("team_methods") or []
        if not isinstance(raw_links, list) or not all(isinstance(r, dict) for r in raw_links):
            raise ValidationError("La exportación no contiene una lista válida de 'team_methods'.")
        now = now_iso()
        teams = [self._import_team(row, now) for row in lists["teams"]]
        team_ids = set(t["id"] for t in teams)
        if len(team_ids) != len(teams):
            raise ValidationError("Hay equipos con identificador repetido.")
        members = [self._import_child(row, team_ids, "miembro", now) for row in lists["members"]]
        for member in members:
            member.update(self._member_fields(member, partial=False))
        links = [dict(r, status=r.get("status") or "pendiente") for r in raw_links
                 if r.get("team_id") in team_ids and isinstance(r.get("method_id"), int)]
        return teams, members, links

    def _import_team(self, row, now):
        if not isinstance(row.get("id"), int):
            raise ValidationError("Hay un equipo sin identificador numérico.")
        team = dict(row)
        team.update(self._team_fields(row, partial=False))
        team["id"] = row["id"]
        team["created_at"] = row.get("created_at") or now
        team["updated_at"] = row.get("updated_at") or team["created_at"]
        team["last_visit_at"] = row.get("last_visit_at")
        team["updated_by"] = row.get("updated_by") or ""
        team["last_visit_by"] = row.get("last_visit_by") or ""
        team["nasa_slug"] = row.get("nasa_slug") or ""
        return team

    @staticmethod
    def _import_child(row, team_ids, label, now):
        if not isinstance(row.get("id"), int):
            raise ValidationError("Hay un %s sin identificador numérico." % label)
        if row.get("team_id") not in team_ids:
            raise ValidationError("Hay un %s que apunta a un equipo inexistente." % label)
        child = dict(row)
        child["created_at"] = row.get("created_at") or now
        return child
