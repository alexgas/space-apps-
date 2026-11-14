#!/usr/bin/env python3
"""Sincroniza los equipos desde un JSON de la web NASA, desde la terminal.

Hace lo mismo que el botón "Refrescar equipos NASA" del CRM (ver nasa_sync.py):
la web NASA manda en equipos, nombres, retos y miembros; se conserva el trabajo de
los mentores. Útil si prefieres no usar el navegador.

  python3 import_nasa.py                              # muestra los cambios (no guarda)
  python3 import_nasa.py --yes                        # aplica en SQLite local (data/)
  DATABASE_URL="postgresql://..." python3 import_nasa.py --yes   # aplica en Render
"""
import argparse
import json
import os
import sys

import nasa_sync
from store import Store

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--file", default=os.path.join(HERE, "nasa", "teams_valencia.json"))
    ap.add_argument("--yes", action="store_true", help="aplica los cambios (sin esto solo los muestra)")
    ap.add_argument("--data-dir", help="carpeta de la BD SQLite (por defecto data/)")
    args = ap.parse_args(argv)

    with open(args.file, encoding="utf-8") as fh:
        data = json.load(fh)
    url = os.environ.get("DATABASE_URL")
    store = Store(data_dir=args.data_dir, database_url=url, backup=args.yes)
    try:
        plan = nasa_sync.preview(store, data)
        print("BD: %s · %d equipos en el fichero" % ("Postgres" if url else store.db_path,
                                                    plan["totals"]["teams"]))
        print("Nuevos (%d): %s" % (len(plan["created"]), ", ".join(c["name"] for c in plan["created"]) or "-"))
        for u in plan["updated"]:
            bits = u["changes"] + ["+" + n for n in u["members_added"]] + ["-" + n for n in u["members_removed"]]
            print("Cambia %s: %s" % (u["name"], "; ".join(bits)))
        print("Se BORRAN (%d): %s" % (len(plan["deleted"]), ", ".join(d["name"] for d in plan["deleted"]) or "-"))
        print("Sin cambios: %d" % (plan["unchanged"] + plan["linked"]))
        for w in plan["warnings"]:
            print("  aviso: " + w)
        if not args.yes:
            print("\nNo se ha guardado nada. Repite con --yes para aplicar.")
            return 0
        res = nasa_sync.apply(store, dict(data, plan_hash=plan["plan_hash"]), actor="terminal")
        print("\nAplicado: %(created)d nuevos, %(updated)d actualizados, %(deleted)d borrados." % res)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
