"""
scraper_modeles.py — Aramisauto, détail par modèle
=====================================================
Complète scraper.py : pour chaque marque, sélectionne la marque dans le
panneau de filtres puis lit l'onglet "Modèles" (qui n'apparaît qu'une fois
une marque sélectionnée — vu sur capture d'écran du site).

Fait ça sur les 2 pages :
  - https://www.aramisauto.com/achat/               -> total par modèle
  - https://www.aramisauto.com/achat/electrique/    -> électrique par modèle

⚠️ Plus lent que scraper.py : environ 2 chargements de page par marque
(total + électrique), donc peut prendre plusieurs minutes pour ~38 marques.
Pour les marques à 0 véhicule électrique (vues dans data/historique.csv),
on ne relit pas la page électrique — inutile, ça sera 0 pour tous les modèles.

USAGE
-----
    python scraper_modeles.py
        -> génère/complète data/historique_modeles.csv

    SCRAPER_HEADLESS=0 python scraper_modeles.py
        -> mode visible, pour observer/déboguer
"""

import csv
import datetime as dt
import os
import re
import sys

from playwright.sync_api import sync_playwright

from scraper_aramisauto import (
    URL_TOTAL, URL_ELECTRIC, HEADLESS,
    _click_first_visible, _dismiss_cookie_banner, _read_brand_counts,
)

CSV_PATH = "data/historique_modeles_aramisauto.csv"
CSV_FIELDS = ["date_releve", "marque", "modele", "nb_total", "nb_electrique", "proportion_electrique"]
BRAND_LEVEL_CSV = "data/historique_aramisauto.csv"  # généré par scraper_aramisauto.py

SCRAPER_MODELES_VERSION = "v3-cookie-retry-each-step"
print(f"[scraper_modeles] Module chargé — version: {SCRAPER_MODELES_VERSION}")

MODEL_COUNT_PATTERN = re.compile(r"^([A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9\-\.\s]{0,30})\s*\((\d+)\)\s*$")

STOP_HEADERS_AFTER_MODELS = {
    "prix", "mensualité", "mensualite", "carburants", "boîtes de vitesse",
    "boites de vitesse", "kilométrage", "kilometrage", "tout effacer",
    "masquer la liste",
}


def _open_panel_and_select_brand(page, brand, debug_tag=""):
    """Ouvre le panneau de filtres, sélectionne la marque donnée, puis
    bascule sur l'onglet 'Modèles'. Réutilise les briques de scraper.py."""
    page.wait_for_timeout(1500)
    _dismiss_cookie_banner(page)
    page.wait_for_timeout(500)

    if not (_click_first_visible(page, "Tous les filtres") or _click_first_visible(page, "Filtres")):
        page.screenshot(path=f"erreur_filtres_{debug_tag}.png", full_page=True)
        raise RuntimeError(f"Impossible d'ouvrir 'Tous les filtres' pour {brand} ({debug_tag})")
    page.wait_for_timeout(1200)

    # La modale cookies peut apparaître avec un léger délai après le chargement
    # de la page (vu en pratique : elle peut surgir APRÈS l'ouverture du
    # panneau de filtres et bloquer le clic suivant). On retente ici.
    _dismiss_cookie_banner(page)
    page.wait_for_timeout(500)

    if not _click_first_visible(page, "Marques", exact=True):
        page.screenshot(path=f"erreur_onglet_marques_{debug_tag}.png", full_page=True)
        raise RuntimeError(f"Impossible d'ouvrir l'onglet 'Marques' pour {brand} ({debug_tag})")
    page.wait_for_timeout(1200)

    # Étendre la liste complète A-Z si besoin (marques peu communes)
    for label in ["Voir toutes les marques", "Afficher la liste", "Afficher plus"]:
        _click_first_visible(page, label, timeout=1500)
    page.wait_for_timeout(500)
    _dismiss_cookie_banner(page)

    if not _click_first_visible(page, brand, exact=True):
        page.screenshot(path=f"erreur_selection_marque_{debug_tag}.png", full_page=True)
        raise RuntimeError(f"Impossible de sélectionner la marque '{brand}' ({debug_tag})")
    page.wait_for_timeout(1500)
    _dismiss_cookie_banner(page)

    if not _click_first_visible(page, "Modèles", exact=True):
        page.screenshot(path=f"erreur_onglet_modeles_{debug_tag}.png", full_page=True)
        raise RuntimeError(f"Impossible d'ouvrir l'onglet 'Modèles' pour {brand} ({debug_tag})")
    page.wait_for_timeout(1500)


