from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import DEFAULT_PRIOR_ITEMS, app, get_db, seed_default_priors


with app.app_context():
    seed_default_priors()
    names = [item["name"] for item in DEFAULT_PRIOR_ITEMS]
    placeholders = ",".join("?" for _ in names)
    rows = get_db().execute(
        f"""
        SELECT name, picture
        FROM item_prior
        WHERE name IN ({placeholders})
        ORDER BY lower(name)
        """,
        names,
    ).fetchall()
    for row in rows:
        status = "picture" if row["picture"] else "no-picture"
        print(f"{row['name']}: {status}")
