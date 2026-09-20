from __future__ import annotations

import json
import os
import re
from html import escape as html_escape
from difflib import SequenceMatcher
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from google import genai
from markupsafe import Markup

from flask import (
    Flask,
    flash,
    g,
    jsonify,
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
    "freezer": "Freezer",
}

UNITS = ["pz", "g", "ml", "l", "kg"]

CATEGORIES = [
    "Verdura",
    "Frutta",
    "Latticini",
    "Formaggi",
    "Carne",
    "Pesce",
    "Uova",
    "Cereali",
    "Legumi",
    "Pasta",
    "Dolci",
    "Bibite",
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

REQUIRED_TABLES = [
    "item_prior",
    "inventory_items",
    "inventory_quantity_changes",
    "shopping_items",
    "items_history",
    "recipes",
    "recipe_ingredients",
    "meals",
    "meal_recipes",
    "recipe_history",
    "meal_consumptions",
    "meal_defaults",
    "meal_default_recipes",
]

MEAL_TYPES = {
    "colazione": "Colazione",
    "pranzo": "Pranzo",
    "cena": "Cena",
}

RECIPE_MEAL_TYPES = {
    "antipasto": "Antipasto",
    "primo": "Primo",
    "secondo": "Secondo",
    "contorno": "Contorno",
    "piatto_unico": "Piatto unico",
    "colazione": "Colazione",
    "merenda": "Merenda",
    "dolce": "Dolce",
    "altro": "Altro",
}

TRUTHY_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY_VALUES


def should_run_startup_tasks() -> bool:
    # On Vercel we avoid startup-side schema checks and seeding on cold starts.
    default = not env_flag("VERCEL", False)
    return env_flag("RUN_STARTUP_TASKS", default)


def create_app(
    test_config: dict[str, Any] | None = None,
    *,
    startup_checks: bool | None = None,
) -> Flask:
    if startup_checks is None:
        startup_checks = should_run_startup_tasks()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        ENABLE_FOOD_IMAGE_LOOKUP=env_flag("ENABLE_FOOD_IMAGE_LOOKUP", True),
        SEED_DEFAULT_PRIORS=env_flag("SEED_DEFAULT_PRIORS", not env_flag("VERCEL", False)),
        OPEN_FOOD_FACTS_USER_AGENT="KitchenPlanner/0.1 (local development)",
        OPEN_FOOD_FACTS_TIMEOUT=4,
    )

    if test_config:
        app.config.update(test_config)

    register_template_helpers(app)
    register_routes(app)

    if startup_checks:
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


def _format_qty(value: float | int | None) -> str:
    if value in (None, ""):
        return ""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def register_template_helpers(app: Flask) -> None:
    @app.template_filter("qty")
    def qty(value: float | int | None) -> str:
        return _format_qty(value)

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

    @app.template_filter("markdown")
    def markdown_filter(value: str | None) -> Markup:
        """Render recipe notes as Markdown, with raw HTML disabled."""
        text = value or ""
        try:
            import markdown
            import bleach
            rendered = markdown.markdown(text, extensions=["extra", "nl2br"])
            rendered = bleach.clean(
                rendered,
                tags=["p", "br", "strong", "em", "del", "h1", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "code", "pre", "a"],
                attributes={"a": ["href", "title"]},
                protocols=["http", "https", "mailto"],
                strip=True,
            )
            return Markup(rendered)
        except ImportError:
            # Keep Markdown notes useful while dependencies are being installed.
            # The normal path above provides the complete Markdown implementation.
            blocks = []
            list_tag = None

            def close_list() -> None:
                nonlocal list_tag
                if list_tag:
                    blocks.append(f"</{list_tag}>")
                    list_tag = None

            def inline_markdown(line: str) -> str:
                rendered = html_escape(line, quote=True)
                rendered = re.sub(r"`([^`]+)`", r"<code>\1</code>", rendered)
                rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
                rendered = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", rendered)
                rendered = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", rendered)
                rendered = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<em>\1</em>", rendered)
                return rendered

            for line in text.splitlines():
                heading = re.match(r"^\s*(#{1,4})\s+(.+?)\s*$", line)
                unordered = re.match(r"^\s*[-*+]\s+(.+?)\s*$", line)
                ordered = re.match(r"^\s*\d+[.)]\s+(.+?)\s*$", line)
                if heading:
                    close_list()
                    level = len(heading.group(1))
                    blocks.append(f"<h{level}>{inline_markdown(heading.group(2))}</h{level}>")
                elif unordered or ordered:
                    tag = "ul" if unordered else "ol"
                    if list_tag != tag:
                        close_list()
                        list_tag = tag
                        blocks.append(f"<{tag}>")
                    blocks.append(f"<li>{inline_markdown((unordered or ordered).group(1))}</li>")
                elif line.strip():
                    close_list()
                    blocks.append(f"<p>{inline_markdown(line)}</p>")
                else:
                    close_list()
            close_list()
            return Markup("".join(blocks))

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "locations": LOCATIONS,
            "categories": CATEGORIES,
            "recipe_meal_types": RECIPE_MEAL_TYPES,
            "units": UNITS,
            "today": date.today().isoformat(),
            "now_local_value": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        }


def redirect_inventory_context():
    """Return to the inventory section from which a destructive action started."""
    location = request.args.get("location", "").strip()
    view = request.args.get("view", "").strip().lower()
    params = {}
    if location in LOCATIONS:
        params["location"] = location
    if view in {"grid", "list"}:
        params["view"] = view
    return redirect(url_for("index", **params))


