import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import server
from test_store import write_seed


class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        seed = write_seed(cls.tmp)
        cls.httpd = server.create_server("127.0.0.1", 0, os.path.join(cls.tmp, "data"),
                                         seed_path=seed, backup=False)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(5)
        shutil.rmtree(cls.tmp, True)

    def call(self, method, path, body=None, headers=None):
        """Devuelve (status, cabeceras, json|bytes)."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data,
                                     method=method, headers=headers or {})
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            resp = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as err:
            resp = err
        raw = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        payload = json.loads(raw.decode("utf-8")) if "json" in ctype else raw
        return resp.code, resp.headers, payload

    def new_team(self, **fields):
        fields.setdefault("name", "Equipo")
        status, _, team = self.call("POST", "/api/teams", fields)
        self.assertEqual(status, 201)
        return team


class TestApi(ServerTestCase):
    def test_create_team_with_members(self):
        team = self.new_team(name="Cosmos", challenge_id=1,
                             members=[{"name": "Ana", "role": "dev"}, {"name": "Luis"}])
        self.assertEqual(len(team["members"]), 2)
        status, _, detail = self.call("GET", "/api/teams/%d" % team["id"])
        self.assertEqual(status, 200)
        self.assertEqual(detail["challenge"]["slug"], "reto-uno")
        self.assertNotIn("notes", detail)

    def test_patch_phase_validation(self):
        team = self.new_team()
        status, _, body = self.call("PATCH", "/api/teams/%d" % team["id"], {"phase": "demo"})
        self.assertEqual((status, body["phase"]), (200, "demo"))
        status, _, body = self.call("PATCH", "/api/teams/%d" % team["id"], {"phase": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_missing_name_is_400(self):
        status, _, body = self.call("POST", "/api/teams", {"name": ""})
        self.assertEqual(status, 400)
        self.assertIn("obligatorio", body["error"])

    def test_invalid_json_is_400(self):
        req = urllib.request.Request("http://127.0.0.1:%d/api/teams" % self.port,
                                     data=b"{no json", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    def test_visit_endpoint_and_no_notes_api(self):
        team = self.new_team()
        self.assertIsNone(team["last_visit_at"])
        status, _, body = self.call("POST", "/api/teams/%d/visit" % team["id"], {})
        self.assertEqual(status, 200)
        self.assertTrue(body["last_visit_at"])
        self.assertEqual(self.call("POST", "/api/teams/%d/visit" % 9999, {})[0], 404)
        self.assertEqual(self.call("POST", "/api/teams/%d/notes" % team["id"], {"body": "x"})[0], 404)

    def test_member_endpoints(self):
        team = self.new_team()
        status, _, member = self.call("POST", "/api/teams/%d/members" % team["id"],
                                      {"name": "Eva", "role": "ciencia"})
        self.assertEqual(status, 201)
        status, _, member = self.call("PATCH", "/api/members/%d" % member["id"], {"role": "dev"})
        self.assertEqual(member["role"], "dev")
        status, _, body = self.call("DELETE", "/api/members/%d" % member["id"])
        self.assertEqual(body, {"ok": True})

    def test_delete_cascade(self):
        team = self.new_team(members=[{"name": "Ana"}])
        status, _, body = self.call("DELETE", "/api/teams/%d" % team["id"])
        self.assertEqual((status, body), (200, {"ok": True}))
        self.assertEqual(self.call("GET", "/api/teams/%d" % team["id"])[0], 404)
        _, _, hits = self.call("GET", "/api/search?q=Ana")
        self.assertFalse([m for m in hits["members"] if m["team_id"] == team["id"]])

    def test_state_shape_and_challenge_team_count(self):
        before = self.call("GET", "/api/state")[2]
        count = [c for c in before["challenges"] if c["id"] == 2][0]["team_count"]
        self.new_team(challenge_id=2, members=[{"name": "Z"}])
        status, headers, state = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(set(state), {"phases", "roles", "note_kinds", "challenges", "teams",
                                      "methods"})
        after = [c for c in state["challenges"] if c["id"] == 2][0]["team_count"]
        self.assertEqual(after, count + 1)
        team = [t for t in state["teams"] if t["challenge_id"] == 2][-1]
        for key in ("member_count", "challenge_title", "challenge_num", "updated_by"):
            self.assertIn(key, team)

    def test_search(self):
        self.new_team(name="Buscable Único", idea="telescopio casero")
        _, _, result = self.call("GET", "/api/search?q=TELESCOPIO")
        self.assertEqual(set(result), {"teams", "members"})
        self.assertTrue(result["teams"])
        _, _, result = self.call("GET", "/api/search?q=")
        self.assertEqual(result["teams"], [])

    def test_challenge_detail(self):
        team = self.new_team(challenge_id=1)
        status, _, challenge = self.call("GET", "/api/challenges/1")
        self.assertEqual(status, 200)
        self.assertIn(team["id"], [t["id"] for t in challenge["teams"]])
        self.assertEqual(self.call("GET", "/api/challenges/999")[0], 404)

    def test_export_import_roundtrip(self):
        team = self.new_team(name="Roundtrip", members=[{"name": "Rita"}])
        status, headers, dump = self.call("GET", "/api/export")
        self.assertEqual(status, 200)
        self.assertIn('attachment; filename="spaceapps-', headers["Content-Disposition"])
        self.new_team(name="Extra que desaparece")
        status, _, result = self.call("POST", "/api/import", dump)
        self.assertEqual(status, 200)
        self.assertEqual(result["teams"], len(dump["teams"]))
        names = [t["name"] for t in self.call("GET", "/api/state")[2]["teams"]]
        self.assertIn("Roundtrip", names)
        self.assertNotIn("Extra que desaparece", names)
        self.assertEqual(self.call("GET", "/api/teams/%d" % team["id"])[2]["members"][0]["name"],
                         "Rita")

    def test_import_invalid_is_400(self):
        status, _, body = self.call("POST", "/api/import", {"foo": 1})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_unknown_route_404_json(self):
        status, headers, body = self.call("GET", "/api/nada")
        self.assertEqual(status, 404)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertIn("error", body)

    def test_method_not_allowed(self):
        status, headers, body = self.call("DELETE", "/api/state")
        self.assertEqual(status, 405)
        self.assertIn("GET", headers["Allow"])
        self.assertIn("error", body)


class TestNasaSyncApi(ServerTestCase):
    def test_preview_then_apply_with_stale_check(self):
        data = {"teams": [{"slug": "cosmos", "name": "Cosmos", "challenge_en": "Challenge one",
                           "members": [{"name": "Ana", "owner": True}]}]}
        self.new_team(name="Manual que sobra")
        status, _, plan = self.call("POST", "/api/nasa-sync/preview", data)
        self.assertEqual(status, 200)
        self.assertEqual([c["name"] for c in plan["created"]], ["Cosmos"])
        self.assertEqual([d["name"] for d in plan["deleted"]], ["Manual que sobra"])
        status, _, body = self.call("POST", "/api/nasa-sync/apply", data)
        self.assertEqual(status, 400)  # sin revisar antes
        status, _, body = self.call("POST", "/api/nasa-sync/apply",
                                    dict(data, plan_hash="otro-plan"))
        self.assertEqual(status, 409)
        status, _, res = self.call("POST", "/api/nasa-sync/apply",
                                   dict(data, plan_hash=plan["plan_hash"]))
        self.assertEqual(status, 200)
        self.assertEqual((res["created"], res["deleted"]), (1, 1))
        teams = self.call("GET", "/api/state")[2]["teams"]
        self.assertEqual([(t["name"], t["nasa_slug"], t["challenge_id"]) for t in teams],
                         [("Cosmos", "cosmos", 1)])


class TestSecurityAndStatic(ServerTestCase):
    def raw(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def test_bad_host_rejected(self):
        status, body = self.raw("GET", "/api/state", {"Host": "evil.example.com"})
        self.assertEqual(status, 403)
        self.assertIn("error", json.loads(body.decode("utf-8")))

    def test_wrong_port_in_host_rejected(self):
        status, _ = self.raw("GET", "/api/state", {"Host": "localhost:1"})
        self.assertEqual(status, 403)

    def test_localhost_host_accepted(self):
        status, _ = self.raw("GET", "/api/state", {"Host": "localhost:%d" % self.port})
        self.assertEqual(status, 200)

    def test_foreign_origin_rejected_on_mutation(self):
        headers = {"Origin": "http://evil.example.com", "Content-Type": "application/json"}
        status, _ = self.raw("POST", "/api/teams", headers, b'{"name": "X"}')
        self.assertEqual(status, 403)

    def test_same_origin_accepted_on_mutation(self):
        headers = {"Origin": "http://127.0.0.1:%d" % self.port, "Content-Type": "application/json"}
        status, _ = self.raw("POST", "/api/teams", headers, b'{"name": "Mismo origen"}')
        self.assertEqual(status, 201)

    def test_body_too_large(self):
        headers = {"Content-Length": str(server.MAX_BODY + 1), "Content-Type": "application/json"}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", "/api/import")
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.endheaders()
            self.assertEqual(conn.getresponse().status, 413)
        finally:
            conn.close()

    def test_traversal_blocked(self):
        for path in ("/../server.py", "/%2e%2e/server.py", "/..%2fstore.py"):
            status, body = self.raw("GET", path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"ThreadingHTTPServer", body)

    def test_resolve_static_traversal_unit(self):
        dist = os.path.join(self.tmp, "dist")
        os.makedirs(dist)
        with open(os.path.join(dist, "index.html"), "w") as fh:
            fh.write("ok")
        with open(os.path.join(self.tmp, "secreto.txt"), "w") as fh:
            fh.write("secreto")
        self.assertIsNotNone(server.resolve_static("/", dist))
        self.assertIsNone(server.resolve_static("/../secreto.txt", dist))
        self.assertIsNone(server.resolve_static("/nada.js", dist))

    def test_static_index_served(self):
        dist_index = os.path.join(server.DIST_DIR, "index.html")
        created = not os.path.exists(dist_index)
        if created:
            os.makedirs(server.DIST_DIR, exist_ok=True)
            with open(dist_index, "w", encoding="utf-8") as fh:
                fh.write("<!doctype html><title>test</title>")
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.getheader("Content-Type"))
            self.assertEqual(resp.getheader("Cache-Control"), "no-store")
            self.assertIn(b"<!doctype html>", body.lower())
            conn.close()
        finally:
            if created:
                os.remove(dist_index)

    def test_static_missing_is_json_404(self):
        status, body = self.raw("GET", "/no-existe.js")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body.decode("utf-8")))


class AuthServerTestCase(ServerTestCase):
    """Servidor en modo compartido: contraseña común + hosts permitidos."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        seed = write_seed(cls.tmp)
        cls.httpd = server.create_server(
            "127.0.0.1", 0, os.path.join(cls.tmp, "data"), seed_path=seed, backup=False,
            password="cohete", secret="s3cret",
            allowed_hosts=["mentores.spaceappsvalencia.es", ".onrender.com"])
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    def login(self, name="Marta", password="cohete"):
        status, headers, body = self.call("POST", "/api/login",
                                          {"name": name, "password": password})
        cookie = headers.get("Set-Cookie", "")
        return status, body, cookie.split(";")[0]


