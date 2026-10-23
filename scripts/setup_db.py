"""Apply db/schema.sql and upsert db/seed_items.json into the Postgres at DATABASE_URL.

Usage: DATABASE_URL=postgres://... python scripts/setup_db.py [--no-seed]
"""

import json
import os
import sys

import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    with psycopg.connect(dsn) as conn:
        with open(os.path.join(ROOT, "db", "schema.sql")) as f:
            conn.execute(f.read())
        print("schema applied")
        if "--no-seed" in sys.argv:
            return
        with open(os.path.join(ROOT, "db", "seed_items.json")) as f:
            items = json.load(f)
        with conn.cursor() as cur:
            cur.executemany(
                """insert into items (sku, name, category, color, material, size, price, stock, image)
                   values (%(sku)s, %(name)s, %(category)s, %(color)s, %(material)s, %(size)s, %(price)s,
                           %(stock)s, %(image)s)
                   on conflict (sku) do update set name = excluded.name, category = excluded.category,
                       color = excluded.color, material = excluded.material, size = excluded.size,
                       price = excluded.price, stock = excluded.stock, image = excluded.image""",
                items,
            )
        print(f"seeded {len(items)} items")


if __name__ == "__main__":
    main()
