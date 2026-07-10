"""
dashboard.py — Dashboard unifié (Aramisauto + Ayvens)
========================================================
Lit les CSV générés par les deux scrapers (mis à jour automatiquement
chaque jour par GitHub Actions) et propose un seul dashboard avec un
filtre pour basculer entre les sites, ou tout voir en même temps.

    data/historique_aramisauto.csv
    data/historique_ayvens.csv
    data/historique_modeles_aramisauto.csv  (optionnel, détail par modèle)

Lancement :
    pip install streamlit pandas plotly --break-system-packages
    streamlit run dashboard.py
"""

import os

import pandas as pd
import plotly.express as px
import streamlit as st

SOURCES = {
    "Aramisauto": "data/historique_aramisauto.csv",
    "Ayvens": "data/historique_ayvens.csv",
}
MODELS_CSV = {
    "Aramisauto": "data/historique_modeles_aramisauto.csv",
    # Ayvens a déjà le détail par modèle dans son CSV principal (voir plus bas)
}

st.set_page_config(page_title="Proportion électrique — Aramisauto & Ayvens", layout="wide")
st.title("🔋 Proportion de véhicules électriques — vue multi-sites")

# --- Chargement des données de chaque site ---
frames = []
for source_name, path in SOURCES.items():
    if not os.path.exists(path):
        st.warning(f"Pas encore de données pour {source_name} ({path} introuvable).")
        continue
    df = pd.read_csv(path, sep=None, engine="python")
    df["date_releve"] = pd.to_datetime(df["date_releve"], errors="coerce")
    df = df.dropna(subset=["date_releve"])
    df["source"] = source_name
    if "modele" not in df.columns:
        df["modele"] = ""
    if "type_financement" not in df.columns:
        df["type_financement"] = ""
    frames.append(df)

if not frames:
    st.error("Aucune donnée disponible pour aucun site. Lance d'abord les scrapers.")
    st.stop()

df_all = pd.concat(frames, ignore_index=True)

# --- Filtre par site ---
sites_dispo = sorted(df_all["source"].unique())
selected_sites = st.sidebar.multiselect("Sites", sites_dispo, default=sites_dispo)
df_all = df_all[df_all["source"].isin(selected_sites)] if selected_sites else df_all

if df_all.empty:
    st.info("Aucune donnée pour les sites sélectionnés.")
    st.stop()

# --- Pour chaque site, ne garder que son DERNIER relevé (les sites ne sont ---
# --- pas forcément scrapés au même moment) ---
latest_frames = []
for source_name in df_all["source"].unique():
    sub = df_all[df_all["source"] == source_name]
    last_date = sub["date_releve"].max()
    latest_frames.append(sub[sub["date_releve"] == last_date])
latest = pd.concat(latest_frames, ignore_index=True)
latest = latest[latest["nb_total"] > 0]

st.caption(
    "Dernier relevé par site : "
    + " · ".join(
        f"{s} → {df_all[df_all['source'] == s]['date_releve'].max().strftime('%d/%m/%Y %H:%M')}"
        for s in df_all["source"].unique()
    )
)

# --- KPI globaux ---
by_brand = latest.groupby(["source", "marque"])[["nb_total", "nb_electrique"]].sum().reset_index()
col1, col2, col3 = st.columns(3)
total_vehicules = by_brand["nb_total"].sum()
total_electriques = by_brand["nb_electrique"].sum()
prop_globale = (total_electriques / total_vehicules) if total_vehicules else 0
col1.metric("Véhicules (sites sélectionnés)", f"{total_vehicules:,}".replace(",", " "))
col2.metric("Dont électriques", f"{total_electriques:,}".replace(",", " "))
col3.metric("Proportion électrique globale", f"{prop_globale:.1%}")

st.divider()

# --- Graphique par marque, coloré par site ---
st.subheader("Proportion électrique par marque")
by_brand_prop = by_brand.copy()
by_brand_prop["proportion_electrique"] = by_brand_prop["nb_electrique"] / by_brand_prop["nb_total"]