def register_routes(app: Flask) -> None:
    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}, 200

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

        history_resp = (
            get_supabase()
            .table("items_history")
            .select("purchased_at")
            .eq("inventory_item_id", item_id)
            .limit(1)
            .execute()
        )
        purchased_at = history_resp.data[0]["purchased_at"] if history_resp.data else None
        return render_template(
            "inventory_form.html",
            item=dict(item),
            mode="edit",
            prior_options=list_item_prior_options(),
            purchased_at=purchased_at,
        )

    @app.post("/inventory/<int:item_id>/finish")
    def finish_inventory_item(item_id: int):
        item = get_inventory_item(item_id)
        if not item:
            flash("Prodotto non trovato.", "error")
            return redirect(url_for("index"))

        # If another instance of the same prior is still available, the product
        # is not finished from the household's point of view: do not replenish it.
        other_inventory = (
            get_supabase().table("inventory_items")
            .select("id")
            .eq("item_prior_id", item["item_prior_id"])
            .neq("id", item_id)
            .gt("quantity", 0)
            .limit(1)
            .execute()
        ).data
        existing_shopping = (
            get_supabase().table("shopping_items")
            .select("id")
            .eq("item_prior_id", item["item_prior_id"])
            .limit(1)
            .execute()
        ).data
        if not other_inventory and not existing_shopping:
            add_or_increment_shopping_item(
                item_prior_id=item["item_prior_id"],
                quantity=max(float(item["quantity"] or 1), 1),
                unit=item["unit"],
                target_location=item["location"],
                notes=item["notes"],
            )
        delete_inventory_item(item_id)
        flash(
            "Prodotto finito: " + ("la lista della spesa è stata aggiornata." if not other_inventory and not existing_shopping else "non serve aggiungerlo alla lista della spesa."),
            "success",
        )
        return redirect_inventory_context()

    @app.post("/inventory/<int:item_id>/prepare")
    def prepare_inventory_item(item_id: int):
        item = get_inventory_item(item_id)
        if not item:
            flash("Prodotto non trovato.", "error")
            return redirect(url_for("index"))

        status = clean_text(request.form.get("preparation_status")).lower()
        if status not in {"cotto", "aperto"}:
            flash("Modalità non valida.", "error")
            return redirect_inventory_context()
        try:
            quantity = float(str(request.form.get("quantity", "")).replace(",", "."))
        except (TypeError, ValueError):
            quantity = 0
        available = float(item.get("quantity") or 0)
        if quantity <= 0 or quantity > available:
            flash("La quantità deve essere positiva e non superiore a quella disponibile.", "error")
            return redirect_inventory_context()

        create_inventory_item(
            int(item["item_prior_id"]),
            {
                "quantity": quantity,
                "unit": item["unit"],
                "location": "frigo",
                "expiry_date": (date.today() + timedelta(days=4 if status == "cotto" else 5)).isoformat(),
                "expiry_estimated": 0,
                "notes": item.get("notes") or "",
                "preparation_status": status,
            },
        )
        remaining = available - quantity
        if remaining <= 0.000001:
            delete_inventory_item(item_id)
        else:
            update_inventory_item(item_id, int(item["item_prior_id"]), item | {
                "quantity": remaining,
                "preparation_status": item.get("preparation_status") or "none",
            })
        flash(f"Prodotto segnato come {status}: spostato in frigo.", "success")
        return redirect_inventory_context()

    @app.post("/inventory/<int:item_id>/delete")
    def delete_inventory(item_id: int):
        delete_inventory_item(item_id)
        flash("Prodotto eliminato dall'inventario.", "success")
        return redirect_inventory_context()

    @app.post("/inventory/<int:item_id>/adjust")
    def adjust_inventory_quantity(item_id: int):
        is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        item = get_inventory_item(item_id)
        if not item:
            if is_xhr:
                return jsonify({"ok": False, "error": "Prodotto non trovato."}), 404
            flash("Prodotto non trovato.", "error")
            return redirect(url_for("index"))

        direction = clean_text(request.form.get("direction")).lower()
        if direction not in {"inc", "dec"}:
            if is_xhr:
                return jsonify({"ok": False, "error": "Azione quantita' non valida."}), 400
            flash("Azione quantita' non valida.", "error")
            return redirect(url_for("index"))

        current_quantity = float(item.get("quantity") or 0)
        new_quantity, new_unit = adjust_quantity_with_unit(
            current_quantity,
            item.get("unit"),
            direction,
        )

        if new_quantity <= 0:
            if is_xhr:
                return jsonify({"ok": False, "error": "La quantita' non puo' scendere sotto zero."}), 400
            flash("La quantita' non puo' scendere sotto zero.", "error")
            return redirect(url_for("index"))

        payload = {
            "quantity": new_quantity,
            "unit": new_unit,
            "location": item["location"],
            "preparation_status": item.get("preparation_status") or "none",
            "expiry_date": item.get("expiry_date"),
            "expiry_estimated": item.get("expiry_estimated") or 0,
            "notes": item.get("notes") or "",
        }
        old_unit = item.get("unit") or "pz"
        old_base, old_factor = unit_factor(old_unit)
        new_base, new_factor = unit_factor(new_unit)
        quantity_delta = new_quantity - current_quantity
        if old_base == new_base:
            quantity_delta = new_quantity - (current_quantity * old_factor / new_factor)
        update_inventory_item(
            item_id,
            int(item["item_prior_id"]),
            payload,
            quantity_delta=quantity_delta,
        )
        if is_xhr:
            today_change = get_today_quantity_change(item_id, new_unit)
            return jsonify({
                "ok": True,
                "qty_display": f"{_format_qty(new_quantity)} {new_unit}",
                "today_quantity_change": today_change,
                "today_quantity_change_display": f"{_format_qty(abs(today_change))} {new_unit}",
            })
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
        session["receipt_purchased_at"] = parse_receipt_date(receipt_text)
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
        purchased_at = session.get("receipt_purchased_at") or utc_now()

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
                purchased_at=purchased_at,
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

        purchased_at = session.get("receipt_purchased_at") or utc_now()
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
                purchased_at=purchased_at,
            )
            added_count += 1

        session.pop("receipt_rows", None)
        session.pop("receipt_purchased_at", None)
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

        error = complete_shopping_purchase(
            item,
            quantity=parse_quantity(request.form.get("quantity"), item["quantity"]),
            unit=clean_text(request.form.get("unit"), item["unit"]),
            target_location=request.form.get("target_location") or item["target_location"],
            typical_shelf_life_days=parse_optional_int(
                request.form.get("typical_shelf_life_days"),
                item["typical_shelf_life_days"],
            ),
            cost=parse_optional_money(request.form.get("cost")),
            purchased_at=parse_form_datetime(request.form.get("purchased_at")) or utc_now(),
            expiry_input=request.form.get("expiry_date"),
        )
        if error:
            flash(error, "error")
            return redirect(url_for("shopping"))

        flash("Acquisto registrato, storicizzato e spostato in inventario.", "success")
        return redirect(url_for("shopping"))

    @app.post("/shopping/complete")
    def complete_shopping_items():
        selected_ids = parse_id_list(request.form.getlist("selected_ids"))
        if not selected_ids:
            flash("Seleziona almeno un prodotto da completare.", "error")
            return redirect(url_for("shopping"))

        completed_count = 0
        for item_id in selected_ids:
            item = get_shopping_item(item_id)
            if not item:
                continue
            error = complete_shopping_purchase(
                item,
                quantity=float(item["quantity"]),
                unit=clean_text(item["unit"]),
                target_location=item["target_location"],
                typical_shelf_life_days=item["typical_shelf_life_days"],
                cost=None,
                purchased_at=utc_now(),
                expiry_input=None,
            )
            if error:
                flash(f"{item['name']}: {error}", "error")
                continue
            completed_count += 1

        if completed_count:
            flash(f"{completed_count} prodotti spostati in inventario.", "success")
        return redirect(url_for("shopping"))

    @app.post("/shopping/<int:item_id>/delete")
    def delete_shopping(item_id: int):
        delete_shopping_item(item_id)
        flash("Voce eliminata dalla lista della spesa.", "success")
        return redirect(url_for("shopping"))

    @app.post("/shopping/<int:item_id>/adjust")
    def adjust_shopping_quantity(item_id: int):
        is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        item = get_shopping_item(item_id)
        if not item:
            if is_xhr:
                return jsonify({"ok": False, "error": "Voce non trovata."}), 404
            flash("Voce della lista non trovata.", "error")
            return redirect(url_for("shopping"))

        direction = clean_text(request.form.get("direction")).lower()
        if direction not in {"inc", "dec"}:
            if is_xhr:
                return jsonify({"ok": False, "error": "Azione non valida."}), 400
            flash("Azione quantita' non valida.", "error")
            return redirect(url_for("shopping"))

        current_quantity = float(item.get("quantity") or 0)
        new_quantity, new_unit = adjust_quantity_with_unit(
            current_quantity,
            item.get("unit"),
            direction,
        )

        if new_quantity <= 0:
            if is_xhr:
                return jsonify({"ok": False, "error": "La quantita' non puo' scendere sotto zero."}), 400
            flash("La quantita' non puo' scendere sotto zero.", "error")
            return redirect(url_for("shopping"))

        update_shopping_item(item_id, new_quantity, new_unit)
        if is_xhr:
            return jsonify({
                "ok": True,
                "qty_display": f"{_format_qty(new_quantity)} {new_unit}",
            })
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

    @app.get("/meals")
    def meals_agenda():
        meals = list_meals()
        return render_template("meals_agenda.html", meals=meals)

    @app.route("/meals/weekly", methods=("GET", "POST"))
    def weekly_meal_scan():
        week_start = monday_of_week(date.today())
        if request.method == "POST":
            action = clean_text(request.form.get("action"))
            slots = weekly_slots_from_form(request.form)
            if action == "save_defaults":
                save_meal_defaults(slots)
                flash("Default settimanali salvati.", "success")
            elif action == "load_defaults":
                created = load_meal_defaults(week_start)
                flash(f"{created} pasti caricati nell'agenda della settimana.", "success")
            else:
                flash("Azione non valida.", "error")
            return redirect(url_for("weekly_meal_scan"))
        return render_template(
            "weekly_meal_scan.html",
            week_start=week_start,
            days=weekly_meal_days(week_start),
            slots=list_meal_defaults(),
            recipes=list_recipes(),
        )

    @app.get("/meals/history")
    def meals_history():
        return render_template("meals_history.html", meals=list_meal_history())

    @app.route("/meals/new", methods=("GET", "POST"))
    def new_meal():
        if request.method == "POST":
            data = meal_form_data(request.form)
            errors = validate_meal_data(data)
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template("meal_form.html", meal=data, recipes=list_recipes()), 400
            meal_id = create_meal(data)
            flash("Pasto aggiunto all'agenda.", "success")
            return redirect(url_for("meal_detail", meal_id=meal_id))
        return render_template("meal_form.html", meal=empty_meal_form(), recipes=list_recipes())

    @app.get("/meals/<int:meal_id>")
    def meal_detail(meal_id: int):
        meal = get_meal(meal_id)
        if not meal:
            flash("Pasto non trovato.", "error")
            return redirect(url_for("meals_agenda"))
        selected_ids = {int(recipe["id"]) for recipe in meal.get("recipes", [])}
        all_recipes = list_recipes()
        available_recipes = [recipe for recipe in all_recipes if int(recipe["id"]) not in selected_ids]
        return render_template(
            "meal_detail.html",
            meal=meal,
            ingredients=aggregate_meal_ingredients(meal),
            available_recipes=available_recipes,
            existing_recipe_names=[recipe["name"] for recipe in meal.get("recipes", [])],
        )

    @app.post("/meals/<int:meal_id>/recipes/add")
    def add_meal_recipe(meal_id: int):
        meal = get_meal(meal_id)
        if not meal:
            flash("Pasto non trovato.", "error")
            return redirect(url_for("meals_agenda"))

        recipe_id = parse_optional_int(request.form.get("recipe_id"))
        if not recipe_id or not get_recipe(recipe_id):
            flash("Seleziona un piatto valido.", "error")
            return redirect(url_for("meal_detail", meal_id=meal_id))

        if not add_recipe_to_meal(meal_id, recipe_id):
            flash("Questo piatto è già associato al meal.", "error")
            return redirect(url_for("meal_detail", meal_id=meal_id))
        flash("Piatto aggiunto al meal.", "success")
        return redirect(url_for("meal_detail", meal_id=meal_id))

    @app.post("/meals/<int:meal_id>/recipes/<int:recipe_id>/remove")
    def remove_meal_recipe(meal_id: int, recipe_id: int):
        meal = get_meal(meal_id)
        if not meal:
            flash("Pasto non trovato.", "error")
            return redirect(url_for("meals_agenda"))
        if not any(int(recipe["id"]) == recipe_id for recipe in meal.get("recipes", [])):
            flash("Piatto non associato a questo meal.", "error")
            return redirect(url_for("meal_detail", meal_id=meal_id))

        supabase = get_supabase()
        supabase.table("meal_recipes").delete().eq("meal_id", meal_id).eq("recipe_id", recipe_id).execute()
        reorder_meal_recipes(meal_id)
        flash("Piatto rimosso dal meal.", "success")
        return redirect(url_for("meal_detail", meal_id=meal_id))

    @app.post("/meals/<int:meal_id>/recipes/<int:recipe_id>/move/<direction>")
    def move_meal_recipe(meal_id: int, recipe_id: int, direction: str):
        if direction not in {"up", "down"}:
            flash("Ordine non valido.", "error")
            return redirect(url_for("meal_detail", meal_id=meal_id))
        meal = get_meal(meal_id)
        if not meal:
            flash("Pasto non trovato.", "error")
            return redirect(url_for("meals_agenda"))

        links = get_meal_recipe_links(meal_id)
        index = next((index for index, link in enumerate(links) if int(link["recipe_id"]) == recipe_id), None)
        if index is None:
            flash("Piatto non associato a questo meal.", "error")
            return redirect(url_for("meal_detail", meal_id=meal_id))
        target = index - 1 if direction == "up" else index + 1
        if 0 <= target < len(links):
            links[index], links[target] = links[target], links[index]
            supabase = get_supabase()
            for sort_order, link in enumerate(links):
                supabase.table("meal_recipes").update({"sort_order": sort_order}).eq("id", link["id"]).execute()
        return redirect(url_for("meal_detail", meal_id=meal_id))

    @app.post("/meals/<int:meal_id>/delete")
    def delete_meal(meal_id: int):
        meal = get_meal(meal_id)
        if not meal:
            flash("Pasto non trovato.", "error")
            return redirect(url_for("meals_agenda"))
        delete_meal_record(meal_id)
        flash("Pasto eliminato dall'agenda.", "success")
        return redirect(url_for("meals_agenda"))

    @app.post("/meals/<int:meal_id>/complete")
    def complete_meal(meal_id: int):
        meal = get_meal(meal_id)
        if not meal:
            flash("Pasto non trovato.", "error")
            return redirect(url_for("meals_agenda"))
        if meal.get("completed_at"):
            flash("Questo pasto è già nello storico.", "error")
            return redirect(url_for("meal_detail", meal_id=meal_id))
        supabase = get_supabase()
        consume_meal_ingredients(meal)
        for recipe in meal.get("recipes", []):
            supabase.table("recipe_history").upsert({"recipe_id": recipe["id"], "cooked_on": meal["meal_date"]}, on_conflict="recipe_id,cooked_on").execute()
        supabase.table("meals").update({"completed_at": utc_now(), "updated_at": utc_now()}).eq("id", meal_id).execute()
        flash("Pasto segnato come preparato e aggiunto allo storico.", "success")
        return redirect(url_for("meals_history"))

    @app.post("/meals/<int:meal_id>/undo")
    def undo_meal(meal_id: int):
        meal = get_meal(meal_id)
        if not meal or not meal.get("completed_at"):
            flash("Pasto non trovato nello storico.", "error")
            return redirect(url_for("meals_history"))
        action = clean_text(request.form.get("action")).lower()
        new_date = clean_text(request.form.get("meal_date"))
        if action == "reschedule" and not parse_iso_date(new_date):
            flash("Inserisci una data valida per riprogrammare il pasto.", "error")
            return redirect(url_for("meals_history"))
        restore_meal_ingredients(meal)
        supabase = get_supabase()
        for recipe in meal.get("recipes", []):
            supabase.table("recipe_history").delete().eq("recipe_id", recipe["id"]).eq("cooked_on", meal["meal_date"]).execute()
        if action == "reschedule":
            supabase.table("meals").update({"meal_date": new_date, "completed_at": None, "updated_at": utc_now()}).eq("id", meal_id).execute()
            flash("Pasto annullato e riprogrammato.", "success")
            return redirect(url_for("meals_agenda"))
        delete_meal_record(meal_id)
        flash("Pasto annullato e rimosso dallo storico.", "success")
        return redirect(url_for("meals_history"))

    @app.post("/meals/<int:meal_id>/shopping/<int:prior_id>")
    def meal_add_to_shopping(meal_id: int, prior_id: int):
        meal = get_meal(meal_id)
        if not meal:
            flash("Pasto non trovato.", "error")
            return redirect(url_for("meals_agenda"))
        ingredient = next((row for row in aggregate_meal_ingredients(meal) if int(row["item_prior_id"]) == prior_id), None)
        if not ingredient or ingredient["shortage"] <= 0:
            flash("Questo ingrediente è già disponibile nella quantità necessaria.", "error")
            return redirect(url_for("meal_detail", meal_id=meal_id))
        add_or_increment_shopping_item(
            prior_id,
            ingredient["shortage"],
            ingredient["unit"],
            ingredient["default_location"] or "dispensa",
            notes=f"Pasto: {meal['name']} ({meal['meal_date']})",
        )
        flash(f"{ingredient['name']} aggiunto alla lista della spesa.", "success")
        return redirect(url_for("meal_detail", meal_id=meal_id))

    @app.get("/settings/recipes")
    def recipes():
        query = request.args.get("q", "").strip()
        return render_template("recipes.html", recipes=list_recipes(query), query=query)

    @app.route("/settings/recipes/new", methods=("GET", "POST"))
    def new_recipe():
        meal_id = parse_optional_int(request.form.get("meal_id") if request.method == "POST" else request.args.get("meal_id"))
        if request.method == "POST":
            data, ingredients = recipe_form_data(request.form)
            errors = validate_recipe_data(data, ingredients)
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template("recipe_form.html", recipe=data, ingredients=ingredients, prior_options=list_item_prior_options(), meal_id=meal_id), 400
            recipe_id = create_recipe(data, ingredients)
            if meal_id and get_meal(meal_id):
                add_recipe_to_meal(meal_id, recipe_id)
                flash("Ricetta salvata e associata al meal.", "success")
                return redirect(url_for("meal_detail", meal_id=meal_id))
            flash("Ricetta salvata nel ricettario.", "success")
            return redirect(url_for("recipe_detail", recipe_id=recipe_id))
        recipe = empty_recipe_form()
        recipe["name"] = request.args.get("name", "").strip()
        return render_template("recipe_form.html", recipe=recipe, ingredients=[empty_ingredient()], prior_options=list_item_prior_options(), meal_id=meal_id)

    @app.get("/settings/recipes/<int:recipe_id>")
    def recipe_detail(recipe_id: int):
        recipe = get_recipe(recipe_id)
        if not recipe:
            flash("Ricetta non trovata.", "error")
            return redirect(url_for("recipes"))
        return render_template("recipe_detail.html", recipe=recipe)

    @app.route("/settings/recipes/<int:recipe_id>/edit", methods=("GET", "POST"))
    def edit_recipe(recipe_id: int):
        recipe = get_recipe(recipe_id)
        if not recipe:
            flash("Ricetta non trovata.", "error")
            return redirect(url_for("recipes"))
        if request.method == "POST":
            data, ingredients = recipe_form_data(request.form)
            errors = validate_recipe_data(data, ingredients)
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template("recipe_form.html", recipe=data | {"id": recipe_id}, ingredients=ingredients, prior_options=list_item_prior_options()), 400
            update_recipe(recipe_id, data, ingredients)
            flash("Ricetta aggiornata.", "success")
            return redirect(url_for("recipe_detail", recipe_id=recipe_id))
        return render_template("recipe_form.html", recipe=recipe, ingredients=recipe["ingredients"], prior_options=list_item_prior_options())

    @app.get("/settings/priors")
    def priors():
        query = request.args.get("q", "").strip()
        items = list_item_priors(query)
        return render_template("priors.html", items=items, query=query)

    @app.route("/settings/priors/new", methods=("GET", "POST"))
    def new_prior():
        if request.method == "POST":
            data = prior_form_data(request.form)
            errors = validate_prior_data(data)
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template("prior_form.html", item=data), 400

            supabase = get_supabase()
            existing = supabase.table("item_prior").select("id").ilike("name", data["name"]).limit(1).execute()
            if existing.data:
                flash("Esiste già un prior con questo nome.", "error")
                return render_template("prior_form.html", item=data), 400

            payload = {
                "name": data["name"],
                "category": data.get("category"),
                "typical_quantity": data.get("typical_quantity"),
                "typical_unit": data.get("typical_unit") or "pz",
                "typical_shelf_life_days": data.get("typical_shelf_life_days"),
                "default_location": data.get("default_location") or "dispensa",
                "picture": data.get("picture") or "",
                "notes": data.get("notes") or "",
                "updated_at": utc_now(),
            }
            response = supabase.table("item_prior").insert(payload).execute()
            if not response.data:
                flash("Creazione prior non riuscita.", "error")
                return render_template("prior_form.html", item=data), 500

            flash("Prodotto prior creato.", "success")
            return redirect(url_for("priors"))

        name = request.args.get("name", "").strip()
        return render_template("prior_form.html", item={"name": name})

    @app.post("/settings/priors/new-llm")
    def new_prior_with_llm():
        name = request.form.get("name", "").strip()
        if not name:
            flash("Il nome del prodotto è obbligatorio.", "error")
            return redirect(url_for("priors"))

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            flash("GEMINI_API_KEY non configurato.", "error")
            return redirect(url_for("priors"))

        supabase = get_supabase()
        existing = supabase.table("item_prior").select("id").ilike("name", name).limit(1).execute()
        if existing.data:
            prior_id = existing.data[0]["id"]
        else:
            payload = {
                "name": name,
                "category": None,
                "typical_quantity": None,
                "typical_unit": "pz",
                "default_location": "dispensa",
                "picture": "",
                "notes": "",
                "updated_at": utc_now(),
            }
            response = supabase.table("item_prior").insert(payload).execute()
            if not response.data:
                flash("Creazione prior non riuscita.", "error")
                return redirect(url_for("priors"))
            prior_id = response.data[0]["id"]

        return redirect(url_for("enrich_prior_preview", prior_id=prior_id))

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

    @app.post("/settings/priors/<int:prior_id>/delete")
    def delete_prior(prior_id: int):
        prior = get_item_prior(prior_id)
        if not prior:
            flash("Prodotto prior non trovato.", "error")
            return redirect(url_for("priors"))

        deleted, usage = delete_item_prior(prior_id)
        if not deleted:
            flash(f"Non puoi eliminare questo prior: è ancora usato da {usage}.", "error")
            return redirect(url_for("edit_prior", prior_id=prior_id))

        flash("Prodotto prior eliminato.", "success")
        return redirect(url_for("priors"))

    @app.get("/settings/priors/<int:prior_id>/enrich")
    def enrich_prior_preview(prior_id: int):
        """Show a preview of LLM-suggested metadata and allow accept/decline."""
        prior = get_item_prior(prior_id)
        if not prior:
            flash("Prodotto prior non trovato.", "error")
            return redirect(url_for("priors"))

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            flash("GEMINI_API_KEY non configurato.", "error")
            return redirect(url_for("edit_prior", prior_id=prior_id))

        llm, raw_llm = enrich_prior_with_llm(prior["name"])
        if not llm and not raw_llm:
            flash("Nessun dato utile restituito dall'LLM.", "error")
            return redirect(url_for("edit_prior", prior_id=prior_id))

        # build suggested values without overwriting yet
        suggested = {
            "category": llm.get("category") or prior.get("category"),
            "typical_quantity": llm.get("typical_quantity") if llm.get("typical_quantity") is not None else prior.get("typical_quantity"),
            "typical_unit": llm.get("typical_unit") or prior.get("typical_unit"),
            "typical_shelf_life_days": llm.get("typical_shelf_life_days") if llm.get("typical_shelf_life_days") is not None else prior.get("typical_shelf_life_days"),
            "default_location": llm.get("default_location") or prior.get("default_location"),
            "picture": llm.get("picture") or None,
        }

        return render_template("prior_enrich_preview.html", prior=prior, suggested=suggested, raw_llm=raw_llm)

    @app.post("/settings/priors/<int:prior_id>/enrich/accept")
    def enrich_prior_accept(prior_id: int):
        prior = get_item_prior(prior_id)
        if not prior:
            flash("Prodotto prior non trovato.", "error")
            return redirect(url_for("priors"))

        # form will contain suggested values; only update fields that are present
        merged = {}
        for key in ("category", "typical_quantity", "typical_unit", "typical_shelf_life_days", "default_location", "picture"):
            if key in request.form and request.form.get(key) not in (None, ""):
                value = request.form.get(key)
                if key in ("typical_quantity", "typical_shelf_life_days"):
                    try:
                        if "." in value:
                            val = float(value)
                        else:
                            val = int(value)
                        merged[key] = val
                    except (TypeError, ValueError):
                        continue
                else:
                    merged[key] = value

        if not merged:
            flash("Nessun dato valido da applicare.", "error")
            return redirect(url_for("edit_prior", prior_id=prior_id))

        update_item_prior(prior_id, merged)
        flash("Metadati aggiornati dall'LLM.", "success")
        return redirect(url_for("priors"))


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


