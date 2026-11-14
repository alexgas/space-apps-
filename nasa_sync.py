"""Sincroniza los equipos del CRM con la web oficial de Space Apps (fuente de la verdad).

La web NASA manda en: qué equipos existen, su nombre, su reto oficial y su lista de
miembros. El CRM conserva lo que trabajan los mentores: fase, "necesita atención",
mesa, idea/problema/solución/enlaces, visitas, métodos y el rol/habilidades de los
miembros que siguen en el equipo.

Flujo: preview(store, datos) -> plan con los cambios y una huella (plan_hash).
       apply(store, datos, plan_hash) -> aplica solo si el plan no ha cambiado entre medias.

Formato de entrada (lo genera el marcador del CRM o nasa/scrape_teams.js):
  {"teams": [{"slug": "the-big-5", "name": "The BIG 5",
              "challenge_en": "Dancing with the SARs",
              "members": [{"name": "Zhivko Stoimchev", "owner": true}, ...]}, ...]}
"""
import hashlib
import json
import re
import unicodedata

from store import ValidationError, now_iso

TEAM_URL = "https://www.spaceappschallenge.org/2026/find-a-team/%s/"
OWNER_SKILL = "Owner del equipo (NASA)"
MAX_TEAMS = 400
MAX_MEMBERS = 30
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$")


class PlanChanged(ValidationError):
    """Los datos del CRM cambiaron entre la revisión y la confirmación (HTTP 409)."""
    status = 409


