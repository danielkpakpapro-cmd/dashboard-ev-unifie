"""
scraper.py — Aramisauto uniquement
===================================
Approche construite à partir de captures d'écran réelles du site (juillet 2026) :

  - https://www.aramisauto.com/achat/               -> catalogue complet
  - https://www.aramisauto.com/achat/electrique/    -> catalogue électrique uniquement

Les DEUX pages partagent le même panneau de filtres ("Tous les filtres" ->
onglet "Marques"), qui affiche une liste texte du type :

    Peugeot (78)
    Renault (98)
    ...

PRINCIPE : pas besoin de cliquer sur un filtre "carburant" dynamique (ce qui
s'est révélé fragile). On charge 2 URLs fixes, on ouvre le même panneau sur
les deux, on lit la liste de marques avec son compteur, et on calcule :

    proportion_electrique(marque) = compteur(page électrique) / compteur(page totale)

INSTALLATION
------------
    pip install playwright pandas --break-system-packages
    playwright install chromium

USAGE
-----
    python scraper.py
        -> lance un relevé, l'ajoute à data/historique.csv

    SCRAPER_HEADLESS=0 python scraper.py
        -> lance en mode visible (navigateur affiché), utile pour déboguer
           si le site a changé de structure entre-temps.
"""

import csv
import datetime as dt
import os
import re
import time

from playwright.sync_api import sync_playwright

URL_TOTAL = "https://www.aramisauto.com/achat/"
URL_ELECTRIC = "https://www.aramisauto.com/achat/electrique/"

CSV_PATH = "data/historique_aramisauto.csv"
CSV_FIELDS = ["date_releve", "marque", "nb_total", "nb_electrique", "proportion_electrique"]

HEADLESS = os.environ.get("SCRAPER_HEADLESS", "1") != "0"

# Motif pour lire "NomDeMarque (123)" ligne par ligne.
BRAND_COUNT_PATTERN = re.compile(r"^([A-Za-zÀ-ÖØ-öø-ÿ&\-\s]{2,30})\s*\((\d+)\)\s*$")


def _click_first_visible(page, label, exact=False, timeout=3000):
    try:
        locator = page.get_by_text(label, exact=exact)
        count = locator.count()
    except Exception:
        return False
    for i in range(count):
        try:
            el = locator.nth(i)
            if el.is_visible():
                el.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


