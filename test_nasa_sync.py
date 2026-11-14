import json
import os
import shutil
import tempfile
import unittest

import nasa_sync
from store import Store, ValidationError

SEED = {"challenges": [
    {"num": 1, "slug": "health-monitoring-software", "title": "Software de salud",
     "title_en": "Create Health Monitoring Software for Astronauts on Space Missions"},
    {"num": 2, "slug": "dancing-with-the-sars", "title": "Bailando con los SAR",
     "title_en": "Dancing with the SARs"},
], "methods": []}

HEALTH = "Create Health Monitoring Software for Astronauts on Space Missions"


def nasa(*teams):
    return {"teams": list(teams)}


BIG5 = {"slug": "the-big-5", "name": "The BIG 5", "challenge_en": "Dancing with the SARs",
        "members": [{"name": "Zhivko Stoimchev", "owner": True}, {"name": "Elizaveta"}]}
VITAL = {"slug": "vitalorbitv2", "name": "VitalOrbitV2", "challenge_en": HEALTH,
         "members": [{"name": "José María", "owner": True}]}


class NasaSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        seed = os.path.join(self.tmp, "seed.json")
        with open(seed, "w", encoding="utf-8") as fh:
            json.dump(SEED, fh)
        self.store = Store(data_dir=self.tmp, seed_path=seed, backup=False)

    def sync(self, data, actor="Ale"):
        plan = nasa_sync.preview(self.store, data)
        return plan, nasa_sync.apply(self.store, dict(data, plan_hash=plan["plan_hash"]), actor=actor)

    def teams(self):
        return {t["name"]: self.store.get_team(t["id"]) for t in self.store.state()["teams"]}

    def test_first_sync_creates_everything(self):
        plan, res = self.sync(nasa(BIG5, VITAL))
        self.assertEqual([c["name"] for c in plan["created"]], ["The BIG 5", "VitalOrbitV2"])
        self.assertEqual(plan["created"][0]["challenge"], "Bailando con los SAR")
        self.assertEqual(res["created"], 2)
        big5 = self.teams()["The BIG 5"]
        self.assertEqual(big5["challenge_id"], 2)
        self.assertEqual(big5["nasa_slug"], "the-big-5")
        self.assertEqual(big5["updated_by"], "NASA (vía Ale)")
        self.assertEqual(big5["idea"], "")
        owner = [m for m in big5["members"] if m["name"] == "Zhivko Stoimchev"][0]
        self.assertEqual(owner["skills"], nasa_sync.OWNER_SKILL)

    def test_second_sync_is_noop(self):
        self.sync(nasa(BIG5, VITAL))
        plan, res = self.sync(nasa(BIG5, VITAL))
        self.assertEqual((plan["created"], plan["updated"], plan["deleted"]), ([], [], []))
        self.assertEqual(plan["unchanged"], 2)

    def test_nasa_overwrites_official_fields_keeps_mentor_work(self):
        self.sync(nasa(BIG5))
        t = self.teams()["The BIG 5"]
        self.store.update_team(t["id"], {"name": "Big Five", "phase": "mvp", "attention": 1,
                                         "table_label": "A7", "idea": "Radar", "challenge_id": 1})
        eli = [m for m in t["members"] if m["name"] == "Elizaveta"][0]
        self.store.update_member(eli["id"], {"role": "dev", "skills": "Python"})
        self.store.create_member(t["id"], {"name": "Intruso"})
        changed = dict(BIG5, members=BIG5["members"][1:] + [{"name": "Nueva Persona"}])
        plan, res = self.sync(nasa(changed))
        upd = plan["updated"][0]
        self.assertEqual(len(upd["changes"]), 2)  # nombre y reto
        self.assertEqual(sorted(upd["members_removed"]), ["Intruso", "Zhivko Stoimchev"])
        self.assertEqual(upd["members_added"], ["Nueva Persona"])
        after = self.store.get_team(t["id"])
        self.assertEqual((after["name"], after["challenge_id"]), ("The BIG 5", 2))
        self.assertEqual((after["phase"], after["attention"], after["table_label"], after["idea"]),
                         ("mvp", 1, "A7", "Radar"))
        eli_after = [m for m in after["members"] if m["name"] == "Elizaveta"][0]
        self.assertEqual((eli_after["id"], eli_after["role"], eli_after["skills"]),
                         (eli["id"], "dev", "Python"))
        self.assertEqual(sorted(m["name"] for m in after["members"]),
                         ["Elizaveta", "Nueva Persona"])

    def test_deletes_teams_not_in_nasa_including_manual(self):
        self.store.create_team({"name": "Equipo a mano"})
        self.sync(nasa(BIG5, VITAL))
        plan, res = self.sync(nasa(BIG5))
        self.assertEqual([d["name"] for d in plan["deleted"]], ["VitalOrbitV2"])
        self.assertEqual(set(self.teams()), {"The BIG 5"})

    def test_links_manual_team_by_name_and_keeps_its_id(self):
        manual = self.store.create_team({"name": "the big 5", "phase": "demo",
                                         "members": [{"name": "zhivko stoimchev", "role": "negocio"}]})
        plan, res = self.sync(nasa(BIG5))
        self.assertEqual(plan["created"], [])
        self.assertEqual(plan["deleted"], [])
        after = self.store.get_team(manual["id"])
        self.assertEqual((after["name"], after["phase"], after["nasa_slug"]),
                         ("The BIG 5", "demo", "the-big-5"))
        z = [m for m in after["members"] if m["name"] == "Zhivko Stoimchev"][0]
        self.assertEqual(z["role"], "negocio")

    def test_apply_rejects_stale_plan(self):
        plan = nasa_sync.preview(self.store, nasa(BIG5))
        self.store.create_team({"name": "Otro mentor lo acaba de crear"})
        with self.assertRaises(nasa_sync.PlanChanged) as ctx:
            nasa_sync.apply(self.store, dict(nasa(BIG5), plan_hash=plan["plan_hash"]))
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(len(self.store.state()["teams"]), 1)

    def test_apply_requires_preview_hash(self):
        with self.assertRaises(ValidationError):
            nasa_sync.apply(self.store, nasa(BIG5))

    def test_rejects_empty_or_invalid_payload(self):
        for bad in ({"teams": []}, {"foo": 1}, {"teams": [{"slug": "", "name": "X"}]},
                    {"teams": [BIG5, BIG5]}, "texto"):
            with self.assertRaises(ValidationError):
                nasa_sync.preview(self.store, bad)

    def test_rejects_incomplete_scrape(self):
        with self.assertRaises(ValidationError) as ctx:
            nasa_sync.preview(self.store, dict(nasa(BIG5), expected_total=30))
        self.assertIn("incompletos", str(ctx.exception))
        self.assertEqual(nasa_sync.preview(self.store, dict(nasa(BIG5), expected_total=1))["totals"]["teams"], 1)

    def test_unknown_challenge_warns(self):
        plan = nasa_sync.preview(self.store, nasa(dict(VITAL, challenge_en="Reto nuevo")))
        self.assertTrue(plan["warnings"])
        self.assertIsNone(plan["created"][0]["challenge"])

    def test_real_scraped_file(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nasa", "teams_valencia.json")
        if not os.path.exists(path):
            self.skipTest("sin nasa/teams_valencia.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        plan = nasa_sync.preview(self.store, data)
        self.assertEqual(plan["totals"]["teams"], len(data["teams"]))


if __name__ == "__main__":
    unittest.main()
