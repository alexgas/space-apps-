"""Servidor de Space Apps Mentor: API JSON + estáticos de dist/.

Dos modos:
- Local (por defecto): 127.0.0.1, SQLite, sin login. Solo librería estándar.
- Compartido (Render): Postgres vía DATABASE_URL y contraseña común de mentores
  vía MENTOR_PASSWORD. Ver README.

Variables de entorno: PORT, DATABASE_URL, MENTOR_PASSWORD, SECRET_KEY, ALLOWED_HOSTS.
"""
import argparse
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import logging
import mimetypes
import os
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import nasa_sync
from store import NotFound, Store, StoreError, ValidationError

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, "dist")
MAX_BODY = 5 * 1024 * 1024
HOST_RE = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\])(:(?P<port>\d+))?$", re.IGNORECASE)
MUTATING = ("POST", "PATCH", "DELETE")
JSON_TYPE = "application/json; charset=utf-8"
COOKIE = "sam_session"
SESSION_DAYS = 7
MAX_FAILS = 10           # intentos fallidos de login por IP...
FAIL_WINDOW = 10 * 60    # ...en esta ventana (segundos)
PUBLIC_API = ("/api/me", "/api/login", "/api/logout")

log = logging.getLogger("spaceapps.server")


class ApiResult(object):
    def __init__(self, status=200, payload=None, headers=None):
        self.status = status
        self.payload = payload
        self.headers = headers or {}


# ------------------------------------------------------------------ rutas API

def _id(match):
    return int(match.group("id"))


def _export_response(store):
    from datetime import datetime
    name = "spaceapps-equipos-%s.json" % datetime.now().strftime("%Y%m%d-%H%M")
    return ApiResult(200, store.export_all(),
                     {"Content-Disposition": 'attachment; filename="%s"' % name})


def _import_response(store, body):
    return ApiResult(200, {"ok": True, "teams": store.import_all(body)})


def _delete(fn, match, store):
    getattr(store, fn)(_id(match))
    return ApiResult(200, {"ok": True})


# (método, regex, función(store, match, query, body, actor) -> ApiResult)
ROUTES = [
    ("GET", r"/api/state",
     lambda s, m, q, b, a: ApiResult(200, s.state())),
    ("POST", r"/api/teams",
     lambda s, m, q, b, a: ApiResult(201, s.create_team(b, actor=a))),
    ("GET", r"/api/teams/(?P<id>\d+)",
     lambda s, m, q, b, a: ApiResult(200, s.get_team(_id(m)))),
    ("PATCH", r"/api/teams/(?P<id>\d+)",
     lambda s, m, q, b, a: ApiResult(200, s.update_team(_id(m), b, actor=a))),
    ("DELETE", r"/api/teams/(?P<id>\d+)",
     lambda s, m, q, b, a: _delete("delete_team", m, s)),
    ("POST", r"/api/teams/(?P<id>\d+)/visit",
     lambda s, m, q, b, a: ApiResult(200, s.mark_visit(_id(m), actor=a))),
    ("POST", r"/api/teams/(?P<id>\d+)/members",
     lambda s, m, q, b, a: ApiResult(201, s.create_member(_id(m), b, actor=a))),
    ("PATCH", r"/api/members/(?P<id>\d+)",
     lambda s, m, q, b, a: ApiResult(200, s.update_member(_id(m), b, actor=a))),
    ("DELETE", r"/api/members/(?P<id>\d+)",
     lambda s, m, q, b, a: ApiResult(200, (s.delete_member(_id(m), actor=a), {"ok": True})[1])),
    ("GET", r"/api/challenges/(?P<id>\d+)",
     lambda s, m, q, b, a: ApiResult(200, s.get_challenge(_id(m)))),
    ("GET", r"/api/search",
     lambda s, m, q, b, a: ApiResult(200, s.search((q.get("q") or [""])[0]))),
    ("GET", r"/api/export",
     lambda s, m, q, b, a: _export_response(s)),
    ("POST", r"/api/import",
     lambda s, m, q, b, a: _import_response(s, b)),
    ("POST", r"/api/nasa-sync/preview",
     lambda s, m, q, b, a: ApiResult(200, nasa_sync.preview(s, b))),
    ("POST", r"/api/nasa-sync/apply",
     lambda s, m, q, b, a: ApiResult(200, nasa_sync.apply(s, b, actor=a))),
]
COMPILED_ROUTES = [(method, re.compile(pattern + r"$"), fn) for method, pattern, fn in ROUTES]


def dispatch(store, method, path, query, body, actor=""):
    """Resuelve una petición API. Devuelve ApiResult o None si la ruta no existe."""
    allowed = []
    for route_method, regex, fn in COMPILED_ROUTES:
        match = regex.match(path)
        if not match:
            continue
        if route_method == method:
            return fn(store, match, query, body, actor)
        allowed.append(route_method)
    if allowed:
        return ApiResult(405, {"error": "Método no permitido."},
                         {"Allow": ", ".join(sorted(set(allowed)))})
    return None


# ---------------------------------------------------------------- sesiones