class TestAuth(AuthServerTestCase):
    def test_api_requires_login(self):
        status, _, body = self.call("GET", "/api/state")
        self.assertEqual(status, 401)
        self.assertTrue(body["login"])

    def test_me_reports_auth_required(self):
        _, _, me = self.call("GET", "/api/me")
        self.assertEqual(me, {"auth_required": True, "logged_in": False, "name": ""})

    def test_wrong_password(self):
        status, body, cookie = self.login(name="X", password="mal")
        self.assertEqual(status, 401)
        self.assertEqual(cookie, "")

    def test_name_required(self):
        status, _, _ = self.login(name="  ")
        self.assertEqual(status, 400)

    def test_login_then_use_api_with_actor(self):
        status, body, cookie = self.login(name="  Marta   López ")
        self.assertEqual((status, body["name"]), (200, "Marta López"))
        hdr = {"Cookie": cookie}
        self.assertEqual(self.call("GET", "/api/me", headers=hdr)[2]["name"], "Marta López")
        status, _, team = self.call("POST", "/api/teams", {"name": "Con login"}, headers=hdr)
        self.assertEqual((status, team["updated_by"]), (201, "Marta López"))
        _, _, team = self.call("POST", "/api/teams/%d/visit" % team["id"], {}, headers=hdr)
        self.assertEqual(team["last_visit_by"], "Marta López")
        status, headers, _ = self.call("POST", "/api/logout", {}, headers=hdr)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])

    def test_tampered_cookie_rejected(self):
        _, _, cookie = self.login()
        bad = cookie[:-2] + ("aa" if not cookie.endswith("aa") else "bb")
        self.assertEqual(self.call("GET", "/api/state", headers={"Cookie": bad})[0], 401)

    def test_static_is_public(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/healthz", headers={"Host": "cualquiera"})
        self.assertEqual(conn.getresponse().status, 200)
        conn.close()

    def test_allowed_hosts(self):
        _, _, cookie = self.login()
        for host, expected in (("mentores.spaceappsvalencia.es", 200),
                               ("space-apps.onrender.com", 200),
                               ("evil.example.com", 403),
                               ("onrender.com.evil.io", 403)):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("GET", "/api/state", headers={"Host": host, "Cookie": cookie})
            self.assertEqual(conn.getresponse().status, expected, host)
            conn.close()

    def test_rate_limit(self):
        ip = "203.0.113.9"
        for _ in range(server.MAX_FAILS):
            self.call("POST", "/api/login", {"name": "a", "password": "x"},
                      headers={"X-Forwarded-For": ip})
        status, _, _ = self.call("POST", "/api/login", {"name": "a", "password": "cohete"},
                                 headers={"X-Forwarded-For": ip})
        self.assertEqual(status, 429)

    def test_secure_cookie_behind_https(self):
        status, headers, _ = self.call("POST", "/api/login", {"name": "a", "password": "cohete"},
                                       headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", headers["Set-Cookie"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])


class TestTokens(unittest.TestCase):
    def test_expired_token(self):
        auth = server.Auth("p", "k")
        token = auth.make_token("Ana", now=1000)
        self.assertEqual(auth.read_token(token, now=1001), "Ana")
        self.assertIsNone(auth.read_token(token, now=1000 + server.SESSION_DAYS * 86400 + 1))
        self.assertIsNone(server.Auth("p", "otra").read_token(token, now=1001))


if __name__ == "__main__":
    unittest.main()
