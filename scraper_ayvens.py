"""
scraper.py — Ayvens
=====================
Approche entièrement dynamique : chaque fiche véhicule affichée sur le
catalogue a un attribut aria-label du type "View details for PEUGEOT 3008".
En scrollant jusqu'à charger toutes les fiches (chargement différé /
infinite scroll) et en lisant tous ces libellés, on obtient directement la
liste RÉELLE des marques et modèles présents sur le site à l'instant T —
aucune liste de marques codée en dur, donc toujours à jour automatiquement,
même si Ayvens ajoute une nouvelle marque demain.

Deux modes de financement existent sur le site : "leasing" (Location Longue
Durée) et "cash" (Achat comptant) — scrapés séparément (colonne
`type_financement` dans le CSV).

Pour chaque mode de financement, on scrape 2 fois :
  1. Catalogue complet (tous carburants)
  2. Catalogue filtré sur "Électrique" uniquement (fueltype=ELECTRIC)
et on calcule la proportion par (marque, modèle).

USAGE
-----
    pip install playwright pandas --break-system-packages
    playwright install chromium
    python scraper.py

    SCRAPER_HEADLESS=0 python scraper.py   -> mode visible, pour déboguer
"""

import csv
import datetime as dt
import os
import re
import time

from playwright.sync_api import sync_playwright

BASE_URL = "https://used-cars.ayvens.com/fr-fr/catalog"
FINANCE_TYPES = ["leasing", "cash"]

CSV_PATH = "data/historique_ayvens.csv"
CSV_FIELDS = ["date_releve", "type_financement", "marque", "modele",
              "nb_total", "nb_electrique", "proportion_electrique"]

HEADLESS = os.environ.get("SCRAPER_HEADLESS", "1") != "0"

ARIA_SELECTOR = "[aria-label^='View details for']"
RESULT_COUNT_PATTERN = re.compile(r"(\d[\d\s]*)\s*[Rr]ésultat")


def _get_announced_total(page):
    """Lit le nombre annoncé par le site (ex: '580 Résultats'), pour
    vérifier ensuite que le défilement a bien tout chargé."""
    text = page.inner_text("body")
    m = RESULT_COUNT_PATTERN.search(text)
    return int(m.group(1).replace(" ", "")) if m else None


def _dismiss_cookie_banner(page):
    for label in ["Tout accepter", "Accepter", "J'accepte", "Accepter tout"]:
        try:
            btn = page.get_by_text(label, exact=False)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                page.wait_for_timeout(800)
                return True
        except Exception:
            continue
    return False


def _click_load_more_if_present(page):
    """Certains catalogues ne chargent que les 2 premiers lots via scroll
    infini, puis demandent un clic explicite sur un bouton 'Voir plus' pour
    continuer. On cherche ce bouton et on clique s'il existe."""
    for label in ["Voir plus", "Charger plus", "Afficher plus", "Load more",
                  "Plus de résultats", "Voir plus de résultats"]:
        try:
            btn = page.get_by_text(label, exact=False)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                return True
        except Exception:
            continue
    return False


def _scroll_to_load_all(page, max_iterations=150):
    """Fait défiler jusqu'à la dernière fiche véhicule chargée à chaque
    itération (scroll_into_view_if_needed), ce qui déclenche le chargement
    différé quel que soit le conteneur réellement scrollable — plus fiable
    qu'un mouse.wheel positionné à l'aveugle. S'arrête quand le nombre de
    fiches se stabilise (5 tours sans changement), en essayant aussi un
    éventuel bouton 'Voir plus' entre-temps."""
    previous = -1
    stable_rounds = 0

    for i in range(max_iterations):
        locator = page.locator(ARIA_SELECTOR)
        current = locator.count()

        if current == previous:
            stable_rounds += 1
            clicked = _click_load_more_if_present(page)
            if clicked:
                page.wait_for_timeout(1500)
                stable_rounds = 0
                continue
            if stable_rounds >= 5:
                break
        else:
            stable_rounds = 0
        previous = current

        if current > 0:
            try:
                locator.nth(current - 1).scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass
        else:
            page.mouse.wheel(0, 2000)

        page.wait_for_timeout(1000)

    return previous