def norm(text):
    """Clave de comparación: sin tildes, minúsculas, solo letras y números."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _str(value, label, max_len):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError("%s debe ser texto." % label)
    value = " ".join(value.split())
    if len(value) > max_len:
        raise ValidationError("%s demasiado largo." % label)
    return value


def parse(data):
    """Valida el JSON recibido y devuelve la lista normalizada de equipos NASA."""
    raw = data.get("teams") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise ValidationError("No encuentro la lista de equipos. Pega el JSON que copia el "
                              "marcador desde la web de Space Apps.")
    if not raw:
        raise ValidationError("La lista de equipos está vacía: no se sincroniza para no "
                              "borrar todos los equipos por error.")
    expected = data.get("expected_total") if isinstance(data, dict) else None
    if isinstance(expected, int) and not isinstance(expected, bool) and expected > len(raw):
        raise ValidationError("Datos incompletos: la web NASA dice %d equipos y el JSON trae %d. "
                              "Vuelve a lanzar el marcador; sincronizar así borraría equipos."
                              % (expected, len(raw)))
    if len(raw) > MAX_TEAMS:
        raise ValidationError("Demasiados equipos (%d)." % len(raw))
    teams, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("Cada equipo debe ser un objeto.")
        slug = _str(item.get("slug"), "El identificador del equipo", 120).strip("/")
        name = _str(item.get("name"), "El nombre del equipo", 120)
        if not SLUG_RE.match(slug) or not name:
            raise ValidationError("Hay un equipo sin nombre o sin identificador válido (%r)."
                                  % (name or slug))
        if slug in seen:
            raise ValidationError("El equipo %s aparece dos veces." % name)
        seen.add(slug)
        members_raw = item.get("members") or []
        if not isinstance(members_raw, list) or len(members_raw) > MAX_MEMBERS:
            raise ValidationError("Lista de miembros no válida en %s." % name)
        members, mkeys = [], set()
        for m in members_raw:
            if not isinstance(m, dict):
                raise ValidationError("Miembro no válido en %s." % name)
            mname = _str(m.get("name"), "El nombre del miembro", 120)
            if mname and norm(mname) not in mkeys:
                mkeys.add(norm(mname))
                members.append({"name": mname, "owner": bool(m.get("owner"))})
        teams.append({
            "slug": slug, "name": name, "url": TEAM_URL % slug,
            "challenge_en": _str(item.get("challenge_en") or item.get("challenge"), "El reto", 300),
            "members": members,
        })
    return teams


# ------------------------------------------------------------------- plan

def _challenge_index(conn):
    index = {}
    for r in conn.execute("SELECT id, slug, title, title_en FROM challenges"):
        for key in (r["title_en"], r["title"], r["slug"]):
            if key:
                index[norm(key)] = (r["id"], r["title"])
    return index


def _plan(conn, nasa):
    chal = _challenge_index(conn)
    titles = {cid: title for cid, title in chal.values()}
    crm = [dict(r) for r in conn.execute(
        "SELECT id, name, challenge_id, nasa_slug FROM teams ORDER BY id")]
    members = {}
    for r in conn.execute("SELECT id, team_id, name FROM members ORDER BY id"):
        members.setdefault(r["team_id"], []).append(dict(r))

    by_slug = {t["nasa_slug"]: t for t in crm if t["nasa_slug"]}
    by_name = {}
    for t in crm:
        if not t["nasa_slug"]:
            by_name.setdefault(norm(t["name"]), t)
    used = set()
    plan = {"created": [], "updated": [], "deleted": [], "unchanged": 0, "warnings": [],
            "totals": {"teams": len(nasa), "members": sum(len(t["members"]) for t in nasa)}}

    for t in nasa:
        hit = chal.get(norm(t["challenge_en"])) if t["challenge_en"] else None
        if t["challenge_en"] and not hit:
            plan["warnings"].append("%s: el reto «%s» no está en el CRM; queda sin reto."
                                    % (t["name"], t["challenge_en"]))
        cid = hit[0] if hit else None
        row = by_slug.get(t["slug"])
        if row is None:
            cand = by_name.get(norm(t["name"]))
            if cand is not None and cand["id"] not in used:
                row = cand
        if row is None:
            plan["created"].append({"slug": t["slug"], "name": t["name"], "url": t["url"],
                                    "challenge_id": cid, "challenge": titles.get(cid),
                                    "members": t["members"]})
            continue
        used.add(row["id"])
        current = members.get(row["id"], [])
        cur_keys = {norm(m["name"]): m for m in current}
        nasa_keys = {norm(m["name"]) for m in t["members"]}
        change = {"id": row["id"], "slug": t["slug"], "name": t["name"], "url": t["url"],
                  "challenge_id": cid, "changes": [], "members_added": [],
                  "members_removed": [], "members_renamed": []}
        if row["name"] != t["name"]:
            change["changes"].append("nombre: «%s» → «%s»" % (row["name"], t["name"]))
        if row["challenge_id"] != cid:
            change["changes"].append("reto: %s → %s" % (titles.get(row["challenge_id"]) or "sin reto",
                                                        titles.get(cid) or "sin reto"))
        if row["nasa_slug"] != t["slug"]:
            change["link_only"] = not change["changes"]
        for m in t["members"]:
            old = cur_keys.get(norm(m["name"]))
            if old is None:
                change["members_added"].append(m)
            elif old["name"] != m["name"]:
                change["members_renamed"].append({"id": old["id"], "name": m["name"]})
        change["members_removed"] = [{"id": m["id"], "name": m["name"]} for m in current
                                     if norm(m["name"]) not in nasa_keys]
        visible = (change["changes"] or change["members_added"] or change["members_removed"]
                   or change["members_renamed"])
        if visible or row["nasa_slug"] != t["slug"]:
            change["visible"] = bool(visible)
            plan["updated"].append(change)
        else:
            plan["unchanged"] += 1

    for row in crm:
        if row["id"] not in used:
            plan["deleted"].append({"id": row["id"], "name": row["name"],
                                    "member_count": len(members.get(row["id"], []))})
    plan["plan_hash"] = _hash(plan)
    return plan


def _hash(plan):
    core = {k: plan[k] for k in ("created", "updated", "deleted", "unchanged")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()[:16]


def _public(plan):
    """Lo que ve el mentor en la revisión (sin ids internos de miembros)."""
    return {
        "plan_hash": plan["plan_hash"],
        "totals": plan["totals"],
        "unchanged": plan["unchanged"],
        "warnings": plan["warnings"],
        "created": [{"name": c["name"], "url": c["url"], "challenge": c["challenge"],
                     "members": [m["name"] for m in c["members"]]} for c in plan["created"]],
        "updated": [{"id": u["id"], "name": u["name"], "url": u["url"], "changes": u["changes"],
                     "members_added": [m["name"] for m in u["members_added"]],
                     "members_removed": [m["name"] for m in u["members_removed"]],
                     "members_renamed": [m["name"] for m in u["members_renamed"]]}
                    for u in plan["updated"] if u.get("visible")],
        "linked": len([u for u in plan["updated"] if not u.get("visible")]),
        "deleted": [{"id": d["id"], "name": d["name"], "member_count": d["member_count"]}
                    for d in plan["deleted"]],
    }


# ------------------------------------------------------------------- API

def preview(store, data):
    nasa = parse(data)
    with store._conn() as conn:
        return _public(_plan(conn, nasa))


def apply(store, data, actor=""):
    if not isinstance(data, dict) or not data.get("plan_hash"):
        raise ValidationError("Falta la confirmación: revisa los cambios antes de aplicarlos.")
    nasa = parse(data)
    who = "NASA" + (" (vía %s)" % actor if actor else "")
    now = now_iso()
    with store._write() as conn:
        plan = _plan(conn, nasa)
        if plan["plan_hash"] != data["plan_hash"]:
            raise PlanChanged("Los equipos han cambiado desde que revisaste (otro mentor o una "
                              "carga nueva). Vuelve a revisar los cambios.")
        for d in plan["deleted"]:
            conn.execute("DELETE FROM teams WHERE id=?", (d["id"],))
        for c in plan["created"]:
            cur = conn.execute(
                "INSERT INTO teams(name, challenge_id, nasa_slug, phase, attention, created_at, "
                "updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?)",
                (c["name"], c["challenge_id"], c["slug"], "idea", 0, now, now, who))
            for m in c["members"]:
                _insert_member(conn, cur.lastrowid, m, now)
        for u in plan["updated"]:
            for m in u["members_removed"]:
                conn.execute("DELETE FROM members WHERE id=?", (m["id"],))
            for m in u["members_renamed"]:
                conn.execute("UPDATE members SET name=? WHERE id=?", (m["name"], m["id"]))
            for m in u["members_added"]:
                _insert_member(conn, u["id"], m, now)
            if u.get("visible"):
                conn.execute("UPDATE teams SET name=?, challenge_id=?, nasa_slug=?, updated_at=?, "
                             "updated_by=? WHERE id=?",
                             (u["name"], u["challenge_id"], u["slug"], now, who, u["id"]))
            else:
                conn.execute("UPDATE teams SET nasa_slug=? WHERE id=?", (u["slug"], u["id"]))
    return {"ok": True,
            "created": len(plan["created"]),
            "updated": len([u for u in plan["updated"] if u.get("visible")]),
            "deleted": len(plan["deleted"]),
            "unchanged": plan["unchanged"] + len([u for u in plan["updated"] if not u.get("visible")]),
            "teams": len(nasa)}


def _insert_member(conn, team_id, m, now):
    conn.execute("INSERT INTO members(team_id, name, role, skills, created_at) VALUES(?,?,?,?,?)",
                 (team_id, m["name"], "otro", OWNER_SKILL if m["owner"] else "", now))