def _read_model_counts(page):
    """Lit les compteurs 'Modèle (nombre)' affichés après avoir sélectionné
    une marque et ouvert l'onglet 'Modèles'."""
    full_text = page.inner_text("body")
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    start_idx = None
    for i, line in enumerate(lines):
        if line.lower() in ("modèles", "modeles"):
            start_idx = i + 1

    if start_idx is None:
        return {}

    counts = {}
    for line in lines[start_idx:]:
        if line.lower() in STOP_HEADERS_AFTER_MODELS:
            break
        m = MODEL_COUNT_PATTERN.match(line)
        if not m:
            continue
        model = m.group(1).strip()
        counts[model] = int(m.group(2))

    return counts


def get_models_for_brand(page, url, brand, debug_tag=""):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    _open_panel_and_select_brand(page, brand, debug_tag=debug_tag)
    counts = _read_model_counts(page)
    if not counts:
        print(f"  [attention] Aucun modèle trouvé pour {brand} sur {debug_tag} — "
              f"peut-être une marque à un seul modèle sans détail, ou structure changée.")
    return counts


def load_brands_from_previous_run():
    """Réutilise data/historique.csv (généré par scraper.py) pour connaître
    la liste des marques et savoir lesquelles ont au moins 1 véhicule
    électrique (pour éviter de relire inutilement la page électrique pour
    les marques à 0 électrique)."""
    if not os.path.exists(BRAND_LEVEL_CSV):
        raise RuntimeError(
            f"{BRAND_LEVEL_CSV} introuvable — lance d'abord `python scraper_aramisauto.py` "
            f"une fois pour obtenir la liste des marques."
        )
    brands = {}
    with open(BRAND_LEVEL_CSV, newline="", encoding="utf-8-sig") as f:
        first_line = f.readline()
        f.seek(0)
        # Détection simple et fiable : on compte les deux séparateurs possibles
        # sur la ligne d'en-tête, celui qui apparaît le plus est le bon.
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        rows = list(reader)

    if not rows:
        raise RuntimeError(f"{BRAND_LEVEL_CSV} est vide.")
    if "date_releve" not in rows[0]:
        raise RuntimeError(
            f"Colonnes inattendues dans {BRAND_LEVEL_CSV} : {list(rows[0].keys())} "
            f"(attendu notamment 'date_releve'). Le fichier a peut-être été modifié "
            f"ou corrompu — au besoin, supprime-le et relance `python scraper.py`."
        )

    last_date = max(r["date_releve"] for r in rows)
    for r in rows:
        if r["date_releve"] == last_date and int(r["nb_total"]) > 0:
            brands[r["marque"]] = int(r["nb_electrique"]) > 0
    return brands  # {marque: a_des_electriques (bool)}


def scrape_all_models(brands_filter=None):
    brands = load_brands_from_previous_run()
    if brands_filter:
        brands = {b: v for b, v in brands.items() if b in brands_filter}

    print(f"{len(brands)} marques à traiter.")
    rows = []
    now = dt.datetime.now().isoformat(timespec="seconds")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=100 if not HEADLESS else 0)
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
            for i, (brand, has_electric) in enumerate(brands.items(), 1):
                print(f"[{i}/{len(brands)}] {brand}...")
                try:
                    total_models = get_models_for_brand(page, URL_TOTAL, brand, debug_tag=f"total_{brand}")
                except Exception as e:
                    print(f"  ÉCHEC (total) pour {brand} : {e}")
                    continue

                electric_models = {}
                if has_electric:
                    try:
                        electric_models = get_models_for_brand(
                            page, URL_ELECTRIC, brand, debug_tag=f"electrique_{brand}"
                        )
                    except Exception as e:
                        print(f"  ÉCHEC (électrique) pour {brand} : {e}")

                for model in sorted(set(total_models) | set(electric_models)):
                    total = total_models.get(model, 0)
                    electric = electric_models.get(model, 0)
                    proportion = round(electric / total, 4) if total else 0.0
                    rows.append({
                        "date_releve": now,
                        "marque": brand,
                        "modele": model,
                        "nb_total": total,
                        "nb_electrique": electric,
                        "proportion_electrique": proportion,
                    })
        finally:
            browser.close()

    return rows


def save_to_csv(rows, csv_path=CSV_PATH):
    os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"\n{len(rows)} lignes ajoutées à {csv_path}")


if __name__ == "__main__":
    # Usage optionnel : python scraper_modeles.py Peugeot Tesla
    # (limite le traitement à certaines marques, pratique pour tester vite)
    brands_filter = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    rows = scrape_all_models(brands_filter)
    save_to_csv(rows)

    print("\nRésumé (trié par marque puis par total décroissant) :")
    for r in sorted(rows, key=lambda r: (r["marque"], -r["nb_total"])):
        if r["nb_total"] == 0:
            continue
        print(f"  {r['marque']:12s} {r['modele']:15s} total={r['nb_total']:4d}  "
              f"electrique={r['nb_electrique']:3d}  ({r['proportion_electrique']:.1%})")