def parse_iso_date(value: str | date | None) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
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
        "preparation_status": clean_text(form.get("preparation_status"), "none"),
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


def parse_receipt_date(receipt_text: str) -> str | None:
    """Extract receipt date/time from lines like 'Data: 15/03/2024' and 'Ora: 14:30'."""
    date_match = re.search(
        r"[Dd]ata\s*:?\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})",
        receipt_text,
    )
    time_match = re.search(r"[Oo]ra\s*:?\s*(\d{1,2}):(\d{2})", receipt_text)
    if not date_match:
        return None
    try:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3))
        hour = int(time_match.group(1)) if time_match else 12
        minute = int(time_match.group(2)) if time_match else 0
        dt = datetime(year, month, day, hour, minute)
        return dt.astimezone(UTC).isoformat(timespec="seconds")
    except ValueError:
        return None


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


def get_prior_ids_added_today() -> set[int]:
    """Return prior IDs for inventory items whose updated_at is today (local date)."""
    today_prefix = date.today().isoformat()
    items = (
        get_supabase()
        .table("inventory_items")
        .select("item_prior_id,updated_at")
        .execute()
        .data
        or []
    )
    return {
        int(item["item_prior_id"])
        for item in items
        if (item.get("updated_at") or "")[:10] == today_prefix
    }