fig = px.bar(
    by_brand_prop, x="marque", y="proportion_electrique", color="source",
    barmode="group",
    hover_data=["nb_total", "nb_electrique"],
    labels={"proportion_electrique": "% électrique", "marque": "Marque", "source": "Site"},
    text="nb_electrique",
)
fig.update_traces(texttemplate="%{text}", textposition="outside", textfont=dict(color="white", size=11))
fig.update_yaxes(tickformat=".0%", range=[0, by_brand_prop["proportion_electrique"].max() * 1.2 + 0.05])
st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- Tableau détaillé par marque (et modèle si disponible) ---
st.subheader("Détail par marque")

col_f1, col_f2 = st.columns([2, 1])
marques_dispo = sorted(latest["marque"].unique())
selected_marques = col_f1.multiselect("Filtrer par marque", marques_dispo, default=[])
only_electric = col_f2.checkbox("Uniquement avec ≥1 électrique")

detail = latest.copy()
if selected_marques:
    detail = detail[detail["marque"].isin(selected_marques)]
if only_electric:
    detail = detail[detail["nb_electrique"] > 0]

detail = detail.sort_values(["source", "marque"])
display_cols = ["source", "marque", "modele", "nb_total", "nb_electrique", "proportion_electrique"]
display_cols = [c for c in display_cols if c in detail.columns]

st.dataframe(
    detail[display_cols].rename(columns={
        "source": "Site", "marque": "Marque", "modele": "Modèle",
        "nb_total": "Total", "nb_electrique": "Électrique",
        "proportion_electrique": "% Électrique",
    }).style.format({"% Électrique": "{:.1%}"}),
    use_container_width=True,
    hide_index=True,
    height=450,
)

st.divider()

# --- Détail par modèle Aramisauto (fichier séparé, si présent) ---
if "Aramisauto" in selected_sites and os.path.exists(MODELS_CSV.get("Aramisauto", "")):
    st.subheader("Détail par modèle — Aramisauto")
    df_models = pd.read_csv(MODELS_CSV["Aramisauto"], sep=None, engine="python")
    df_models["date_releve"] = pd.to_datetime(df_models["date_releve"], errors="coerce")
    df_models = df_models.dropna(subset=["date_releve"])
    if not df_models.empty:
        last_date_models = df_models["date_releve"].max()
        detail_models = df_models[df_models["date_releve"] == last_date_models]
        detail_models = detail_models[detail_models["nb_total"] > 0]
        st.dataframe(
            detail_models[["marque", "modele", "nb_total", "nb_electrique", "proportion_electrique"]]
            .rename(columns={
                "marque": "Marque", "modele": "Modèle", "nb_total": "Total",
                "nb_electrique": "Électrique", "proportion_electrique": "% Électrique",
            }).style.format({"% Électrique": "{:.1%}"}),
            use_container_width=True,
            hide_index=True,
            height=400,
        )

st.divider()

# --- Évolution dans le temps ---
st.subheader("Évolution dans le temps")
if df_all["date_releve"].nunique() <= len(selected_sites):
    st.info("Pas encore assez d'historique pour tracer une évolution — "
            "ça se remplira au fil des exécutions automatiques quotidiennes.")
else:
    evo = df_all.groupby(["date_releve", "source"])[["nb_total", "nb_electrique"]].sum().reset_index()
    evo["proportion_electrique"] = evo["nb_electrique"] / evo["nb_total"]
    fig_evo = px.line(evo, x="date_releve", y="proportion_electrique", color="source", markers=True,
                       labels={"proportion_electrique": "% électrique", "source": "Site"})
    fig_evo.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig_evo, use_container_width=True)

st.divider()
st.caption("💡 Les données sont mises à jour automatiquement chaque jour (GitHub Actions), "
           "indépendamment pour chaque site.")
