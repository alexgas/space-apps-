import json
import os
import shutil
import tempfile
import unittest

import store as store_module
from store import NotFound, Store, ValidationError

SEED = {
    "challenges": [
        {"num": 1, "slug": "reto-uno", "title": "Reto uno", "title_en": "Challenge one",
         "category": "Tierra", "summary": "Resumen uno", "difficulty": "Intermedio",
         "url": "https://example.org/1/"},
        {"num": 2, "slug": "reto-dos", "title": "Reto dos", "title_en": "Challenge two",
         "category": "Espacio", "summary": "Resumen dos", "difficulty": "Principiante",
         "url": "https://example.org/2/"},
    ],
    "methods": [
        {"slug": "lean-canvas", "name": "Lean Canvas", "summary": "Resumen",
         "when_to_use": "Al inicio", "steps": ["Uno", "Dos"], "key_questions": ["¿Para quién?"],
         "template": "# Canvas"},
    ],
}


def write_seed(folder, data=None):
    path = os.path.join(folder, "seed-fixture.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data or SEED, fh, ensure_ascii=False)
    return path


PG_URL = os.environ.get("TEST_DATABASE_URL")  # p.ej. postgresql://postgres@/spaceapps?host=/tmp&port=5433


def reset_pg(url):
    import psycopg
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS team_methods, members, notes, teams, methods, "
                     "challenges CASCADE")


class StoreTestCase(unittest.TestCase):
    """Por defecto SQLite. Con TEST_DATABASE_URL se repite todo contra Postgres."""
    pg = False

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.seed_path = write_seed(self.tmp)
        if self.pg:
            reset_pg(PG_URL)
        self.store = self.make_store("data")

    def make_store(self, folder, seed_path=None, backup=True):
        seed_path = seed_path or self.seed_path
        if self.pg:
            st = Store(seed_path=seed_path, database_url=PG_URL)
        else:
            st = Store(os.path.join(self.tmp, folder), seed_path=seed_path, backup=backup)
        self.addCleanup(st.close)
        return st

    def count(self, table):
        with self.store._conn() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM %s" % table).fetchone()["n"]


class TestSeedAndInit(StoreTestCase):
    def test_seed_loaded_and_idempotent(self):
        self.store.init_schema()
        self.store.seed()
        state = self.store.state()
        self.assertEqual(len(state["challenges"]), 2)
        self.assertEqual(len(state["methods"]), 1)
        self.assertEqual(state["methods"][0]["steps"], ["Uno", "Dos"])

    def test_seed_upsert_updates_by_slug(self):
        changed = json.loads(json.dumps(SEED))
        changed["challenges"][0]["title"] = "Título nuevo"
        reopened = self.make_store("data", seed_path=write_seed(self.tmp, changed), backup=False)
        titles = [c["title"] for c in reopened.state()["challenges"]]
        self.assertEqual(titles, ["Título nuevo", "Reto dos"])

    def test_missing_seed_is_tolerated(self):
        if self.pg:
            reset_pg(PG_URL)
        other = self.make_store("otra", seed_path=os.path.join(self.tmp, "nada.json"))
        self.assertEqual(other.state()["challenges"], [])

    def test_migrates_v1_sqlite_database(self):
        if self.pg:
            self.skipTest("solo SQLite")
        import sqlite3
        folder = os.path.join(self.tmp, "v1")
        os.makedirs(folder)
        conn = sqlite3.connect(os.path.join(folder, store_module.DB_NAME))
        conn.executescript(
            "CREATE TABLE teams(id INTEGER PRIMARY KEY, name TEXT NOT NULL, table_label TEXT DEFAULT '',"
            " idea TEXT DEFAULT '', problem TEXT DEFAULT '', solution TEXT DEFAULT '',"
            " phase TEXT NOT NULL DEFAULT 'idea', challenge_id INTEGER, links TEXT DEFAULT '',"
            " attention INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
            " last_visit_at TEXT);"
            "INSERT INTO teams(name, created_at, updated_at) VALUES('Viejo', 'x', 'x');")
        conn.commit()
        conn.close()
        st = Store(folder, seed_path=self.seed_path, backup=False)
        team = st.update_team(1, {"idea": "nueva"}, actor="Ale")
        self.assertEqual(team["updated_by"], "Ale")

    def test_state_shape(self):
        state = self.store.state()
        self.assertEqual(set(state), {"phases", "roles", "note_kinds", "challenges",
                                      "teams", "methods"})
        self.assertEqual([p["key"] for p in state["phases"]],
                         ["idea", "problema", "mvp", "demo", "pitch", "entregado"])
        self.assertEqual(state["phases"][0], {"key": "idea", "label": "Idea"})
        self.assertEqual([r["key"] for r in state["roles"]],
                         ["dev", "diseno", "negocio", "ciencia", "otro"])
        self.assertEqual([k["key"] for k in state["note_kinds"]], ["mentoria", "pitch", "otro"])
        self.assertIn("team_count", state["challenges"][0])

    def test_backup_keeps_last_ten(self):
        if self.pg:
            self.skipTest("solo SQLite")
        folder = os.path.join(self.tmp, "data", "backups")
        os.makedirs(folder, exist_ok=True)
        for i in range(15):
            open(os.path.join(folder, "spaceapps-20200101-0000%02d.sqlite3" % i), "w").close()
        Store(os.path.join(self.tmp, "data"), seed_path=self.seed_path)
        files = sorted(os.listdir(folder))
        self.assertEqual(len(files), 10)
        self.assertNotIn("spaceapps-20200101-000000.sqlite3", files)


