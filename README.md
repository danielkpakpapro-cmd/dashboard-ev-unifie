# Dashboard unifié — Proportion de véhicules électriques (Aramisauto + Ayvens)

Regroupe les scrapers d'Aramisauto et d'Ayvens (déjà validés dans leurs
projets respectifs) et affiche un seul dashboard avec un filtre pour
basculer entre les sites, ou tout voir en même temps.

## Structure

```
dashboard-ev-unifie/
├── scraper_aramisauto.py            # marque, quotidien
├── scraper_aramisauto_modeles.py    # marque + modèle, quotidien (plus long)
├── scraper_ayvens.py                # marque + modèle + type financement, quotidien
├── dashboard.py                      # dashboard unifié, filtre par site
├── .github/workflows/
│   ├── scraping-aramisauto.yml
│   ├── scraping-aramisauto-modeles.yml
│   └── scraping-ayvens.yml
├── requirements.txt                  # léger, pour le dashboard (Streamlit Cloud)
├── requirements-scraping.txt         # Playwright, pour les workflows uniquement
└── data/                             # généré automatiquement
    ├── historique_aramisauto.csv
    ├── historique_modeles_aramisauto.csv
    └── historique_ayvens.csv
```

## Mise en place

1. Crée un nouveau dépôt GitHub (privé si tu veux garder la même
   confidentialité que les projets existants), par exemple `dashboard-ev-unifie`.
2. Pousse ce dossier tel quel.
3. Déploie `dashboard.py` sur https://share.streamlit.io (comme pour les
   deux projets précédents — pense à autoriser l'accès au dépôt privé
   dans les paramètres GitHub de l'app Streamlit si besoin).
4. Les 3 workflows GitHub Actions tournent chacun indépendamment,
   chaque jour, et mettent à jour leur propre fichier CSV.

## Pourquoi 3 scrapers séparés plutôt qu'un seul ?

Chaque site a sa propre logique de scraping (facettes pour Aramisauto,
lecture des fiches véhicules pour Ayvens) et son propre rythme
(le détail par modèle Aramisauto prend 20-30 min, bien plus long que le
reste). Les garder séparés évite qu'un site en panne bloque les autres,
et permet de planifier des horaires différents pour éviter les collisions
de push sur le même dépôt.

## Ce que fait le dashboard

- Filtre par site (Aramisauto / Ayvens / les deux) dans la barre latérale
- Graphique marque par marque, coloré par site, avec le nombre de
  véhicules électriques affiché au-dessus de chaque barre
- Tableau détaillé filtrable par marque
- Détail par modèle pour Aramisauto (fichier séparé)
- Évolution dans le temps une fois plusieurs jours d'historique accumulés

## Note sur les anciens dépôts séparés

Les dépôts `aramisauto-ev` et `ayvens-ev` d'origine peuvent rester tels
quels (utiles pour déboguer un scraper individuellement) ou être
archivés une fois ce dashboard unifié validé — à toi de voir.