class Auth(object):
    """Contraseña común de mentores + cookie firmada con el nombre del mentor.

    Si no hay contraseña configurada (modo local), todo está abierto.
    """

    def __init__(self, password=None, secret=None):
        self.password = password or None
        self.secret = (secret or secrets.token_hex(32)).encode("utf-8")
        self._fails = {}
        self._lock = threading.Lock()

    @property
    def required(self):
        return self.password is not None

    def check_password(self, given):
        return hmac.compare_digest((given or "").encode("utf-8"), self.password.encode("utf-8"))

    def make_token(self, name, now=None):
        expires = int((now or time.time()) + SESSION_DAYS * 86400)
        payload = base64.urlsafe_b64encode(
            json.dumps({"n": name, "e": expires}).encode("utf-8")).decode("ascii").rstrip("=")
        return payload + "." + self._sign(payload)

    def read_token(self, token, now=None):
        """Nombre del mentor si el token es válido y no ha caducado; si no, None."""
        if not token or "." not in token:
            return None
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload)):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict) or data.get("e", 0) < (now or time.time()):
            return None
        name = data.get("n")
        return name if isinstance(name, str) and name else None

    def _sign(self, payload):
        return hmac.new(self.secret, payload.encode("ascii"), hashlib.sha256).hexdigest()

    # -- límite de intentos

    def blocked(self, ip, now=None):
        now = now or time.time()
        with self._lock:
            recent = [t for t in self._fails.get(ip, []) if now - t < FAIL_WINDOW]
            self._fails[ip] = recent
            return len(recent) >= MAX_FAILS

    def record_fail(self, ip, now=None):
        with self._lock:
            self._fails.setdefault(ip, []).append(now or time.time())

    def clear_fails(self, ip):
        with self._lock:
            self._fails.pop(ip, None)


def parse_cookies(header):
    cookies = {}
    for part in (header or "").split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def clean_name(value):
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:40]