class TestTeams(StoreTestCase):
    def test_create_team_with_members(self):
        team = self.store.create_team({
            "name": "Los Cosmonautas", "table_label": "Mesa 3", "challenge_id": 1,
            "members": [{"name": "Ana", "role": "dev", "skills": "python"}, {"name": "Luis"}]})
        self.assertEqual(team["name"], "Los Cosmonautas")
        self.assertEqual(team["phase"], "idea")
        self.assertEqual(team["challenge"]["slug"], "reto-uno")
        self.assertEqual([m["name"] for m in team["members"]], ["Ana", "Luis"])
        self.assertEqual(team["members"][1]["role"], "otro")
        self.assertNotIn("notes", team)
        self.assertNotIn("notes", team["members"][0])

    def test_create_requires_name(self):
        with self.assertRaises(ValidationError):
            self.store.create_team({"name": "  "})

    def test_invalid_member_role_creates_nothing(self):
        with self.assertRaises(ValidationError):
            self.store.create_team({"name": "X", "members": [{"name": "A", "role": "mago"}]})
        self.assertEqual(self.store.state()["teams"], [])

    def test_invalid_challenge(self):
        with self.assertRaises(ValidationError):
            self.store.create_team({"name": "X", "challenge_id": 999})

    def test_patch_phase_validation(self):
        team = self.store.create_team({"name": "X"})
        updated = self.store.update_team(team["id"], {"phase": "mvp", "attention": True})
        self.assertEqual(updated["phase"], "mvp")
        self.assertEqual(updated["attention"], 1)
        with self.assertRaises(ValidationError):
            self.store.update_team(team["id"], {"phase": "inexistente"})
        self.assertEqual(self.store.get_team(team["id"])["phase"], "mvp")

    def test_patch_is_partial(self):
        team = self.store.create_team({"name": "X", "idea": "Una idea"})
        updated = self.store.update_team(team["id"], {"problem": "Un problema"})
        self.assertEqual(updated["idea"], "Una idea")
        self.assertEqual(updated["problem"], "Un problema")

    def test_get_missing_team(self):
        with self.assertRaises(NotFound):
            self.store.get_team(42)

    def test_state_team_summary(self):
        team = self.store.create_team({"name": "X", "challenge_id": 2,
                                       "members": [{"name": "A"}, {"name": "B"}]})
        row = self.store.state()["teams"][0]
        self.assertEqual(row["member_count"], 2)
        self.assertEqual(row["challenge_title"], "Reto dos")
        self.assertEqual(row["challenge_num"], 2)
        self.assertNotIn("last_note", row)

    def test_challenge_team_count_and_detail(self):
        self.store.create_team({"name": "A", "challenge_id": 1})
        self.store.create_team({"name": "B", "challenge_id": 1})
        counts = dict((c["id"], c["team_count"]) for c in self.store.state()["challenges"])
        self.assertEqual(counts[1], 2)
        self.assertEqual(counts[2], 0)
        detail = self.store.get_challenge(1)
        self.assertEqual([t["name"] for t in detail["teams"]], ["A", "B"])

    def test_delete_cascade(self):
        team = self.store.create_team({"name": "X", "members": [{"name": "A"}]})
        self.store.delete_team(team["id"])
        self.assertEqual(self.count("members"), 0)
        with self.assertRaises(NotFound):
            self.store.delete_team(team["id"])