def classify_receipt_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    priors = [dict(row) for row in list_item_prior_options()]
    prior_ids_today = get_prior_ids_added_today()
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
                    "added_today": int(prior["id"]) in prior_ids_today,
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
    normalized = clean_text(unit).casefold()
    if normalized in {"pz", "pc", "pezzo", "pezzi", "unita", "u"}:
        return 1.0
    if normalized in {"g", "gr", "grammo", "grammi", "ml"}:
        return 100.0
    if normalized in {"kg", "l", "lt"}:
        return 1.0
    return 1.0


def adjust_quantity_with_unit(
    current_quantity: float,
    unit: str | None,
    direction: str,
) -> tuple[float, str]:
    normalized = clean_text(unit).casefold()
    current_unit = clean_text(unit, "pz")

    if direction == "dec" and normalized in {"kg", "l", "lt"} and current_quantity <= 1.0:
        converted_unit = "g" if normalized == "kg" else "ml"
        converted_quantity = (current_quantity * 1000.0) - 100.0
        return round(converted_quantity, 4), converted_unit

    step = quantity_adjust_step(current_unit)
    new_quantity = current_quantity + step if direction == "inc" else current_quantity - step
    return round(new_quantity, 4), current_unit


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
        "notes": clean_text(form.get("notes")),
    }


def validate_inventory_data(data: dict[str, Any]) -> list[str]:
    errors = validate_prior_data(data)
    if data["quantity"] <= 0:
        errors.append("La quantita' deve essere maggiore di zero.")
    if data["location"] not in LOCATIONS:
        errors.append("Scegli frigo o dispensa.")
    if data.get("preparation_status") not in {"none", "cotto", "aperto"}:
        errors.append("La modalità di preparazione non è valida.")
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

    explicit_location = data.get("default_location") or data.get("location") or data.get("target_location")
    inferred = infer_prior_profile_with_fallback(name)
    explicit_category = normalize_category(data.get("category"))
    explicit_unit = data.get("typical_unit") or data.get("unit")

    prior_data = {
        "name": name,
        "category": inferred.get("category") if explicit_category == "Altro" else explicit_category,
        "typical_quantity": data.get("typical_quantity") if data.get("typical_quantity") is not None else inferred.get("typical_quantity"),
        "typical_unit": explicit_unit or inferred.get("typical_unit") or "pz",
        "typical_shelf_life_days": data.get("typical_shelf_life_days") if data.get("typical_shelf_life_days") is not None else inferred.get("typical_shelf_life_days"),
        "default_location": explicit_location or inferred.get("default_location") or "dispensa",
        "picture": data.get("picture") or inferred.get("picture") or "",

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
        
        "notes": value("notes"),
        "updated_at": utc_now(),
    }
    get_supabase().table("item_prior").update(payload).eq("id", prior_id).execute()


def delete_item_prior(prior_id: int) -> tuple[bool, str | None]:
    """Delete an unused prior, keeping all existing inventory history intact."""
    supabase = get_supabase()
    references = (
        ("inventory_items", "l'inventario"),
        ("shopping_items", "la lista della spesa"),
        ("items_history", "lo storico"),
        ("recipe_ingredients", "una ricetta"),
    )
    for table, label in references:
        rows = supabase.table(table).select("id").eq("item_prior_id", prior_id).limit(1).execute().data or []
        if rows:
            return False, label

    supabase.table("item_prior").delete().eq("id", prior_id).execute()
    return True, None


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