def _dismiss_cookie_banner(page, expected_url_fragment="/achat/"):
    """Ferme un éventuel bandeau de consentement cookies qui pourrait
    recouvrir les boutons de filtre au premier chargement de la page.
    Sécurité : si le clic a fait naviguer vers une autre page (ex: une page
    'Gérer mes cookies' séparée plutôt qu'un simple bandeau), on revient en
    arrière immédiatement."""
    url_before = page.url
    for label in ["Tout accepter", "Accepter tout", "J'accepte", "Accepter et fermer", "Accepter"]:
        if _click_first_visible(page, label, timeout=2000):
            page.wait_for_timeout(1000)
            if expected_url_fragment not in page.url:
                print(f"[warning] Clic sur '{label}' a navigué vers {page.url} — retour arrière.")
                page.go_back(wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
            return True
    return False


def _open_brands_panel(page, debug_tag=""):
    """Ouvre le panneau de filtres puis l'onglet 'Marques'."""
    page.wait_for_timeout(2000)
    page.screenshot(path=f"avant_clic{debug_tag}.png", full_page=True)
    _dismiss_cookie_banner(page)
    page.wait_for_timeout(500)

    if not (_click_first_visible(page, "Tous les filtres") or _click_first_visible(page, "Filtres")):
        page.screenshot(path="erreur_filtres.png", full_page=True)
        raise RuntimeError(
            "Impossible de trouver/cliquer le bouton 'Tous les filtres' "
            "(capture sauvegardée dans erreur_filtres.png)"
        )
    page.wait_for_timeout(1500)

    # La modale cookies peut apparaître avec un léger délai (vu en pratique :
    # parfois après l'ouverture du panneau de filtres), on retente ici.
    _dismiss_cookie_banner(page)
    page.wait_for_timeout(500)

    if not _click_first_visible(page, "Marques", exact=True):
        page.screenshot(path="erreur_onglet_marques.png", full_page=True)
        raise RuntimeError(
            "Impossible de trouver/cliquer l'onglet 'Marques' "
            "(capture sauvegardée dans erreur_onglet_marques.png)"
        )
    page.wait_for_timeout(1500)

    # Au cas où la liste complète A-Z serait repliée derrière un bouton.
    # Sans effet si elle est déjà visible (cas observé par défaut).
    for label in ["Voir toutes les marques", "Afficher la liste", "Afficher plus"]:
        _click_first_visible(page, label, timeout=2000)


def _read_brand_counts(page):
    """Extrait les paires marque -> nombre depuis le texte visible de la page.
    On repart du DERNIER en-tête 'Marques'/'Toutes les marques' rencontré
    (celui qui précède la liste alphabétique complète), pour éviter de
    capter les compteurs de la section 'Catégories' (même format de texte)."""
    full_text = page.inner_text("body")
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    start_idx = None
    for i, line in enumerate(lines):
        if line.lower() in ("marques", "toutes les marques"):
            start_idx = i + 1  # on garde le dernier trouvé

    if start_idx is None:
        return {}

    stop_headers = {"modèles", "modeles", "prix", "mensualité", "mensualite",
                     "masquer la liste", "tout effacer"}

    counts = {}
    for line in lines[start_idx:]:
        if line.lower() in stop_headers:
            break
        m = BRAND_COUNT_PATTERN.match(line)
        if not m:
            continue
        brand = m.group(1).strip()
        if brand.lower().startswith("toutes les marques"):
            continue
        counts[brand] = int(m.group(2))

    return counts


def _get_counts_for_url(page, url, debug_tag=""):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    _open_brands_panel(page, debug_tag=debug_tag)
    counts = _read_brand_counts(page)
    if not counts:
        raise RuntimeError(
            f"Aucune marque trouvée sur {url} — la structure du site a peut-être "
            f"changé. Relance avec SCRAPER_HEADLESS=0 pour observer le navigateur."
        )
    return counts


def scrape():
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
            print("Lecture du catalogue total...")
            total_counts = _get_counts_for_url(page, URL_TOTAL, debug_tag="_total")
            print(f"  -> {len(total_counts)} marques trouvées, "
                  f"{sum(total_counts.values())} véhicules au total")

            print("Lecture du catalogue électrique...")
            electric_counts = _get_counts_for_url(page, URL_ELECTRIC, debug_tag="_electrique")
            print(f"  -> {len(electric_counts)} marques trouvées, "
                  f"{sum(electric_counts.values())} véhicules électriques")
        finally:
            browser.close()

    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for brand in sorted(set(total_counts) | set(electric_counts)):
        total = total_counts.get(brand, 0)
        electric = electric_counts.get(brand, 0)
        proportion = round(electric / total, 4) if total else 0.0
        rows.append({
            "date_releve": now,
            "marque": brand,
            "nb_total": total,
            "nb_electrique": electric,
            "proportion_electrique": proportion,
        })
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
                print(f"[attention] {csv_path} semble ouvert dans un autre programme "
                      f"(Excel, Notepad...) — nouvelle tentative dans 3s "
                      f"({attempt}/{max_retries})...")
                time.sleep(3)
            else:
                raise PermissionError(
                    f"Impossible d'écrire dans {csv_path} : le fichier est probablement "
                    f"ouvert dans un autre programme (Excel, Notepad...). "
                    f"Ferme ce programme puis relance."
                )


if __name__ == "__main__":
    rows = scrape()
    save_to_csv(rows)

    print("\nRésumé (trié par nombre total décroissant) :")
    for r in sorted(rows, key=lambda r: -r["nb_total"]):
        if r["nb_total"] == 0:
            continue
        print(f"  {r['marque']:15s} total={r['nb_total']:5d}  "
              f"electrique={r['nb_electrique']:4d}  ({r['proportion_electrique']:.1%})")