class TestMembersAndVisits(StoreTestCase):
    def setUp(self):
        super(TestMembersAndVisits, self).setUp()
        self.team = self.store.create_team({"name": "X"}, actor="Ale")

    def test_member_crud(self):
        member = self.store.create_member(self.team["id"], {"name": "Ana", "role": "diseno"})
        updated = self.store.update_member(member["id"], {"role": "ciencia", "skills": "R"})
        self.assertEqual((updated["role"], updated["skills"]), ("ciencia", "R"))
        with self.assertRaises(ValidationError):
            self.store.update_member(member["id"], {"role": "xx"})
        self.store.delete_member(member["id"])
        self.assertEqual(self.store.get_team(self.team["id"])["members"], [])

    def test_member_private_notes_are_ignored(self):
        member = self.store.create_member(self.team["id"], {"name": "Ana", "notes": "secreto"})
        self.assertNotIn("notes", member)
        self.assertEqual(self.store.search("secreto")["members"], [])

    def test_updated_by_tracks_last_editor(self):
        self.assertEqual(self.team["updated_by"], "Ale")
        self.store.update_team(self.team["id"], {"idea": "x"}, actor="Marta")
        self.assertEqual(self.store.get_team(self.team["id"])["updated_by"], "Marta")
        self.store.create_member(self.team["id"], {"name": "Ana"}, actor="Pau")
        self.assertEqual(self.store.get_team(self.team["id"])["updated_by"], "Pau")

    def test_mark_visit(self):
        self.assertIsNone(self.team["last_visit_at"])
        team = self.store.mark_visit(self.team["id"], actor="Marta")
        self.assertTrue(team["last_visit_at"].endswith("Z"))
        self.assertEqual(team["last_visit_by"], "Marta")
        with self.assertRaises(NotFound):
            self.store.mark_visit(999)

    def test_ids_are_not_reused_after_create(self):
        a = self.store.create_team({"name": "A"})
        b = self.store.create_team({"name": "B"})
        self.assertGreater(b["id"], a["id"])


class TestSearchAndExport(StoreTestCase):
    def test_search(self):
        team = self.store.create_team({"name": "Astronautas", "idea": "Cohete reutilizable",
                                       "members": [{"name": "Ñoño", "skills": "Soldadura"}]})
        result = self.store.search("COHETE")
        self.assertEqual(len(result["teams"]), 1)
        self.assertEqual(set(result), {"teams", "members"})
        self.assertEqual(self.store.search("ÑOÑO")["members"][0]["team_name"], "Astronautas")
        self.assertEqual(self.store.search("100%")["teams"], [])
        self.assertEqual(self.store.search("")["teams"], [])

    def test_search_limit(self):
        for i in range(25):
            self.store.create_team({"name": "Equipo %d" % i})
        self.assertEqual(len(self.store.search("equipo")["teams"]), 20)

    def test_export_import_roundtrip(self):
        team = self.store.create_team({"name": "A", "challenge_id": 1, "phase": "demo",
                                       "members": [{"name": "Ana", "role": "dev"}]})
        dump = self.store.export_all()
        self.assertEqual(dump["version"], 2)
        self.assertEqual(set(dump), {"version", "exported_at", "teams", "members",
                                     "team_methods"})

        other = self.store if self.pg else self.make_store("otra")
        other.create_team({"name": "Se borrará"})
        self.assertEqual(other.import_all(dump), 1)
        restored = other.get_team(team["id"])
        self.assertEqual(restored["name"], "A")
        self.assertEqual(restored["phase"], "demo")
        self.assertEqual(restored["members"][0]["name"], "Ana")
        self.assertEqual(len(other.state()["teams"]), 1)
        # tras importar, los nuevos ids no chocan con los importados
        new = other.create_team({"name": "Nuevo", "members": [{"name": "Z"}]})
        self.assertGreater(new["id"], team["id"])

    def test_import_accepts_v1_with_notes(self):
        dump = {"version": 1, "teams": [{"id": 5, "name": "Viejo"}],
                "members": [{"id": 1, "team_id": 5, "name": "Ana", "notes": "x"}],
                "notes": [{"id": 1, "team_id": 5, "body": "se ignora"}]}
        self.assertEqual(self.store.import_all(dump), 1)
        self.assertEqual(self.store.get_team(5)["members"][0]["name"], "Ana")

    def test_import_rejects_garbage_and_keeps_data(self):
        self.store.create_team({"name": "A"})
        for bad in ({}, {"version": 9}, {"version": 2}, {"version": 1, "teams": "x", "members": [], "notes": []},
                    {"version": 1, "teams": [{"id": 1, "name": "T", "phase": "zzz"}],
                     "members": [], "notes": []}):
            with self.assertRaises(ValidationError):
                self.store.import_all(bad)
        self.assertEqual(len(self.store.state()["teams"]), 1)


# Variantes Postgres de todas las clases (solo si hay TEST_DATABASE_URL)
if PG_URL:
    for _cls in (TestSeedAndInit, TestTeams, TestMembersAndVisits, TestSearchAndExport):
        _name = _cls.__name__ + "Pg"
        globals()[_name] = type(_name, (_cls,), {"pg": True})


if __name__ == "__main__":
    unittest.main()