def empty_meal_form() -> dict[str, Any]:
    return {"name": "", "meal_date": date.today().isoformat(), "meal_type": "cena", "people_count": 2, "recipe_ids": []}


def monday_of_week(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_meal_days(week_start: date) -> list[dict[str, Any]]:
    italian_days = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    return [{"weekday": index, "date": week_start + timedelta(days=index), "label": italian_days[index]} for index in range(7)]


def month_name(month: int) -> str:
    return ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"][month]


def weekly_slot_key(weekday: int, meal_type: str) -> str:
    return f"{weekday}_{meal_type}"


def weekly_slots_from_form(form: Any) -> list[dict[str, Any]]:
    slots = []
    for weekday in range(7):
        for meal_type in MEAL_TYPES:
            key = weekly_slot_key(weekday, meal_type)
            slots.append({
                "weekday": weekday,
                "meal_type": meal_type,
                "recipe_ids": parse_id_list(form.getlist(f"recipe_ids_{key}")),
                "recipe_people": {
                    recipe_id: parse_optional_int(form.get(f"recipe_people_{key}_{recipe_id}"), 2) or 2
                    for recipe_id in parse_id_list(form.getlist(f"recipe_ids_{key}"))
                },
            })
    return slots


def list_meal_defaults() -> dict[str, dict[str, Any]]:
    supabase = get_supabase()
    defaults = supabase.table("meal_defaults").select("*").eq("active", True).execute().data or []
    links = supabase.table("meal_default_recipes").select("meal_default_id,recipe_id,people_count,sort_order").order("sort_order").execute().data or []
    result = {}
    for row in defaults:
        key = weekly_slot_key(int(row["weekday"]), row["meal_type"])
        result[key] = row | {"recipes": [
            {"id": int(link["recipe_id"]), "people_count": int(link.get("people_count") or 2)}
            for link in links if int(link["meal_default_id"]) == int(row["id"])
        ]}
    return result


def save_meal_defaults(slots: list[dict[str, Any]]) -> None:
    supabase = get_supabase()
    for slot in slots:
        response = supabase.table("meal_defaults").upsert({
            "weekday": slot["weekday"], "meal_type": slot["meal_type"], "name": MEAL_TYPES[slot["meal_type"]],
            "people_count": sum(slot["recipe_people"].values()) or 2,
            "active": bool(slot["recipe_ids"]), "updated_at": utc_now(),
        }, on_conflict="weekday,meal_type").execute()
        default_id = int(response.data[0]["id"])
        supabase.table("meal_default_recipes").delete().eq("meal_default_id", default_id).execute()
        if slot["recipe_ids"]:
            supabase.table("meal_default_recipes").insert([
                {"meal_default_id": default_id, "recipe_id": recipe_id, "people_count": slot["recipe_people"][recipe_id], "sort_order": order}
                for order, recipe_id in enumerate(slot["recipe_ids"])
            ]).execute()


def load_meal_defaults(week_start: date) -> int:
    defaults = list_meal_defaults()
    existing = get_supabase().table("meals").select("meal_date,meal_type").gte(
        "meal_date", week_start.isoformat()
    ).lt("meal_date", (week_start + timedelta(days=7)).isoformat()).is_("completed_at", "null").execute().data or []
    existing_keys = {(row["meal_date"], row["meal_type"]) for row in existing}
    created = 0
    for slot in defaults.values():
        if not slot["recipes"]:
            continue
        meal_date = week_start + timedelta(days=int(slot["weekday"]))
        if (meal_date.isoformat(), slot["meal_type"]) in existing_keys:
            continue
        create_meal({
            "name": f"{MEAL_TYPES[slot['meal_type']]} {meal_date.day} {month_name(meal_date.month)}",
            "meal_date": meal_date.isoformat(), "meal_type": slot["meal_type"],
            "people_count": sum(recipe["people_count"] for recipe in slot["recipes"]) or 2,
            "recipe_ids": [recipe["id"] for recipe in slot["recipes"]],
            "recipe_people": {recipe["id"]: recipe["people_count"] for recipe in slot["recipes"]},
        })
        created += 1
    return created


def meal_form_data(form: Any) -> dict[str, Any]:
    return {
        "name": clean_text(form.get("name")),
        "meal_date": clean_text(form.get("meal_date")),
        "meal_type": clean_text(form.get("meal_type"), "cena"),
        "people_count": parse_optional_int(form.get("people_count"), 2) or 2,
        "recipe_ids": parse_id_list(form.getlist("recipe_ids")),
    }


def validate_meal_data(data: dict[str, Any]) -> list[str]:
    errors = []
    if not data["name"]:
        errors.append("Il nome del pasto è obbligatorio.")
    if not parse_iso_date(data.get("meal_date")):
        errors.append("Inserisci una data valida.")
    if data.get("meal_type") not in MEAL_TYPES:
        errors.append("Scegli colazione, pranzo o cena.")
    if int(data.get("people_count") or 0) <= 0:
        errors.append("Il numero di persone deve essere maggiore di zero.")
    if not data.get("recipe_ids"):
        errors.append("Seleziona almeno una ricetta.")
    return errors


def empty_recipe_form() -> dict[str, Any]:
    return {"name": "", "servings": 2, "meal_type": "altro", "use_automatically": True, "picture": "", "notes": ""}


def empty_ingredient() -> dict[str, Any]:
    return {"name": "", "quantity": 1, "quantity_is_qb": False, "unit": "pz", "item_prior_id": ""}


def upload_ibb_image(file_storage: Any) -> str | None:
    """Upload a recipe image to ImgBB when IMGBB_API_KEY is configured."""
    api_key = os.environ.get("IMGBB_API_KEY", "").strip()
    if not api_key or not file_storage or not getattr(file_storage, "filename", ""):
        return None
    import uuid
    image_bytes = file_storage.read()
    if not image_bytes:
        return None
    boundary = f"----KitchenPlanner{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"key\"\r\n\r\n{api_key}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{file_storage.filename}\"\r\n"
        f"Content-Type: {file_storage.mimetype or 'application/octet-stream'}\r\n\r\n"
    ).encode() + image_bytes + f"\r\n--{boundary}--\r\n".encode()
    try:
        response = urlopen(Request(
            "https://api.imgbb.com/1/upload",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        ), timeout=15)
        payload = json.loads(response.read().decode("utf-8"))
        return payload.get("data", {}).get("url") or payload.get("data", {}).get("display_url")
    except (HTTPError, URLError, ValueError, OSError):
        return None


