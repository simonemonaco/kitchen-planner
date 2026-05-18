from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import Client, create_client


LOCATIONS = {
    "frigo": "Frigo",
    "dispensa": "Dispensa",
}

CATEGORIES = [
    "Carne",
    "Pesce",
    "Uova",
    "Latticini",
    "Formaggi",
    "Cereali",
    "Legumi",
    "Pasta",
    "Verdura",
    "Frutta",
    "Dolci",
    "Altro",
]

OPEN_FOOD_FACTS_SEARCH_URL = "https://world.openfoodfacts.org/api/v2/search"
WIKIDATA_SEARCH_URL = "https://www.wikidata.org/w/api.php"


load_dotenv()

DEFAULT_PRIOR_ITEMS = [
    {
        "name": "Mozzarella",
        "category": "Formaggi",
        "default_location": "frigo",
        "typical_quantity": 125,
        "typical_unit": "g",
        "typical_shelf_life_days": 10,
    },
    {
        "name": "Pasta",
        "category": "Pasta",
        "default_location": "dispensa",
        "typical_quantity": 500,
        "typical_unit": "g",
        "typical_shelf_life_days": 365,
    },
    {
        "name": "Riso",
        "category": "Cereali",
        "default_location": "dispensa",
        "typical_quantity": 1,
        "typical_unit": "kg",
        "typical_shelf_life_days": 365,
    },
    {
        "name": "Farro",
        "category": "Cereali",
        "default_location": "dispensa",
        "typical_quantity": 500,
        "typical_unit": "g",
        "typical_shelf_life_days": 365,
    },
    {
        "name": "Melanzane",
        "category": "Verdura",
        "default_location": "frigo",
        "typical_quantity": 1,
        "typical_unit": "pz",
        "typical_shelf_life_days": 5,
    },
    {
        "name": "Mele",
        "category": "Frutta",
        "default_location": "frigo",
        "typical_quantity": 1,
        "typical_unit": "kg",
        "typical_shelf_life_days": 30,
    },
    {
        "name": "Pere",
        "category": "Frutta",
        "default_location": "frigo",
        "typical_quantity": 1,
        "typical_unit": "kg",
        "typical_shelf_life_days": 7,
    },
    {
        "name": "Fragole",
        "category": "Frutta",
        "default_location": "frigo",
        "typical_quantity": 250,
        "typical_unit": "g",
        "typical_shelf_life_days": 3,
    },
]

INGREDIENT_IMAGE_FALLBACKS = {
    "melanzane": "Aubergine",
    "mele": "Apple",
    "riso": "Rice",
}

REQUIRED_TABLES = [
    "item_prior",
    "inventory_items",
    "shopping_items",
    "items_history",
]


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY="dev",
        ENABLE_FOOD_IMAGE_LOOKUP=True,
        SEED_DEFAULT_PRIORS=True,
        OPEN_FOOD_FACTS_USER_AGENT="KitchenPlanner/0.1 (local development)",
        OPEN_FOOD_FACTS_TIMEOUT=4,
    )

    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    register_template_helpers(app)
    register_routes(app)

    with app.app_context():
        init_db()

    return app


def get_supabase() -> Client:
    if "supabase" not in g:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL e SUPABASE_KEY devono essere configurati.")
        g.supabase = create_client(url, key)
    return g.supabase


def current_app_config(key: str) -> Any:
    from flask import current_app

    return current_app.config[key]


def init_db() -> None:
    ensure_supabase_schema()
    if current_app_config("SEED_DEFAULT_PRIORS"):
        seed_default_priors()


def ensure_supabase_schema() -> None:
    supabase = get_supabase()
    missing_tables: list[str] = []

    for table_name in REQUIRED_TABLES:
        try:
            supabase.table(table_name).select("id").limit(1).execute()
        except APIError as exc:
            if exc.code == "PGRST205":
                missing_tables.append(table_name)
                continue
            raise

    if missing_tables:
        joined = ", ".join(sorted(missing_tables))
        raise RuntimeError(
            "Schema Supabase non inizializzato. Tabelle mancanti: "
            f"{joined}. Esegui lo script scripts/supabase_schema.sql nel SQL Editor di Supabase."
        )


def register_template_helpers(app: Flask) -> None:
    @app.template_filter("qty")
    def qty(value: float | int | None) -> str:
        if value in (None, ""):
            return ""
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.2f}".rstrip("0").rstrip(".")

    @app.template_filter("money")
    def money(value: float | int | None) -> str:
        if value is None:
            return "-"
        return f"{float(value):.2f} EUR"

    @app.template_filter("date_it")
    def date_it(value: str | None) -> str:
        parsed = parse_iso_date(value)
        if not parsed:
            return "Nessuna"
        return parsed.strftime("%d/%m/%Y")

    @app.template_filter("datetime_it")
    def datetime_it(value: str | None) -> str:
        parsed = parse_datetime(value)
        if not parsed:
            return "-"
        return parsed.strftime("%d/%m/%Y %H:%M")

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "locations": LOCATIONS,
            "categories": CATEGORIES,
            "today": date.today().isoformat(),
            "now_local_value": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        }