# ------------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    server_version = "SpaceAppsMentor/1.0"

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    # -- verbos

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_PUT(self):
        self._handle("PUT")

    # -- flujo principal

    def _handle(self, method):
        try:
            if urlparse(self.path).path == "/healthz":
                return self._send_json(200, {"ok": True})
            if not self._host_allowed():
                return self._send_json(403, {"error": "Host no permitido."})
            if method in MUTATING and not self._origin_allowed():
                return self._send_json(403, {"error": "Origen no permitido."})
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/"):
                return self._handle_api(method, path, parse_qs(parsed.query))
            if method != "GET":
                return self._send_json(405, {"error": "Método no permitido."})
            self._serve_static(path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log.exception("Error interno procesando %s %s", method, self.path)
            self._send_json(500, {"error": "Error interno del servidor."})

    def _handle_api(self, method, path, query):
        body = self._read_json() if method in MUTATING else None
        if body is _INVALID:
            return
        auth = self.server.auth
        actor = self._session_name()
        if path in PUBLIC_API:
            return self._handle_session(method, path, body, actor)
        if auth.required and actor is None:
            return self._send_json(401, {"error": "Sesión caducada. Vuelve a entrar.",
                                         "login": True})
        try:
            result = dispatch(self.server.store, method, path, query, body, actor or "")
        except ValidationError as exc:
            return self._send_json(getattr(exc, "status", 400), {"error": str(exc)})
        except NotFound as exc:
            return self._send_json(404, {"error": str(exc)})
        except StoreError as exc:
            return self._send_json(400, {"error": str(exc)})
        if result is None:
            return self._send_json(404, {"error": "Ruta no encontrada."})
        self._send_json(result.status, result.payload, result.headers)

    # -- sesión

    def _session_name(self):
        """Nombre del mentor de la cookie (None si no hay sesión válida).

        En modo local sin contraseña devuelve '' (sesión abierta, sin nombre).
        """
        token = parse_cookies(self.headers.get("Cookie")).get(COOKIE)
        name = self.server.auth.read_token(token)
        if name is None and not self.server.auth.required:
            return ""
        return name

    def _client_ip(self):
        forwarded = self.headers.get("X-Forwarded-For", "")
        return forwarded.split(",")[0].strip() or self.client_address[0]

    def _cookie(self, value, max_age):
        secure = self.headers.get("X-Forwarded-Proto", "") == "https"
        return "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (
            COOKIE, value, max_age, "; Secure" if secure else "")

    def _handle_session(self, method, path, body, actor):
        auth = self.server.auth
        if path == "/api/me" and method == "GET":
            return self._send_json(200, {"auth_required": auth.required,
                                         "logged_in": actor is not None,
                                         "name": actor or ""})
        if path == "/api/logout" and method == "POST":
            return self._send_json(200, {"ok": True},
                                   {"Set-Cookie": self._cookie("", 0)})
        if path == "/api/login" and method == "POST":
            ip = self._client_ip()
            name = clean_name(body.get("name"))
            if not name:
                return self._send_json(400, {"error": "Escribe tu nombre."})
            if auth.required:
                if auth.blocked(ip):
                    return self._send_json(429, {"error": "Demasiados intentos. Espera unos minutos."})
                if not auth.check_password(body.get("password")):
                    auth.record_fail(ip)
                    return self._send_json(401, {"error": "Contraseña incorrecta."})
                auth.clear_fails(ip)
            token = auth.make_token(name)
            return self._send_json(200, {"ok": True, "name": name},
                                   {"Set-Cookie": self._cookie(token, SESSION_DAYS * 86400)})
        return self._send_json(405, {"error": "Método no permitido."})

    # -- seguridad

    def _host_allowed(self):
        host = self.headers.get("Host", "")
        allowed = self.server.allowed_hosts
        if allowed:
            bare = host.rsplit(":", 1)[0].lower() if not host.startswith("[") else host
            for item in allowed:
                if item == "*" or bare == item or (item.startswith(".") and bare.endswith(item)):
                    return True
        match = HOST_RE.match(host)
        if not match:
            return False
        port = match.group("port")
        return port is None or port == str(self.server.server_port)

    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return urlparse(origin).netloc == self.headers.get("Host", "")

    # -- cuerpo

    def _read_json(self):
        """Devuelve el cuerpo JSON (dict) o _INVALID tras responder el error."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self._send_json(400, {"error": "Content-Length no válido."})
            return _INVALID
        if length > MAX_BODY:
            self.close_connection = True
            self._send_json(413, {"error": "El cuerpo supera el máximo de 5 MB."})
            return _INVALID
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "El cuerpo no es JSON válido."})
            return _INVALID
        if not isinstance(data, dict):
            self._send_json(400, {"error": "El cuerpo debe ser un objeto JSON."})
            return _INVALID
        return data

    # -- respuestas

    def _send_json(self, status, payload, headers=None):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, raw, JSON_TYPE, headers)

    def _send(self, status, raw, content_type, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    # -- estáticos

    def _serve_static(self, url_path):
        target = resolve_static(unquote(url_path))
        if target is None:
            return self._send_json(404, {"error": "No encontrado."})
        with open(target, "rb") as fh:
            raw = fh.read()
        self._send(200, raw, content_type_for(target))


_INVALID = object()


def resolve_static(url_path, dist_dir=DIST_DIR):
    """Ruta absoluta del fichero estático pedido, o None (sin path traversal)."""
    relative = url_path.lstrip("/") or "index.html"
    if "\x00" in relative:
        return None
    root = os.path.realpath(dist_dir)
    candidate = os.path.realpath(os.path.join(root, relative))
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate if os.path.isfile(candidate) else None


def content_type_for(path):
    guessed, _ = mimetypes.guess_type(path)
    guessed = guessed or "application/octet-stream"
    if guessed.startswith("text/") or guessed in ("application/javascript", "application/json"):
        return guessed + "; charset=utf-8"
    return guessed


# ------------------------------------------------------------------- arranque

def create_server(host, port, data_dir=None, seed_path=None, backup=True,
                  database_url=None, password=None, secret=None, allowed_hosts=None):
    """Crea el servidor sin arrancarlo (los tests usan port=0)."""
    store = Store(data_dir, seed_path=seed_path, backup=backup, database_url=database_url)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.store = store
    httpd.auth = Auth(password, secret)
    httpd.allowed_hosts = [h.strip().lower() for h in (allowed_hosts or []) if h.strip()]
    return httpd


def parse_args(argv=None):
    env_port = os.environ.get("PORT")
    parser = argparse.ArgumentParser(description="Space Apps Mentor")
    parser.add_argument("--host", default="0.0.0.0" if env_port else "127.0.0.1")
    parser.add_argument("--port", type=int, default=int(env_port or 8766))
    parser.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    parser.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    return parser.parse_args(argv)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    database_url = os.environ.get("DATABASE_URL") or None
    password = os.environ.get("MENTOR_PASSWORD") or None
    secret = os.environ.get("SECRET_KEY") or None
    allowed = (os.environ.get("ALLOWED_HOSTS") or "").split(",")
    cloud = bool(os.environ.get("PORT"))
    if args.host not in ("127.0.0.1", "localhost") and not password:
        print("AVISO: escuchando en %s sin MENTOR_PASSWORD: cualquiera con la URL puede entrar."
              % args.host, file=sys.stderr)
    if password and not secret:
        print("AVISO: sin SECRET_KEY las sesiones se pierden en cada reinicio.", file=sys.stderr)
    try:
        httpd = create_server(args.host, args.port, args.data_dir, database_url=database_url,
                              password=password, secret=secret, allowed_hosts=allowed,
                              backup=not database_url)
    except OSError as exc:
        print("No se pudo abrir %s:%s (%s). ¿Ya está arrancado?" % (args.host, args.port, exc),
              file=sys.stderr)
        return 1
    url = "http://%s:%s/" % ("127.0.0.1" if args.host in ("0.0.0.0", "") else args.host, args.port)
    print("Space Apps Mentor en %s  [%s, %s]  (Ctrl+C para parar)" % (
        url, "Postgres" if database_url else "SQLite",
        "con contraseña" if password else "sin login"))
    if not args.no_browser and not cloud:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nHasta pronto.")
    finally:
        httpd.server_close()
        httpd.store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