def recipe_form_data(form: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    picture = clean_text(form.get("picture"))
    uploaded = upload_ibb_image(request.files.get("picture_file"))
    if uploaded:
        picture = uploaded
    ingredients = []
    for raw_id in form.getlist("ingredient_row_ids"):
        name = clean_text(form.get(f"ingredient_name_{raw_id}"))
        raw_quantity = clean_text(form.get(f"ingredient_quantity_{raw_id}"))
        normalized_quantity = raw_quantity.casefold().replace(" ", "")
        quantity_is_qb = normalized_quantity in {"qb", "q.b", "q.b."}
        quantity = 0 if quantity_is_qb else parse_optional_quantity(raw_quantity)
        if not name and not raw_quantity:
            continue
        ingredients.append({
            "name": name,
            "quantity": quantity or 0,
            "quantity_is_qb": quantity_is_qb,
            "unit": clean_text(form.get(f"ingredient_unit_{raw_id}"), "pz"),
            "item_prior_id": parse_optional_int(form.get(f"ingredient_prior_id_{raw_id}")),
        })
    return {
        "name": clean_text(form.get("name")),
        "servings": parse_optional_int(form.get("servings"), 2) or 2,
        "meal_type": clean_text(form.get("meal_type"), "altro"),
        "use_automatically": "1" in form.getlist("use_automatically"),
        "picture": picture,
        "notes": clean_text(form.get("notes")),
    }, ingredients


def validate_recipe_data(data: dict[str, Any], ingredients: list[dict[str, Any]]) -> list[str]:
    errors = []
    if not data["name"]:
        errors.append("Il nome della ricetta è obbligatorio.")
    if int(data.get("servings") or 0) <= 0:
        errors.append("Il numero di persone della ricetta deve essere maggiore di zero.")
    if data.get("meal_type") not in RECIPE_MEAL_TYPES:
        errors.append("Scegli un tipo di pasto valido.")
    if not ingredients:
        errors.append("Inserisci almeno un ingrediente.")
    for ingredient in ingredients:
        if not ingredient["name"]:
            errors.append("Ogni ingrediente deve avere un nome.")
        if not ingredient.get("quantity_is_qb") and ingredient["quantity"] <= 0:
            errors.append("Le quantità degli ingredienti devono essere maggiori di zero.")
    return errors


def create_recipe(data: dict[str, Any], ingredients: list[dict[str, Any]]) -> int:
    supabase = get_supabase()
    response = supabase.table("recipes").insert({
        "name": data["name"], "servings": data["servings"], "meal_type": data["meal_type"],
        "use_automatically": data["use_automatically"], "picture": data.get("picture") or "", "notes": data.get("notes") or "",
        "updated_at": utc_now(),
    }).execute()
    recipe_id = int(response.data[0]["id"])
    save_recipe_ingredients(recipe_id, ingredients)
    return recipe_id


def save_recipe_ingredients(recipe_id: int, ingredients: list[dict[str, Any]]) -> None:
    supabase = get_supabase()
    rows = []
    for order, ingredient in enumerate(ingredients):
        prior_id = ensure_item_prior({
            "name": ingredient["name"], "category": "Altro", "typical_quantity": ingredient["quantity"],
            "typical_unit": ingredient["unit"], "default_location": "dispensa", "picture": "", "prior_notes": "",
        }, existing_prior_id=ingredient.get("item_prior_id"), fetch_picture=False, update_existing=False)
        rows.append({"recipe_id": recipe_id, "item_prior_id": prior_id, "quantity": ingredient["quantity"], "quantity_is_qb": bool(ingredient.get("quantity_is_qb")), "unit": ingredient["unit"], "sort_order": order})
    if rows:
        supabase.table("recipe_ingredients").insert(rows).execute()


def update_recipe(recipe_id: int, data: dict[str, Any], ingredients: list[dict[str, Any]]) -> None:
    supabase = get_supabase()
    supabase.table("recipes").update({
        "name": data["name"], "servings": data["servings"], "meal_type": data["meal_type"],
        "use_automatically": data["use_automatically"], "picture": data.get("picture") or "", "notes": data.get("notes") or "", "updated_at": utc_now(),
    }).eq("id", recipe_id).execute()
    supabase.table("recipe_ingredients").delete().eq("recipe_id", recipe_id).execute()
    save_recipe_ingredients(recipe_id, ingredients)


def list_recipes(query: str = "") -> list[dict[str, Any]]:
    rows = get_supabase().table("recipes").select("*").execute().data or []
    if query:
        needle = query.casefold()
        rows = [row for row in rows if needle in (row.get("name") or "").casefold()]
    history = get_supabase().table("recipe_history").select("recipe_id,cooked_on").order("cooked_on", desc=True).execute().data or []
    history_map: dict[int, list[str]] = {}
    for row in history:
        history_map.setdefault(int(row["recipe_id"]), []).append(row["cooked_on"])
    for row in rows:
        row["history"] = history_map.get(int(row["id"]), [])
    return sorted(rows, key=lambda row: (row.get("name") or "").casefold())


def get_recipe(recipe_id: int) -> dict[str, Any] | None:
    response = get_supabase().table("recipes").select("*").eq("id", recipe_id).limit(1).execute()
    if not response.data:
        return None
    recipe = response.data[0]
    rows = get_supabase().table("recipe_ingredients").select("*").eq("recipe_id", recipe_id).order("sort_order").execute().data or []
    priors = load_item_prior_map([int(row["item_prior_id"]) for row in rows])
    recipe["ingredients"] = [row | {"name": priors.get(int(row["item_prior_id"]), {}).get("name", "Ingrediente"), "picture": priors.get(int(row["item_prior_id"]), {}).get("picture"), "default_location": priors.get(int(row["item_prior_id"]), {}).get("default_location", "dispensa")} for row in rows]
    recipe["history"] = [row["cooked_on"] for row in (get_supabase().table("recipe_history").select("cooked_on").eq("recipe_id", recipe_id).order("cooked_on", desc=True).execute().data or [])]
    return recipe


def create_meal(data: dict[str, Any]) -> int:
    supabase = get_supabase()
    response = supabase.table("meals").insert({"name": data["name"], "meal_date": data["meal_date"], "meal_type": data["meal_type"], "people_count": data["people_count"], "updated_at": utc_now()}).execute()
    meal_id = int(response.data[0]["id"])
    recipe_people = data.get("recipe_people", {})
    supabase.table("meal_recipes").insert([{
        "meal_id": meal_id, "recipe_id": recipe_id, "people_count": int(recipe_people.get(recipe_id, data["people_count"])), "sort_order": order
    } for order, recipe_id in enumerate(data["recipe_ids"])]).execute()
    return meal_id


def delete_meal_record(meal_id: int) -> None:
    supabase = get_supabase()
    # Delete links explicitly so this also works if the schema predates ON DELETE CASCADE.
    supabase.table("meal_recipes").delete().eq("meal_id", meal_id).execute()
    supabase.table("meals").delete().eq("id", meal_id).execute()


def get_meal_recipe_links(meal_id: int) -> list[dict[str, Any]]:
    return get_supabase().table("meal_recipes").select("id,recipe_id,sort_order").eq("meal_id", meal_id).order("sort_order").execute().data or []


def add_recipe_to_meal(meal_id: int, recipe_id: int) -> bool:
    links = get_meal_recipe_links(meal_id)
    if any(int(link["recipe_id"]) == recipe_id for link in links):
        return False
    next_order = max((int(link.get("sort_order") or 0) for link in links), default=-1) + 1
    meal = get_meal(meal_id)
    people_count = int(meal.get("people_count") or 2) if meal else 2
    get_supabase().table("meal_recipes").insert({"meal_id": meal_id, "recipe_id": recipe_id, "people_count": people_count, "sort_order": next_order}).execute()
    return True


def reorder_meal_recipes(meal_id: int) -> None:
    supabase = get_supabase()
    for sort_order, link in enumerate(get_meal_recipe_links(meal_id)):
        supabase.table("meal_recipes").update({"sort_order": sort_order}).eq("id", link["id"]).execute()


def list_meals() -> list[dict[str, Any]]:
    meals = get_supabase().table("meals").select("*").gte("meal_date", date.today().isoformat()).is_("completed_at", "null").order("meal_date").order("meal_type").execute().data or []
    recipe_links = get_supabase().table("meal_recipes").select("meal_id,recipe_id").execute().data or []
    recipes_map = {int(row["id"]): row for row in (get_supabase().table("recipes").select("id,name,picture").execute().data or [])}
    links: dict[int, list[dict[str, Any]]] = {}
    for link in recipe_links:
        links.setdefault(int(link["meal_id"]), []).append(recipes_map.get(int(link["recipe_id"]), {}))
    for meal in meals:
        meal["meal_type_label"] = MEAL_TYPES.get(meal["meal_type"], meal["meal_type"])
        meal["recipes"] = links.get(int(meal["id"]), [])
    return meals


def list_meal_history() -> list[dict[str, Any]]:
    meals = get_supabase().table("meals").select("*").not_.is_("completed_at", "null").order("completed_at", desc=True).execute().data or []
    recipe_links = get_supabase().table("meal_recipes").select("meal_id,recipe_id").execute().data or []
    recipes_map = {int(row["id"]): row for row in (get_supabase().table("recipes").select("id,name,picture").execute().data or [])}
    links: dict[int, list[dict[str, Any]]] = {}
    for link in recipe_links:
        links.setdefault(int(link["meal_id"]), []).append(recipes_map.get(int(link["recipe_id"]), {}))
    for meal in meals:
        meal["meal_type_label"] = MEAL_TYPES.get(meal["meal_type"], meal["meal_type"])
        meal["recipes"] = links.get(int(meal["id"]), [])
    return meals


def get_meal(meal_id: int) -> dict[str, Any] | None:
    response = get_supabase().table("meals").select("*").eq("id", meal_id).limit(1).execute()
    if not response.data:
        return None
    meal = response.data[0]
    recipe_links = get_supabase().table("meal_recipes").select("recipe_id,people_count").eq("meal_id", meal_id).order("sort_order").execute().data or []
    recipe_ids = [int(row["recipe_id"]) for row in recipe_links]
    meal["recipes"] = [get_recipe(recipe_id) for recipe_id in recipe_ids]
    for recipe, link in zip(meal["recipes"], recipe_links):
        if recipe:
            recipe["people_count"] = int(link.get("people_count") or meal["people_count"] or 2)
    meal["meal_type_label"] = MEAL_TYPES.get(meal["meal_type"], meal["meal_type"])
    return meal


def unit_factor(unit: str) -> tuple[str, float]:
    normalized = clean_text(unit, "pz").casefold()
    if normalized == "kg":
        return "g", 1000.0
    if normalized == "l":
        return "ml", 1000.0
    return normalized, 1.0


def convert_quantity(quantity: float, from_unit: str | None, to_unit: str | None) -> float:
    from_base, from_factor = unit_factor(from_unit or "pz")
    to_base, to_factor = unit_factor(to_unit or "pz")
    if from_base != to_base:
        return 0.0
    return quantity * from_factor / to_factor


def get_today_quantity_change(item_id: int, item_unit: str | None) -> float:
    changes = (
        get_supabase()
        .table("inventory_quantity_changes")
        .select("quantity,unit")
        .eq("inventory_item_id", item_id)
        .eq("changed_on", date.today().isoformat())
        .execute()
        .data
        or []
    )
    return sum(convert_quantity(float(change["quantity"]), change.get("unit"), item_unit) for change in changes)


def aggregate_meal_ingredients(meal: dict[str, Any]) -> list[dict[str, Any]]:
    aggregated: dict[int, dict[str, Any]] = {}
    for recipe in meal.get("recipes", []):
        if not recipe:
            continue
        scale = float(recipe.get("people_count") or meal["people_count"]) / float(recipe["servings"] or 2)
        for ingredient in recipe["ingredients"]:
            prior_id = int(ingredient["item_prior_id"])
            base_unit, factor = unit_factor(ingredient["unit"])
            row = aggregated.setdefault(prior_id, {"item_prior_id": prior_id, "name": ingredient["name"], "required": 0.0, "quantity_is_qb": False, "always_available": normalize_match_text(ingredient["name"]) == "acqua", "unit": base_unit, "default_location": ingredient.get("default_location") or "dispensa", "recipes": []})
            if ingredient.get("quantity_is_qb"):
                row["quantity_is_qb"] = True
            elif row["unit"] == base_unit:
                row["required"] += float(ingredient["quantity"]) * scale * factor
            row["recipes"].append(recipe["name"])
    supabase = get_supabase()
    inventory = supabase.table("inventory_items").select("item_prior_id,quantity,unit").execute().data or []
    shopping = supabase.table("shopping_items").select("item_prior_id,quantity,unit").execute().data or []

    def stock_by_prior(rows: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
        stock: dict[int, dict[str, float]] = {}
        for item in rows:
            base_unit, factor = unit_factor(item["unit"])
            prior_stock = stock.setdefault(int(item["item_prior_id"]), {})
            prior_stock[base_unit] = prior_stock.get(base_unit, 0.0) + float(item["quantity"] or 0) * factor
        return stock

    inventory_stock = stock_by_prior(inventory)
    shopping_stock = stock_by_prior(shopping)
    inventory_presence = {
        int(item["item_prior_id"])
        for item in inventory
        if float(item.get("quantity") or 0) > 0
    }
    for row in aggregated.values():
        unit = row["unit"]
        inventory_have = inventory_stock.get(row["item_prior_id"], {}).get(unit, 0.0)
        shopping_have = shopping_stock.get(row["item_prior_id"], {}).get(unit, 0.0)
        if row["always_available"]:
            row["available"] = row["required"]
            row["inventory_available"] = row["required"]
            row["shopping_available"] = 0
            row["shopping_used"] = 0
            row["shortage"] = 0
            row["status"] = "ok"
            continue
        if row["quantity_is_qb"]:
            row["available"] = 1 if row["item_prior_id"] in inventory_presence else 0
            row["inventory_available"] = row["available"]
            row["shopping_available"] = 0
            row["shopping_used"] = 0
            row["shortage"] = 0
            row["status"] = "ok" if row["item_prior_id"] in inventory_presence else "missing"
            continue
        have = inventory_have + shopping_have
        shopping_used = max(min(row["required"] - inventory_have, shopping_have), 0.0)
        row["available"] = have
        row["inventory_available"] = inventory_have
        row["shopping_available"] = shopping_have
        row["shopping_used"] = shopping_used
        row["shortage"] = max(row["required"] - have, 0.0)
        row["status"] = "ok" if have >= row["required"] else ("partial" if have > 0 else "missing")
    return sorted(aggregated.values(), key=lambda row: row["name"].casefold())


def consume_meal_ingredients(meal: dict[str, Any]) -> None:
    """Consume available pantry stock, using the instances with nearest expiry first."""
    ingredients = aggregate_meal_ingredients(meal)
    supabase = get_supabase()
    for ingredient in ingredients:
        if ingredient["quantity_is_qb"] or ingredient["always_available"] or ingredient["required"] <= 0:
            continue

        needed_base = float(ingredient["required"])
        rows = (
            supabase.table("inventory_items")
            .select("*")
            .eq("item_prior_id", ingredient["item_prior_id"])
            .gt("quantity", 0)
            .execute()
            .data
            or []
        )
        base_unit = ingredient["unit"]
        compatible = []
        for row in rows:
            row_unit, row_factor = unit_factor(row["unit"])
            if row_unit == base_unit:
                compatible.append((row, row_factor))
        compatible.sort(key=lambda pair: (parse_iso_date(pair[0].get("expiry_date")) is None, pair[0].get("expiry_date") or "9999-12-31", pair[0].get("id", 0)))

        for row, row_factor in compatible:
            if needed_base <= 0:
                break
            available_base = float(row["quantity"] or 0) * row_factor
            consumed_base = min(available_base, needed_base)
            supabase.table("meal_consumptions").insert({
                "meal_id": meal["id"],
                "inventory_item_id": row["id"],
                "item_snapshot": row,
                "consumed_quantity": consumed_base / row_factor,
                "consumed_unit": row["unit"],
            }).execute()
            remaining_base = available_base - consumed_base
            if remaining_base <= 0:
                delete_inventory_item(int(row["id"]))
            else:
                update_inventory_item(
                    int(row["id"]),
                    int(row["item_prior_id"]),
                    row | {"quantity": remaining_base / row_factor, "unit": row["unit"]},
                    quantity_delta=-(consumed_base / row_factor),
                )
            needed_base -= consumed_base


def restore_meal_ingredients(meal: dict[str, Any]) -> None:
    """Restore the exact inventory quantities recorded when a meal was completed."""
    supabase = get_supabase()
    records = supabase.table("meal_consumptions").select("*").eq("meal_id", meal["id"]).order("id").execute().data or []
    for record in records:
        snapshot = record.get("item_snapshot") or {}
        item_id = int(record["inventory_item_id"])
        current = supabase.table("inventory_items").select("*").eq("id", item_id).limit(1).execute().data or []
        if current:
            row = current[0]
            if row.get("unit") == record["consumed_unit"]:
                quantity = float(row.get("quantity") or 0) + float(record["consumed_quantity"])
                update_inventory_item(
                    item_id,
                    int(row["item_prior_id"]),
                    row | {"quantity": quantity, "unit": row["unit"]},
                    quantity_delta=float(record["consumed_quantity"]),
                )
            else:
                snapshot = {}
        if not current or not snapshot:
            payload = {key: snapshot[key] for key in ("item_prior_id", "quantity", "unit", "location", "expiry_date", "expiry_estimated", "notes") if key in snapshot}
            if payload:
                response = supabase.table("inventory_items").insert(payload).execute()
                if response.data:
                    record_inventory_quantity_change(
                        int(response.data[0]["id"]),
                        float(snapshot.get("quantity") or 0),
                        snapshot.get("unit") or "pz",
                    )
    supabase.table("meal_consumptions").delete().eq("meal_id", meal["id"]).execute()


def fallback_ingredient_profile(name: str) -> dict[str, Any]:
    """Return a resilient default profile when AI/external enrichment is unavailable."""
    normalized = normalize_match_text(name)

    profile = {
        "category": "Altro",
        "typical_quantity": 1.0,
        "typical_unit": "pz",
        "typical_shelf_life_days": None,
        "default_location": "dispensa",
        "picture": "",
    }
    return profile


def infer_prior_profile_with_fallback(name: str) -> dict[str, Any]:
    """Infer prior fields with LLM first, then fall back to deterministic defaults."""
    fallback = fallback_ingredient_profile(name)
    try:
        llm, _raw = enrich_prior_with_llm(name)
    except Exception:
        return fallback
    if not llm:
        return fallback

    merged = fallback.copy()
    for key in (
        "category",
        "typical_quantity",
        "typical_unit",
        "typical_shelf_life_days",
        "default_location",
        "picture",
    ):
        value = llm.get(key)
        if value not in (None, ""):
            merged[key] = value
    return merged


def enrich_prior_with_llm(name: str) -> tuple[dict[str, Any], str | None]:
    """Call Gemini to fill in missing metadata fields for a new food product prior.

    Returns a validated dict with keys: category, typical_quantity, typical_unit,
    typical_shelf_life_days, default_location (all may be None if the LLM is uncertain
    or the call fails).
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {}, None

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    categories_str = ", ".join(f'"{c}"' for c in CATEGORIES)
    units_str = ", ".join(f'"{u}"' for u in UNITS)

    prompt = (
        "Sei un assistente per una app di gestione cucina italiana.\n"
        "Dato il nome di un prodotto alimentare, rispondi SOLO con un oggetto JSON valido "
        "(senza markdown, senza testo aggiuntivo) con questi campi:\n"
        f'- "category": una tra [{categories_str}], oppure null se incerto\n'
        f'- "typical_quantity": numero positivo (quantità tipica di acquisto), oppure null se incerto\n'
        f'- "typical_unit": una tra [{units_str}], oppure null se incerto\n'
        '- "typical_shelf_life_days": intero positivo (giorni di conservazione tipica dopo acquisto), oppure null se incerto o se molto lungo (es. > 365)\n'
        '- "default_location": "frigo" o "dispensa" in base a dove si conserva normalmente, oppure null se incerto\n'
        '- "picture": se trovi un URL diretto ad un immagine rappresentativa del prodotto restituisci l\'URL, altrimenti null\n'
        '- "picture_source": se "picture" è valorizzata, specifica la fonte: "TheMealDB", "Wikimedia Commons" o "Open Food Facts" (o altra fonte riconoscibile)\n'
        '- "source_product_url": se hai trovato una pagina prodotto sorgente (Open Food Facts o Wikidata), restituisci l\'URL, altrimenti null\n\n'
        'Cerca l\'immagine o URL prodotto nelle seguenti risorse, in quest\'ordine preferenziale: TheMealDB ingredient images (https://www.themealdb.com/images/ingredients/), Wikidata (immagini su Wikimedia Commons), Open Food Facts (image_front_url). Se trovi più di una fonte preferisci TheMealDB, poi Wikidata, poi Open Food Facts.\n\n'
        f'Prodotto: "{name}"\n\n'
        "Rispondi SOLO con il JSON."
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
        content = getattr(response, "text", None) or (response.to_dict().get("output") if hasattr(response, "to_dict") else "") or ""
    except Exception:
        return {}, None

    # Strip markdown code fences that some models add
    content = re.sub(r"```(?:json)?\s*|\s*```", "", content).strip()

    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        # Return empty parsed dict and raw content so callers can show fallback
        return {}, content

    if not isinstance(raw, dict):
        return {}, content

    return _validate_llm_prior_data(raw), content


def _validate_llm_prior_data(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and sanitize LLM-returned prior fields.

    Each field is checked for type and allowed values. Invalid or absent values
    are returned as None so callers can apply their own placeholders.
    """
    result: dict[str, Any] = {}

    category = raw.get("category")
    result["category"] = category if isinstance(category, str) and category in CATEGORIES else None

    try:
        qty = float(raw["typical_quantity"])
        result["typical_quantity"] = qty if qty > 0 else None
    except (KeyError, TypeError, ValueError):
        result["typical_quantity"] = None

    unit = raw.get("typical_unit")
    result["typical_unit"] = unit if isinstance(unit, str) and unit in UNITS else None

    try:
        days = int(raw["typical_shelf_life_days"])
        result["typical_shelf_life_days"] = days if days > 0 else None
    except (KeyError, TypeError, ValueError):
        result["typical_shelf_life_days"] = None

    location = raw.get("default_location")
    result["default_location"] = location if isinstance(location, str) and location in LOCATIONS else None

    # picture
    picture = raw.get("picture")
    if isinstance(picture, str) and picture.startswith("http"):
        result["picture"] = picture
    else:
        result["picture"] = None

    return result


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
        
        "prior_notes": prior.get("notes", ""),
    }


def list_inventory_items(location: str | None = None) -> list[dict[str, Any]]:
    query = get_supabase().table("inventory_items").select("*")
    if location:
        query = query.eq("location", location)
    inventory_items = query.execute().data or []
    prior_map = load_item_prior_map([int(item["item_prior_id"]) for item in inventory_items])
    changes = (
        get_supabase()
        .table("inventory_quantity_changes")
        .select("inventory_item_id,quantity,unit")
        .in_("inventory_item_id", [int(item["id"]) for item in inventory_items])
        .eq("changed_on", date.today().isoformat())
        .execute()
        .data
        or []
    ) if inventory_items else []
    change_map: dict[int, float] = {}
    for change in changes:
        item_id = int(change["inventory_item_id"])
        change_map[item_id] = change_map.get(item_id, 0) + convert_quantity(
            float(change["quantity"]), change.get("unit"), next(
                (item.get("unit") for item in inventory_items if int(item["id"]) == item_id),
                change.get("unit"),
            )
        )
    merged = [
        merge_item_with_prior(item, prior_map.get(int(item["item_prior_id"])))
        | {"today_quantity_change": change_map.get(int(item["id"]), 0)}
        for item in inventory_items
    ]

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


def create_inventory_item(
    item_prior_id: int,
    data: dict[str, Any],
    *,
    merge_similar: bool = False,
) -> int:
    if merge_similar:
        existing = find_similar_inventory_item(item_prior_id, data.get("expiry_date"))
        if existing:
            existing_unit, existing_factor = unit_factor(existing["unit"])
            incoming_unit, incoming_factor = unit_factor(data["unit"])
            if existing_unit == incoming_unit:
                new_quantity = float(existing.get("quantity") or 0) + float(data["quantity"]) * incoming_factor / existing_factor
                update_inventory_item(
                    int(existing["id"]),
                    item_prior_id,
                    existing | {"quantity": new_quantity, "unit": existing["unit"]},
                    quantity_delta=float(data["quantity"]) * incoming_factor / existing_factor,
                )
                return int(existing["id"])
    payload = {
        "item_prior_id": item_prior_id,
        "quantity": data["quantity"],
        "unit": data["unit"],
        "location": data["location"],
        "preparation_status": data.get("preparation_status") or "none",
        "expiry_date": data.get("expiry_date"),
        "expiry_estimated": int(data.get("expiry_estimated") or 0),
        "notes": data.get("notes"),
        "updated_at": utc_now(),
    }
    response = get_supabase().table("inventory_items").insert(payload).execute()
    if not response.data:
        raise RuntimeError("Inserimento inventario non riuscito.")
    item_id = int(response.data[0]["id"])
    record_inventory_quantity_change(item_id, float(data["quantity"]), data["unit"])
    return item_id


def find_similar_inventory_item(item_prior_id: int, expiry_date: str | None) -> dict[str, Any] | None:
    rows = get_supabase().table("inventory_items").select("*").eq("item_prior_id", item_prior_id).gt("quantity", 0).execute().data or []
    target = parse_iso_date(expiry_date)
    candidates = []
    for row in rows:
        current = parse_iso_date(row.get("expiry_date"))
        if target is None or current is None:
            if target != current:
                continue
            distance = 0
        else:
            distance = abs((current - target).days)
            if distance > 5:
                continue
        candidates.append((distance, row))
    return min(candidates, key=lambda value: (value[0], value[1].get("id", 0)))[1] if candidates else None


def update_inventory_item(
    item_id: int,
    item_prior_id: int,
    data: dict[str, Any],
    *,
    quantity_delta: float | None = None,
) -> None:
    payload = {
        "item_prior_id": item_prior_id,
        "quantity": data["quantity"],
        "unit": data["unit"],
        "location": data["location"],
        "preparation_status": data.get("preparation_status") or "none",
        "expiry_date": data.get("expiry_date"),
        "expiry_estimated": int(data.get("expiry_estimated") or 0),
        "notes": data.get("notes"),
        "updated_at": utc_now(),
    }
    get_supabase().table("inventory_items").update(payload).eq("id", item_id).execute()
    if quantity_delta:
        record_inventory_quantity_change(item_id, quantity_delta, data["unit"])


def record_inventory_quantity_change(item_id: int, quantity: float, unit: str) -> None:
    if not quantity:
        return
    get_supabase().table("inventory_quantity_changes").insert(
        {
            "inventory_item_id": item_id,
            "quantity": quantity,
            "unit": unit,
            "changed_on": date.today().isoformat(),
        }
    ).execute()


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
    category_order = {cat: i for i, cat in enumerate(CATEGORIES)}
    return sorted(
        merged,
        key=lambda row: (
            category_order.get(row.get("category") or "Altro", len(CATEGORIES)),
            (row.get("name") or "").casefold(),
        ),
    )


def get_shopping_item(item_id: int) -> dict[str, Any] | None:
    response = get_supabase().table("shopping_items").select("*").eq("id", item_id).limit(1).execute()
    if not response.data:
        return None
    item = response.data[0]
    prior = get_item_prior(int(item["item_prior_id"]))
    return merge_item_with_prior(item, prior)


def delete_shopping_item(item_id: int) -> None:
    get_supabase().table("shopping_items").delete().eq("id", item_id).execute()


def update_shopping_item(item_id: int, new_quantity: float, unit: str) -> None:
    get_supabase().table("shopping_items").update({"quantity": new_quantity, "unit": unit}).eq("id", item_id).execute()


def complete_shopping_purchase(
    item: dict[str, Any],
    quantity: float,
    unit: str,
    target_location: str,
    typical_shelf_life_days: int | None,
    cost: float | None,
    purchased_at: str,
    expiry_input: str | None,
) -> str | None:
    if quantity <= 0:
        return "La quantita' acquistata deve essere maggiore di zero."

    if target_location not in LOCATIONS:
        return "Destinazione non valida."

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

    expiry_date, expiry_estimated = resolve_expiry(expiry_input, typical_shelf_life_days)

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
        merge_similar=True,
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
    delete_shopping_item(int(item["id"]))
    return None


def parse_id_list(values: list[str]) -> list[int]:
    selected_ids: list[int] = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed not in selected_ids:
            selected_ids.append(parsed)
    return selected_ids


def add_receipt_item_to_kitchen(
    prior_id: int,
    quantity: float,
    unit: str,
    cost: float | None,
    description: str,
    purchased_at: str | None = None,
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
            "purchased_at": purchased_at or utc_now(),
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