def register_routes(app: Flask) -> None:
    @app.get("/")
    def index():
        location = request.args.get("location", "").strip()
        requested_view = request.args.get("view", "").strip().lower()
        selected_location = location if location in LOCATIONS else ""
        if requested_view in {"grid", "list"}:
            view_mode = requested_view
        else:
            view_mode = "grid"
        items = list_inventory_items(location if location in LOCATIONS else None)
        stats = load_dashboard_stats()
        return render_template(
            "index.html",
            items=items,
            stats=stats,
            selected_location=selected_location,
            view_mode=view_mode,
        )

    @app.route("/inventory/add", methods=("GET", "POST"))
    def add_inventory_item():
        if request.method == "POST":
            data = inventory_form_data(request.form)
            errors = validate_inventory_data(data)
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template(
                    "inventory_form.html",
                    item=data,
                    mode="add",
                    prior_options=list_item_prior_options(),
                ), 400

            prior_id = ensure_item_prior(
                data,
                existing_prior_id=data.get("item_prior_id"),
                update_existing=False,
            )
            create_inventory_item(prior_id, data)
            flash("Prodotto aggiunto all'inventario.", "success")
            return redirect(url_for("index"))

        return render_template(
            "inventory_form.html",
            item=empty_inventory_form(),
            mode="add",
            prior_options=list_item_prior_options(),
        )

    @app.route("/inventory/<int:item_id>/edit", methods=("GET", "POST"))
    def edit_inventory_item(item_id: int):
        item = get_inventory_item(item_id)
        if not item:
            flash("Prodotto non trovato.", "error")
            return redirect(url_for("index"))

        if request.method == "POST":
            data = inventory_form_data(request.form)
            errors = validate_inventory_data(data)
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template(
                    "inventory_form.html",
                    item=data | {"id": item_id, "item_prior_id": item["item_prior_id"]},
                    mode="edit",
                    prior_options=list_item_prior_options(),
                ), 400

            prior_id = ensure_item_prior(
                data,
                existing_prior_id=data.get("item_prior_id") or item["item_prior_id"],
                update_existing=False,
            )
            update_inventory_item(item_id, prior_id, data)
            flash("Prodotto aggiornato.", "success")
            return redirect(url_for("index"))

        return render_template(
            "inventory_form.html",
            item=dict(item),
            mode="edit",
            prior_options=list_item_prior_options(),
        )

    @app.post("/inventory/<int:item_id>/finish")
    def finish_inventory_item(item_id: int):
        item = get_inventory_item(item_id)
        if not item:
            flash("Prodotto non trovato.", "error")
            return redirect(url_for("index"))

        add_or_increment_shopping_item(
            item_prior_id=item["item_prior_id"],
            quantity=max(float(item["quantity"] or 1), 1),
            unit=item["unit"],
            target_location=item["location"],
            notes=item["notes"],
        )
        delete_inventory_item(item_id)
        flash("Prodotto finito: aggiunto alla lista della spesa.", "success")
        return redirect(url_for("index"))

    @app.post("/inventory/<int:item_id>/delete")
    def delete_inventory(item_id: int):
        delete_inventory_item(item_id)
        flash("Prodotto eliminato dall'inventario.", "success")
        return redirect(url_for("index"))

    @app.post("/inventory/<int:item_id>/adjust")
    def adjust_inventory_quantity(item_id: int):
        item = get_inventory_item(item_id)
        if not item:
            flash("Prodotto non trovato.", "error")
            return redirect(url_for("index"))

        direction = clean_text(request.form.get("direction")).lower()
        if direction not in {"inc", "dec"}:
            flash("Azione quantita' non valida.", "error")
            return redirect(url_for("index"))

        step = quantity_adjust_step(item.get("unit"), item.get("typical_quantity"))
        current_quantity = float(item.get("quantity") or 0)
        new_quantity = current_quantity + step if direction == "inc" else current_quantity - step

        if new_quantity <= 0:
            flash("La quantita' non puo' scendere sotto zero.", "error")
            return redirect(url_for("index"))

        payload = {
            "quantity": new_quantity,
            "unit": item["unit"],
            "location": item["location"],
            "expiry_date": item.get("expiry_date"),
            "expiry_estimated": item.get("expiry_estimated") or 0,
            "notes": item.get("notes") or "",
        }
        update_inventory_item(item_id, int(item["item_prior_id"]), payload)
        return redirect(url_for("index", location=request.args.get("location", ""), view=request.args.get("view", "")))

    @app.get("/inventory/receipt")
    def receipt_upload():
        return render_template("receipt_upload.html")

    @app.post("/inventory/receipt/scan")
    def receipt_scan():
        receipt_text = clean_text(request.form.get("receipt_text"))
        if not receipt_text:
            flash(
                "Nessun testo rilevato. Carica una foto e attendi la lettura OCR nel browser, oppure incolla il testo manualmente.",
                "error",
            )
            return redirect(url_for("receipt_upload"))

        rows = parse_receipt_rows(receipt_text)
        if not rows:
            flash("Non ho trovato righe prodotto nello scontrino.", "error")
            return render_template("receipt_upload.html", receipt_text=receipt_text), 400

        matched, unmatched = classify_receipt_rows(rows)
        session["receipt_rows"] = rows
        return render_template(
            "receipt_match.html",
            matched=matched,
            unmatched=unmatched,
            prior_options=list_item_prior_options(),
        )

    @app.post("/inventory/receipt/matched")
    def receipt_add_matched():
        rows = receipt_rows_by_id()
        selected_ids = set(request.form.getlist("selected_row_ids"))
        matched_ids = request.form.getlist("matched_row_ids")
        unmatched_ids = request.form.getlist("unmatched_row_ids")
        unresolved = []
        added_count = 0

        for row_id in matched_ids:
            row = rows.get(row_id)
            if not row:
                continue
            if row_id not in selected_ids:
                unresolved.append(row)
                continue

            prior_id = parse_optional_int(request.form.get(f"prior_id_{row_id}"))
            prior = get_item_prior(prior_id) if prior_id else None
            if not prior:
                unresolved.append(row)
                continue

            add_receipt_item_to_kitchen(
                prior_id=prior["id"],
                quantity=parse_quantity(request.form.get(f"quantity_{row_id}"), default_prior_quantity(prior)),
                unit=clean_text(request.form.get(f"unit_{row_id}"), prior["typical_unit"] or "pz"),
                cost=row.get("price"),
                description=row["description"],
            )
            added_count += 1

        for row_id in unmatched_ids:
            row = rows.get(row_id)
            if row:
                unresolved.append(row)

        if not unresolved:
            session.pop("receipt_rows", None)
            flash(f"{added_count} prodotti aggiunti alla cucina.", "success")
            return redirect(url_for("index"))

        session["receipt_unresolved_rows"] = unresolved
        if added_count:
            flash(f"{added_count} prodotti aggiunti. Completa quelli da rivedere.", "success")
        return render_template(
            "receipt_unmatched.html",
            rows=unresolved,
            prior_options=list_item_prior_options(),
        )

    @app.post("/inventory/receipt/unmatched")
    def receipt_add_unmatched():
        rows = {row["id"]: row for row in session.get("receipt_unresolved_rows", [])}
        include_ids = request.form.getlist("include_row_ids")
        added_count = 0

        for row_id in include_ids:
            row = rows.get(row_id)
            if not row:
                continue
            name = clean_text(request.form.get(f"name_{row_id}"))
            if not name:
                continue

            prior_id = ensure_item_prior(
                {
                    "item_prior_id": parse_optional_int(request.form.get(f"prior_id_{row_id}")),
                    "name": name,
                    "category": "Altro",
                    "typical_quantity": parse_quantity(request.form.get(f"quantity_{row_id}")),
                    "typical_unit": clean_text(request.form.get(f"unit_{row_id}"), "pz"),
                    "default_location": request.form.get(f"location_{row_id}", "dispensa"),
                    "picture": "",
                    "prior_notes": "",
                },
                existing_prior_id=parse_optional_int(request.form.get(f"prior_id_{row_id}")),
                update_existing=False,
            )
            prior = get_item_prior(prior_id)
            add_receipt_item_to_kitchen(
                prior_id=prior_id,
                quantity=parse_quantity(request.form.get(f"quantity_{row_id}"), default_prior_quantity(prior)),
                unit=clean_text(request.form.get(f"unit_{row_id}"), (prior["typical_unit"] if prior else "") or "pz"),
                cost=row.get("price"),
                description=row["description"],
            )
            added_count += 1

        session.pop("receipt_rows", None)
        session.pop("receipt_unresolved_rows", None)
        flash(f"{added_count} prodotti aggiunti alla cucina.", "success")
        return redirect(url_for("index"))

    @app.route("/shopping", methods=("GET", "POST"))
    def shopping():
        if request.method == "POST":
            data = shopping_form_data(request.form)
            errors = validate_shopping_data(data)
            if errors:
                for error in errors:
                    flash(error, "error")
                return redirect(url_for("shopping"))

            prior_id = ensure_item_prior(
                data,
                existing_prior_id=data.get("item_prior_id"),
                update_existing=False,
            )
            add_or_increment_shopping_item(
                item_prior_id=prior_id,
                quantity=data["quantity"],
                unit=data["unit"],
                target_location=data["target_location"],
                notes=data["notes"],
            )
            flash("Prodotto aggiunto alla lista della spesa.", "success")
            return redirect(url_for("shopping"))

        items = list_shopping_items()
        return render_template(
            "shopping.html",
            items=items,
            prior_options=list_item_prior_options(),
        )

    @app.post("/shopping/<int:item_id>/purchase")
    def purchase_shopping_item(item_id: int):
        item = get_shopping_item(item_id)
        if not item:
            flash("Voce della lista non trovata.", "error")
            return redirect(url_for("shopping"))

        quantity = parse_quantity(request.form.get("quantity"), item["quantity"])
        unit = clean_text(request.form.get("unit"), item["unit"])
        target_location = request.form.get("target_location") or item["target_location"]
        typical_shelf_life_days = parse_optional_int(
            request.form.get("typical_shelf_life_days"),
            item["typical_shelf_life_days"],
        )
        cost = parse_optional_money(request.form.get("cost"))
        purchased_at = parse_form_datetime(request.form.get("purchased_at")) or utc_now()

        if quantity <= 0:
            flash("La quantita' acquistata deve essere maggiore di zero.", "error")
            return redirect(url_for("shopping"))

        if target_location not in LOCATIONS:
            flash("Destinazione non valida.", "error")
            return redirect(url_for("shopping"))

        if typical_shelf_life_days != item["typical_shelf_life_days"]:
            update_item_prior(
                item["item_prior_id"],
                {
                    "name": item["name"],
                    "category": item["category"],
                    "typical_quantity": item["typical_quantity"],
                    "typical_unit": item["typical_unit"],
                    "typical_shelf_life_days": typical_shelf_life_days,
                    "picture": item["picture"],
                    "notes": item["prior_notes"],
                },
            )

        expiry_date, expiry_estimated = resolve_expiry(
            request.form.get("expiry_date"),
            typical_shelf_life_days,
        )

        inventory_item_id = create_inventory_item(
            item["item_prior_id"],
            {
                "quantity": quantity,
                "unit": unit,
                "location": target_location,
                "expiry_date": expiry_date,
                "expiry_estimated": expiry_estimated,
                "notes": item["notes"] or "",
            },
        )
        create_history_item(
            {
                "item_prior_id": item["item_prior_id"],
                "inventory_item_id": inventory_item_id,
                "purchased_at": purchased_at,
                "quantity": quantity,
                "unit": unit,
                "cost": cost,
                "target_location": target_location,
                "notes": item["notes"] or "",
            }
        )
        delete_shopping_item(item_id)
        flash("Acquisto registrato, storicizzato e spostato in inventario.", "success")
        return redirect(url_for("shopping"))

    @app.post("/shopping/<int:item_id>/delete")
    def delete_shopping(item_id: int):
        delete_shopping_item(item_id)
        flash("Voce eliminata dalla lista della spesa.", "success")
        return redirect(url_for("shopping"))

    @app.get("/history")
    def history():
        items = list_history_items()
        stats = load_history_stats()
        return render_template("history.html", items=items, stats=stats)

    @app.get("/settings")
    def settings():
        stats = load_settings_stats()
        return render_template("settings.html", stats=stats)

    @app.get("/settings/priors")
    def priors():
        query = request.args.get("q", "").strip()
        items = list_item_priors(query)
        return render_template("priors.html", items=items, query=query)

    @app.route("/settings/priors/<int:prior_id>/edit", methods=("GET", "POST"))
    def edit_prior(prior_id: int):
        prior = get_item_prior(prior_id)
        if not prior:
            flash("Prodotto prior non trovato.", "error")
            return redirect(url_for("priors"))

        if request.method == "POST":
            data = prior_form_data(request.form)
            errors = validate_prior_data(data)
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template(
                    "prior_form.html",
                    item=data | {"id": prior_id},
                ), 400

            update_item_prior(prior_id, data)
            flash("Prodotto prior aggiornato.", "success")
            return redirect(url_for("priors"))

        return render_template("prior_form.html", item=dict(prior))


