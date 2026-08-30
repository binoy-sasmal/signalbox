"""Apply the schema. Explicit, idempotent, and never run by the service.

ADR 0009 decision 4. A service that converges its own schema on every boot is a
second reconciler over objects ADR 0003 assigns to ArgoCD. Stage 2 replaces this
command with operator-managed CRDs; keeping it out of the service's startup path
makes that a swap rather than a conflict.

    python -m ingest.migrate tenants/hsl_tripupdates.yaml
"""
from __future__ import annotations

import os
import pathlib
import sys

import psycopg

from . import config

SQL_DIR = pathlib.Path(__file__).resolve().parent.parent / "sql"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    tenant = config.load(argv[1])
    dsn = os.environ.get("SIGNALBOX_DSN")
    if not dsn:
        print("SIGNALBOX_DSN is not set", file=sys.stderr)
        return 2

    # config.load has already checked db_schema against ^[a-z][a-z0-9_]*$. It is
    # interpolated rather than parameterised because an identifier cannot be a bind
    # parameter; the validation is what makes that safe, and it happens before the
    # value reaches this module.
    statements = (SQL_DIR / "001_schema.sql").read_text(encoding="utf-8")
    statements = statements.replace("{schema}", tenant.db_schema)

    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(statements)
        conn.commit()

    print(f"[migrate] schema {tenant.db_schema} applied for tenant {tenant.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