def _extract_brand_model_counts(page):
    """Lit tous les aria-label 'View details for MARQUE MODELE...' visibles
    et retourne un dict {(marque, modele): nombre_de_fiches}."""
    labels_locator = page.locator(ARIA_SELECTOR)
    n = labels_locator.count()
    counts = {}
    for i in range(n):
        raw = labels_locator.nth(i).get_attribute("aria-label") or ""
        text = raw.replace("View details for", "").strip()
        if not text:
            continue
        parts = text.split(" ", 1)
        brand = parts[0].strip()
        model = parts[1].strip() if len(parts) > 1 else ""
        key = (brand, model)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _scrape_catalog(page, financetype, fueltype=None):
    params = [f"financetype={financetype}"]
    if fueltype:
        params.append(f"fueltype={fueltype}")
    url = f"{BASE_URL}?{'&'.join(params)}"

    print(f"    Chargement : {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    _dismiss_cookie_banner(page)
    page.wait_for_timeout(500)

    announced_total = _get_announced_total(page)
    n_loaded = _scroll_to_load_all(page)

    if announced_total is not None:
        print(f"    {n_loaded} fiches chargées après défilement complet "
              f"(site annonce {announced_total} au total).")
        if n_loaded < announced_total * 0.95:
            print(f"    [ALERTE] Défilement probablement incomplet : "
                  f"{n_loaded}/{announced_total} chargées seulement.")
    else:
        print(f"    {n_loaded} fiches chargées après défilement complet.")

    return _extract_brand_model_counts(page)


def scrape():
    rows = []
    now = dt.datetime.now().isoformat(timespec="seconds")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=50 if not HEADLESS else 0)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
            viewport={"width": 1400, "height": 1000},
        )
        page = context.new_page()

        try:
            for financetype in FINANCE_TYPES:
                print(f"\n=== Type de financement : {financetype} ===")

                print("  Catalogue complet (tous carburants)...")
                total_counts = _scrape_catalog(page, financetype)

                print("  Catalogue électrique uniquement...")
                electric_counts = _scrape_catalog(page, financetype, fueltype="ELECTRIC")

                all_keys = set(total_counts) | set(electric_counts)
                for (brand, model) in sorted(all_keys):
                    total = total_counts.get((brand, model), 0)
                    electric = electric_counts.get((brand, model), 0)
                    proportion = round(electric / total, 4) if total else 0.0
                    rows.append({
                        "date_releve": now,
                        "type_financement": financetype,
                        "marque": brand,
                        "modele": model,
                        "nb_total": total,
                        "nb_electrique": electric,
                        "proportion_electrique": proportion,
                    })

                print(f"  -> {len(all_keys)} couples marque/modèle distincts trouvés pour {financetype}.")
        finally:
            browser.close()

    return rows


def save_to_csv(rows, csv_path=CSV_PATH, max_retries=3):
    os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
    file_exists = os.path.exists(csv_path)

    for attempt in range(1, max_retries + 1):
        try:
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                if not file_exists:
                    writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            print(f"\n{len(rows)} lignes ajoutées à {csv_path}")
            return
        except PermissionError:
            if attempt < max_retries:
                print(f"[attention] {csv_path} semble ouvert ailleurs — nouvelle tentative dans 3s...")
                time.sleep(3)
            else:
                raise


if __name__ == "__main__":
    rows = scrape()
    save_to_csv(rows)

    print("\nRésumé combiné (leasing + cash) par marque :")
    combined = {}
    for r in rows:
        b = r["marque"]
        combined.setdefault(b, {"total": 0, "electrique": 0})
        combined[b]["total"] += r["nb_total"]
        combined[b]["electrique"] += r["nb_electrique"]

    for brand, c in sorted(combined.items(), key=lambda x: -x[1]["total"]):
        if c["total"] == 0:
            continue
        prop = c["electrique"] / c["total"]
        print(f"  {brand:15s} total={c['total']:4d}  electrique={c['electrique']:3d}  ({prop:.1%})")