def empty_inventory_form() -> dict[str, Any]:
    return {
        "item_prior_id": "",
        "name": "",
        "quantity": 1,
        "unit": "pz",
        "location": "dispensa",
        "expiry_date": "",
        "notes": "",
    }


def clean_text(value: str | None, default: str = "") -> str:
    cleaned = (value or "").strip()
    return cleaned or default


def normalize_category(value: str | None) -> str:
    cleaned = clean_text(value, "Altro")
    for category in CATEGORIES:
        if category.casefold() == cleaned.casefold():
            return category
    return cleaned


def parse_quantity(value: str | float | int | None, default: float = 1) -> float:
    if value in (None, ""):
        return float(default)
    try:
        quantity = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)
    return quantity


def parse_optional_quantity(value: str | float | int | None) -> float | None:
    if value in (None, ""):
        return None
    parsed = parse_quantity(value, 0)
    return parsed if parsed > 0 else None


def parse_optional_money(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        cost = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return cost if cost >= 0 else None


def parse_receipt_price(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.strip().replace("€", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_optional_int(value: str | int | None, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def parse_form_datetime(value: str | None) -> str | None:
    parsed = parse_datetime(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def get_selected_prior(prior_id: str | int | None, name: str | None) -> dict[str, Any] | None:
    parsed_id = parse_optional_int(prior_id)
    cleaned_name = clean_text(name)
    if not parsed_id or not cleaned_name:
        return None
    prior = get_item_prior(parsed_id)
    if prior and prior["name"].casefold() == cleaned_name.casefold():
        return prior
    return None


def resolve_expiry(
    exact_date_value: str | None,
    typical_shelf_life_days: int | None,
) -> tuple[str | None, int]:
    exact_date = parse_iso_date(exact_date_value)
    if exact_date:
        return exact_date.isoformat(), 0
    if typical_shelf_life_days:
        return (date.today() + timedelta(days=typical_shelf_life_days)).isoformat(), 1
    return None, 0


def inventory_form_data(form: Any) -> dict[str, Any]:
    selected_prior = get_selected_prior(form.get("item_prior_id"), form.get("name"))
    typical_shelf_life_days = (
        selected_prior["typical_shelf_life_days"] if selected_prior else None
    )
    expiry_date, expiry_estimated = resolve_expiry(
        form.get("expiry_date"),
        typical_shelf_life_days,
    )
    if expiry_date and form.get("expiry_estimated") == "1":
        expiry_estimated = 1
    quantity = parse_quantity(form.get("quantity"))
    unit = clean_text(form.get("unit"), "pz")
    location = form.get("location", "dispensa")
    return {
        "item_prior_id": parse_optional_int(form.get("item_prior_id")),
        "name": clean_text(form.get("name")),
        "category": "Altro",
        "typical_quantity": quantity,
        "typical_unit": unit,
        "typical_shelf_life_days": typical_shelf_life_days,
        "default_location": location,
        "picture": "",
        "prior_notes": "",
        "quantity": quantity,
        "unit": unit,
        "location": location,
        "expiry_date": expiry_date,
        "expiry_estimated": expiry_estimated,
        "notes": clean_text(form.get("notes")),
    }


def shopping_form_data(form: Any) -> dict[str, Any]:
    quantity = parse_quantity(form.get("quantity"))
    unit = clean_text(form.get("unit"), "pz")
    target_location = form.get("target_location", "dispensa")
    return {
        "item_prior_id": parse_optional_int(form.get("item_prior_id")),
        "name": clean_text(form.get("name")),
        "category": "Altro",
        "typical_quantity": quantity,
        "typical_unit": unit,
        "typical_shelf_life_days": None,
        "default_location": target_location,
        "picture": "",
        "prior_notes": "",
        "quantity": quantity,
        "unit": unit,
        "target_location": target_location,
        "notes": clean_text(form.get("notes")),
    }


def parse_receipt_rows(receipt_text: str) -> list[dict[str, Any]]:
    rows = []
    inside_table = False
    line_id = 0

    for raw_line in receipt_text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue

        normalized = normalize_match_text(line)
        if not inside_table:
            if "vendita" in normalized and "prestazione" in normalized:
                inside_table = True
            continue

        if normalized.startswith("subtotale"):
            break
        if is_receipt_header_line(normalized):
            continue

        parsed = parse_receipt_product_line(line)
        if parsed:
            parsed["id"] = str(line_id)
            rows.append(parsed)
            line_id += 1

    return rows


def is_receipt_header_line(normalized_line: str) -> bool:
    if not normalized_line:
        return True
    header_words = {"descrizione", "iva", "prezzo", "totale", "importo"}
    return len(set(normalized_line.split()) & header_words) >= 2


def parse_receipt_product_line(line: str) -> dict[str, Any] | None:
    match = re.search(r"(?P<price>[0-9]+(?:[.,][0-9]{2}))\s*$", line)
    if not match:
        return None

    price = parse_receipt_price(match.group("price"))
    if price is None:
        return None

    before_price = line[: match.start()].strip()
    if not before_price:
        return None

    tokens = before_price.split()
    if tokens and re.fullmatch(r"(?:\d{1,2}%?|[A-Z])", tokens[-1], flags=re.IGNORECASE):
        tokens = tokens[:-1]
    description = " ".join(tokens).strip(" -")
    if not description:
        return None

    return {
        "description": description,
        "price": price,
    }


def classify_receipt_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    priors = [dict(row) for row in list_item_prior_options()]
    matched = []
    unmatched = []

    for row in rows:
        prior, score = match_receipt_row_to_prior(row["description"], priors)
        if prior and score >= 0.64:
            quantity = default_prior_quantity(prior)
            unit = prior.get("typical_unit") or "pz"
            matched.append(
                row
                | {
                    "prior": prior,
                    "quantity": quantity,
                    "unit": unit,
                }
            )
        else:
            unmatched.append(row)
    return matched, unmatched


def match_receipt_row_to_prior(
    description: str,
    priors: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    normalized_description = normalize_match_text(description)
    best_prior = None
    best_score = 0.0

    for prior in priors:
        normalized_name = normalize_match_text(prior["name"])
        if not normalized_name:
            continue
        if normalized_name in normalized_description:
            score = 1.0
        else:
            score = SequenceMatcher(None, normalized_name, normalized_description).ratio()
        if score > best_score:
            best_prior = prior
            best_score = score

    return best_prior, best_score


def normalize_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def receipt_rows_by_id() -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in session.get("receipt_rows", [])}


def default_prior_quantity(prior: dict[str, Any] | None) -> float:
    if not prior:
        return 1
    quantity = prior.get("typical_quantity")
    return float(quantity or 1)


def quantity_adjust_step(unit: str | None, typical_quantity: float | int | None = None) -> float:
    if typical_quantity is not None:
        try:
            parsed_typical = float(typical_quantity)
        except (TypeError, ValueError):
            parsed_typical = 0
        if parsed_typical > 0:
            return parsed_typical

    normalized = clean_text(unit).casefold()
    if normalized in {"pz", "pc", "pezzo", "pezzi", "unita", "u"}:
        return 1.0
    if normalized in {"g", "gr", "grammo", "grammi", "ml"}:
        return 100.0
    if normalized in {"kg", "l", "lt"}:
        return 1.0
    return 1.0


def prior_form_data(form: Any) -> dict[str, Any]:
    picture = clean_text(form.get("picture"))
    return {
        "name": clean_text(form.get("name")),
        "category": normalize_category(form.get("category")),
        "typical_quantity": parse_optional_quantity(form.get("typical_quantity")),
        "typical_unit": clean_text(form.get("typical_unit"), "pz"),
        "typical_shelf_life_days": parse_optional_int(
            form.get("typical_shelf_life_days")
        ),
        "default_location": form.get("default_location", "dispensa"),
        "picture": picture,
        "picture_source": clean_text(form.get("picture_source"), "manuale" if picture else ""),
        "source_product_url": clean_text(form.get("source_product_url")),
        "notes": clean_text(form.get("notes")),
    }


def validate_inventory_data(data: dict[str, Any]) -> list[str]:
    errors = validate_prior_data(data)
    if data["quantity"] <= 0:
        errors.append("La quantita' deve essere maggiore di zero.")
    if data["location"] not in LOCATIONS:
        errors.append("Scegli frigo o dispensa.")
    return errors


def validate_shopping_data(data: dict[str, Any]) -> list[str]:
    errors = validate_prior_data(data)
    if data["quantity"] <= 0:
        errors.append("La quantita' deve essere maggiore di zero.")
    if data["target_location"] not in LOCATIONS:
        errors.append("Scegli dove andra' riposto il prodotto.")
    return errors


def validate_prior_data(data: dict[str, Any]) -> list[str]:
    errors = []
    if not data["name"]:
        errors.append("Il nome del prodotto e' obbligatorio.")
    if data.get("category") and data["category"] not in CATEGORIES:
        errors.append("Scegli una categoria tra quelle disponibili.")
    if data.get("typical_quantity") is not None and data["typical_quantity"] <= 0:
        errors.append("La quantita' tipica deve essere maggiore di zero.")
    if data.get("default_location") and data["default_location"] not in LOCATIONS:
        errors.append("La destinazione predefinita non e' valida.")
    return errors


def seed_default_priors() -> None:
    for item in DEFAULT_PRIOR_ITEMS:
        ensure_item_prior(
            {
                "name": item["name"],
                "category": item["category"],
                "typical_quantity": item["typical_quantity"],
                "typical_unit": item["typical_unit"],
                "typical_shelf_life_days": item["typical_shelf_life_days"],
                "default_location": item["default_location"],
                "picture": "",
                "prior_notes": "",
            }
        )


def ensure_item_prior(
    data: dict[str, Any],
    existing_prior_id: int | None = None,
    fetch_picture: bool = True,
    update_existing: bool = True,
) -> int:
    supabase = get_supabase()
    name = data["name"]
    prior = None
    if existing_prior_id:
        selected_prior = get_item_prior(existing_prior_id)
        if selected_prior and selected_prior["name"].casefold() == name.casefold():
            prior = selected_prior
    if not prior:
        response = supabase.table("item_prior").select("*").ilike("name", name).limit(1).execute()
        prior = response.data[0] if response.data else None

    if prior:
        if not update_existing:
            return int(prior["id"])
        merged = merge_prior_data(prior, data)
        if not merged.get("picture") and fetch_picture:
            food_profile = fetch_public_food_profile(merged["name"], merged.get("category"))
            merged = merge_external_prior_data(merged, food_profile)
        update_item_prior(prior["id"], merged)
        return int(prior["id"])

    prior_data = {
        "name": name,
        "category": normalize_category(data.get("category")),
        "typical_quantity": data.get("typical_quantity"),
        "typical_unit": data.get("typical_unit") or data.get("unit") or "pz",
        "typical_shelf_life_days": data.get("typical_shelf_life_days"),
        "default_location": data.get("default_location")
        or data.get("location")
        or data.get("target_location")
        or "dispensa",
        "picture": data.get("picture") or "",
        "picture_source": "manuale" if data.get("picture") else "",
        "source_product_url": "",
        "notes": data.get("prior_notes") or data.get("notes") or "",
    }
    if not prior_data["picture"] and fetch_picture:
        food_profile = fetch_public_food_profile(name, prior_data.get("category"))
        prior_data = merge_external_prior_data(prior_data, food_profile)

    payload = {
        "name": prior_data["name"],
        "category": prior_data.get("category"),
        "typical_quantity": prior_data.get("typical_quantity"),
        "typical_unit": prior_data.get("typical_unit"),
        "typical_shelf_life_days": prior_data.get("typical_shelf_life_days"),
        "default_location": prior_data.get("default_location"),
        "picture": prior_data.get("picture"),
        "picture_source": prior_data.get("picture_source"),
        "source_product_url": prior_data.get("source_product_url"),
        "notes": prior_data.get("notes"),
        "updated_at": utc_now(),
    }
    response = supabase.table("item_prior").insert(payload).execute()
    if not response.data:
        raise RuntimeError("Inserimento prior non riuscito.")
    return int(response.data[0]["id"])


def merge_prior_data(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": incoming.get("name") or current.get("name"),
        "category": incoming.get("category") or current.get("category"),
        "typical_quantity": incoming.get("typical_quantity") or current.get("typical_quantity"),
        "typical_unit": incoming.get("typical_unit") or current.get("typical_unit"),
        "typical_shelf_life_days": incoming.get("typical_shelf_life_days")
        or current.get("typical_shelf_life_days"),
        "default_location": incoming.get("default_location") or current.get("default_location"),
        "picture": incoming.get("picture") or current.get("picture"),
        "picture_source": "manuale"
        if incoming.get("picture")
        else current.get("picture_source"),
        "source_product_url": current.get("source_product_url"),
        "notes": incoming.get("prior_notes") or current.get("notes"),
    }


def merge_external_prior_data(
    prior_data: dict[str, Any],
    food_profile: dict[str, Any],
) -> dict[str, Any]:
    if not food_profile:
        return prior_data
    merged = prior_data.copy()
    if not merged.get("category") and food_profile.get("category"):
        merged["category"] = food_profile["category"]
    if not merged.get("typical_quantity") and food_profile.get("typical_quantity"):
        merged["typical_quantity"] = food_profile["typical_quantity"]
    if not merged.get("typical_unit") and food_profile.get("typical_unit"):
        merged["typical_unit"] = food_profile["typical_unit"]
    if not merged.get("picture") and food_profile.get("picture"):
        merged["picture"] = food_profile["picture"]
        merged["picture_source"] = food_profile.get("picture_source") or "Open Food Facts"
    if food_profile.get("source_product_url"):
        merged["source_product_url"] = food_profile["source_product_url"]
    return merged


def update_item_prior(prior_id: int, data: dict[str, Any]) -> None:
    current = get_item_prior(prior_id)
    if current:
        current_data = current
    else:
        current_data = {}

    def value(key: str) -> Any:
        return data[key] if key in data else current_data.get(key)

    payload = {
        "name": value("name"),
        "category": value("category"),
        "typical_quantity": value("typical_quantity"),
        "typical_unit": value("typical_unit"),
        "typical_shelf_life_days": value("typical_shelf_life_days"),
        "default_location": value("default_location"),
        "picture": value("picture"),
        "picture_source": value("picture_source"),
        "source_product_url": value("source_product_url"),
        "notes": value("notes"),
        "updated_at": utc_now(),
    }
    get_supabase().table("item_prior").update(payload).eq("id", prior_id).execute()


def get_item_prior(prior_id: int) -> dict[str, Any] | None:
    response = get_supabase().table("item_prior").select("*").eq("id", prior_id).limit(1).execute()
    return response.data[0] if response.data else None


def list_item_priors(query: str = "") -> list[dict[str, Any]]:
    supabase = get_supabase()
    priors_response = supabase.table("item_prior").select("*").execute()
    priors = priors_response.data or []

    if query:
        needle = query.casefold()
        priors = [
            row
            for row in priors
            if needle in (row.get("name") or "").casefold()
            or needle in (row.get("category") or "").casefold()
        ]

    inventory_rows = supabase.table("inventory_items").select("item_prior_id").execute().data or []
    shopping_rows = supabase.table("shopping_items").select("item_prior_id").execute().data or []
    history_rows = supabase.table("items_history").select("item_prior_id").execute().data or []

    inventory_count: dict[int, int] = {}
    shopping_count: dict[int, int] = {}
    history_count: dict[int, int] = {}

    for row in inventory_rows:
        prior_id = int(row["item_prior_id"])
        inventory_count[prior_id] = inventory_count.get(prior_id, 0) + 1
    for row in shopping_rows:
        prior_id = int(row["item_prior_id"])
        shopping_count[prior_id] = shopping_count.get(prior_id, 0) + 1
    for row in history_rows:
        prior_id = int(row["item_prior_id"])
        history_count[prior_id] = history_count.get(prior_id, 0) + 1

    result = []
    for prior in priors:
        prior_id = int(prior["id"])
        result.append(
            prior
            | {
                "inventory_count": inventory_count.get(prior_id, 0),
                "shopping_count": shopping_count.get(prior_id, 0),
                "history_count": history_count.get(prior_id, 0),
            }
        )
    return sorted(result, key=lambda row: (row.get("name") or "").casefold())


def list_item_prior_options() -> list[dict[str, Any]]:
    response = get_supabase().table("item_prior").select(
        "id,name,category,typical_quantity,typical_unit,typical_shelf_life_days,default_location,picture,notes"
    ).execute()
    return sorted(response.data or [], key=lambda row: (row.get("name") or "").casefold())


def fetch_public_food_profile(name: str, category: str | None = None) -> dict[str, Any]:
    if not current_app_config("ENABLE_FOOD_IMAGE_LOOKUP"):
        return {}

    wikidata_profile = fetch_wikidata_food_profile(name, category)
    if wikidata_profile:
        return wikidata_profile

    search_terms = " ".join(part for part in (name, category or "") if part).strip()
    if not search_terms:
        return {}

    params = {
        "search_terms": search_terms,
        "page_size": 5,
        "fields": "product_name,generic_name,categories,quantity,image_front_url,image_url,url",
        "lc": "it",
    }
    url = f"{OPEN_FOOD_FACTS_SEARCH_URL}?{urlencode(params)}"
    request = Request(
        url,
        headers={"User-Agent": current_app_config("OPEN_FOOD_FACTS_USER_AGENT")},
    )

    try:
        with urlopen(request, timeout=current_app_config("OPEN_FOOD_FACTS_TIMEOUT")) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return fallback_ingredient_profile(name)

    for product in payload.get("products", []):
        picture = product.get("image_front_url") or product.get("image_url")
        if not picture:
            continue
        quantity, unit = parse_quantity_label(product.get("quantity"))
        return {
            "category": first_category(product.get("categories")),
            "typical_quantity": quantity,
            "typical_unit": unit,
            "picture": picture,
            "source_product_url": product.get("url") or "",
        }
    return fallback_ingredient_profile(name)


def fetch_wikidata_food_profile(name: str, category: str | None = None) -> dict[str, Any]:
    search_terms = " ".join(part for part in (name, category or "") if part).strip()
    if not search_terms:
        return {}

    search_params = {
        "action": "wbsearchentities",
        "search": search_terms,
        "language": "it",
        "type": "item",
        "limit": 5,
        "format": "json",
    }
    search_url = f"{WIKIDATA_SEARCH_URL}?{urlencode(search_params)}"
    search_request = Request(
        search_url,
        headers={"User-Agent": current_app_config("OPEN_FOOD_FACTS_USER_AGENT")},
    )

    try:
        with urlopen(search_request, timeout=current_app_config("OPEN_FOOD_FACTS_TIMEOUT")) as response:
            search_payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {}

    entity_ids = [item.get("id") for item in search_payload.get("search", []) if item.get("id")]
    if not entity_ids:
        return {}

    entity_params = {
        "action": "wbgetentities",
        "ids": "|".join(entity_ids),
        "props": "claims",
        "format": "json",
    }
    entity_url = f"{WIKIDATA_SEARCH_URL}?{urlencode(entity_params)}"
    entity_request = Request(
        entity_url,
        headers={"User-Agent": current_app_config("OPEN_FOOD_FACTS_USER_AGENT")},
    )

    try:
        with urlopen(entity_request, timeout=current_app_config("OPEN_FOOD_FACTS_TIMEOUT")) as response:
            entity_payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {}

    entities = entity_payload.get("entities", {})
    for entity_id in entity_ids:
        entity = entities.get(entity_id) or {}
        image_filename = extract_wikidata_image_filename(entity)
        if not image_filename:
            continue
        encoded_filename = quote(image_filename)
        return {
            "picture": f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded_filename}",
            "picture_source": "Wikimedia Commons",
            "source_product_url": f"https://www.wikidata.org/wiki/{entity_id}",
        }

    return {}


def extract_wikidata_image_filename(entity: dict[str, Any]) -> str | None:
    claims = entity.get("claims") or {}
    image_claims = claims.get("P18") or []
    for claim in image_claims:
        mainsnak = claim.get("mainsnak") or {}
        datavalue = mainsnak.get("datavalue") or {}
        value = datavalue.get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def fallback_ingredient_profile(name: str) -> dict[str, Any]:
    ingredient = INGREDIENT_IMAGE_FALLBACKS.get(name.strip().lower())
    if not ingredient:
        return {}
    return {
        "picture": f"https://www.themealdb.com/images/ingredients/{ingredient}.png",
        "picture_source": "TheMealDB",
        "source_product_url": f"https://www.themealdb.com/ingredient/{ingredient}",
    }


def parse_quantity_label(value: str | None) -> tuple[float | None, str | None]:
    if not value:
        return None, None
    match = re.search(r"([0-9]+(?:[,.][0-9]+)?)\s*([A-Za-z]+)?", value)
    if not match:
        return None, None
    quantity = parse_optional_quantity(match.group(1))
    unit = match.group(2) or None
    return quantity, unit


def first_category(value: str | None) -> str:
    if not value:
        return ""
    return value.split(",")[0].strip()


def load_item_prior_map(prior_ids: list[int]) -> dict[int, dict[str, Any]]:
    unique_ids = sorted({int(prior_id) for prior_id in prior_ids if prior_id})
    if not unique_ids:
        return {}
    response = get_supabase().table("item_prior").select("*").in_("id", unique_ids).execute()
    return {int(row["id"]): row for row in (response.data or [])}


def merge_item_with_prior(item: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    prior = prior or {}
    return item | {
        "name": prior.get("name", ""),
        "category": prior.get("category", ""),
        "typical_quantity": prior.get("typical_quantity"),
        "typical_unit": prior.get("typical_unit"),
        "typical_shelf_life_days": prior.get("typical_shelf_life_days"),
        "default_location": prior.get("default_location"),
        "picture": prior.get("picture"),
        "picture_source": prior.get("picture_source"),
        "source_product_url": prior.get("source_product_url"),
        "prior_notes": prior.get("notes", ""),
    }


def list_inventory_items(location: str | None = None) -> list[dict[str, Any]]:
    query = get_supabase().table("inventory_items").select("*")
    if location:
        query = query.eq("location", location)
    inventory_items = query.execute().data or []
    prior_map = load_item_prior_map([int(item["item_prior_id"]) for item in inventory_items])
    merged = [merge_item_with_prior(item, prior_map.get(int(item["item_prior_id"]))) for item in inventory_items]

    return sorted(
        merged,
        key=lambda row: (
            row.get("location") or "",
            row.get("expiry_date") is None,
            row.get("expiry_date") or "",
            (row.get("name") or "").casefold(),
        ),
    )


def get_inventory_item(item_id: int) -> dict[str, Any] | None:
    response = get_supabase().table("inventory_items").select("*").eq("id", item_id).limit(1).execute()
    if not response.data:
        return None
    item = response.data[0]
    prior = get_item_prior(int(item["item_prior_id"]))
    return merge_item_with_prior(item, prior)


def create_inventory_item(item_prior_id: int, data: dict[str, Any]) -> int:
    payload = {
        "item_prior_id": item_prior_id,
        "quantity": data["quantity"],
        "unit": data["unit"],
        "location": data["location"],
        "expiry_date": data.get("expiry_date"),
        "expiry_estimated": int(data.get("expiry_estimated") or 0),
        "notes": data.get("notes"),
        "updated_at": utc_now(),
    }
    response = get_supabase().table("inventory_items").insert(payload).execute()
    if not response.data:
        raise RuntimeError("Inserimento inventario non riuscito.")
    return int(response.data[0]["id"])


def update_inventory_item(item_id: int, item_prior_id: int, data: dict[str, Any]) -> None:
    payload = {
        "item_prior_id": item_prior_id,
        "quantity": data["quantity"],
        "unit": data["unit"],
        "location": data["location"],
        "expiry_date": data.get("expiry_date"),
        "expiry_estimated": int(data.get("expiry_estimated") or 0),
        "notes": data.get("notes"),
        "updated_at": utc_now(),
    }
    get_supabase().table("inventory_items").update(payload).eq("id", item_id).execute()


def delete_inventory_item(item_id: int) -> None:
    get_supabase().table("inventory_items").delete().eq("id", item_id).execute()


def add_or_increment_shopping_item(
    item_prior_id: int,
    quantity: float,
    unit: str,
    target_location: str,
    notes: str | None = None,
) -> int:
    supabase = get_supabase()
    existing_response = (
        supabase.table("shopping_items")
        .select("*")
        .eq("item_prior_id", item_prior_id)
        .eq("unit", unit)
        .eq("target_location", target_location)
        .limit(1)
        .execute()
    )
    existing = existing_response.data[0] if existing_response.data else None

    if existing:
        existing_notes = existing.get("notes") or ""
        if not existing_notes:
            merged_notes = notes or ""
        elif not notes:
            merged_notes = existing_notes
        else:
            merged_notes = f"{existing_notes}; {notes}"
        supabase.table("shopping_items").update(
            {
                "quantity": float(existing.get("quantity") or 0) + quantity,
                "notes": merged_notes,
            }
        ).eq("id", existing["id"]).execute()
        return int(existing["id"])

    response = supabase.table("shopping_items").insert(
        {
            "item_prior_id": item_prior_id,
            "quantity": quantity,
            "unit": unit,
            "target_location": target_location,
            "notes": notes,
        }
    ).execute()
    if not response.data:
        raise RuntimeError("Inserimento shopping non riuscito.")
    return int(response.data[0]["id"])


def list_shopping_items() -> list[dict[str, Any]]:
    items = get_supabase().table("shopping_items").select("*").execute().data or []
    prior_map = load_item_prior_map([int(item["item_prior_id"]) for item in items])
    merged = [merge_item_with_prior(item, prior_map.get(int(item["item_prior_id"]))) for item in items]
    return sorted(merged, key=lambda row: ((row.get("target_location") or ""), (row.get("name") or "").casefold()))


def get_shopping_item(item_id: int) -> dict[str, Any] | None:
    response = get_supabase().table("shopping_items").select("*").eq("id", item_id).limit(1).execute()
    if not response.data:
        return None
    item = response.data[0]
    prior = get_item_prior(int(item["item_prior_id"]))
    return merge_item_with_prior(item, prior)


def delete_shopping_item(item_id: int) -> None:
    get_supabase().table("shopping_items").delete().eq("id", item_id).execute()


def add_receipt_item_to_kitchen(
    prior_id: int,
    quantity: float,
    unit: str,
    cost: float | None,
    description: str,
) -> int:
    prior = get_item_prior(prior_id)
    if not prior:
        raise ValueError("Prior non trovato.")

    expiry_date, expiry_estimated = resolve_expiry(
        None,
        prior["typical_shelf_life_days"],
    )
    inventory_item_id = create_inventory_item(
        prior_id,
        {
            "quantity": quantity,
            "unit": unit,
            "location": prior["default_location"] or "dispensa",
            "expiry_date": expiry_date,
            "expiry_estimated": expiry_estimated,
            "notes": f"Scontrino: {description}",
        },
    )
    create_history_item(
        {
            "item_prior_id": prior_id,
            "inventory_item_id": inventory_item_id,
            "purchased_at": utc_now(),
            "quantity": quantity,
            "unit": unit,
            "cost": cost,
            "target_location": prior["default_location"] or "dispensa",
            "notes": f"Scontrino: {description}",
        }
    )
    return inventory_item_id


def create_history_item(data: dict[str, Any]) -> int:
    response = get_supabase().table("items_history").insert(
        {
            "item_prior_id": data["item_prior_id"],
            "inventory_item_id": data.get("inventory_item_id"),
            "purchased_at": data["purchased_at"],
            "quantity": data["quantity"],
            "unit": data["unit"],
            "cost": data.get("cost"),
            "target_location": data.get("target_location"),
            "notes": data.get("notes"),
        }
    ).execute()
    if not response.data:
        raise RuntimeError("Inserimento storico non riuscito.")
    return int(response.data[0]["id"])


def list_history_items() -> list[dict[str, Any]]:
    history = get_supabase().table("items_history").select("*").execute().data or []
    prior_map = load_item_prior_map([int(item["item_prior_id"]) for item in history])
    merged = []
    for item in history:
        prior = prior_map.get(int(item["item_prior_id"])) or {}
        merged.append(
            item
            | {
                "name": prior.get("name", ""),
                "category": prior.get("category", ""),
                "picture": prior.get("picture"),
            }
        )
    return sorted(
        merged,
        key=lambda row: (
            row.get("purchased_at") or "",
            int(row.get("id") or 0),
        ),
        reverse=True,
    )


def load_dashboard_stats() -> dict[str, Any]:
    supabase = get_supabase()
    today_iso = date.today().isoformat()
    soon_iso = (date.today() + timedelta(days=3)).isoformat()
    inventory_rows = supabase.table("inventory_items").select("id,location,expiry_date").execute().data or []
    shopping_count = len(supabase.table("shopping_items").select("id").execute().data or [])
    prior_count = len(supabase.table("item_prior").select("id").execute().data or [])

    inventory_count = len(inventory_rows)
    fridge_count = sum(1 for row in inventory_rows if row.get("location") == "frigo")
    pantry_count = sum(1 for row in inventory_rows if row.get("location") == "dispensa")
    expired_count = sum(
        1
        for row in inventory_rows
        if row.get("expiry_date") is not None and str(row["expiry_date"]) < today_iso
    )
    expiring_count = sum(
        1
        for row in inventory_rows
        if row.get("expiry_date") is not None and today_iso <= str(row["expiry_date"]) <= soon_iso
    )
    return {
        "inventory_count": inventory_count,
        "shopping_count": shopping_count,
        "prior_count": prior_count,
        "fridge_count": fridge_count,
        "pantry_count": pantry_count,
        "expired_count": expired_count,
        "expiring_count": expiring_count,
    }


def load_history_stats() -> dict[str, Any]:
    history_items = get_supabase().table("items_history").select("cost").execute().data or []
    return {
        "total_purchases": len(history_items),
        "total_cost": sum(float(row.get("cost") or 0) for row in history_items),
    }


def load_settings_stats() -> dict[str, Any]:
    supabase = get_supabase()
    return {
        "prior_count": len(supabase.table("item_prior").select("id").execute().data or []),
        "inventory_count": len(supabase.table("inventory_items").select("id").execute().data or []),
        "shopping_count": len(supabase.table("shopping_items").select("id").execute().data or []),
        "history_count": len(supabase.table("items_history").select("id").execute().data or []),
    }


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
