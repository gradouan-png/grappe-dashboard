"""
Grapper – Dashboard Streamlit.
Lance :  streamlit run app.py
"""
import pandas as pd
import streamlit as st

import grapper_data as gd

st.set_page_config(page_title="Grapper Dashboard", page_icon="\U0001F4CA", layout="wide")


def eur(x):
    return f"{int(round(x)):,} \u20ac".replace(",", " ")


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.title("\U0001F4CA Grapper")
    if st.button("\U0001F504 Rafra\u00eechir les donn\u00e9es", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    year = st.radio("Ann\u00e9e", gd.YEARS[::-1], horizontal=True)

# One cached call feeds the whole page
data = gd.compute_all()
if data is None:
    st.error("Aucune donn\u00e9e lue depuis le Sheet. V\u00e9rifie l'acc\u00e8s du compte de service.")
    st.stop()

yb = data["years"][year]
prev = data["years"].get(year - 1)
k = yb["kpi"]

st.caption(
    f"{data['rows']} lignes \u00b7 mis \u00e0 jour {data['updated'].strftime('%d/%m/%Y %H:%M')} "
    f"\u00b7 cache {gd.TTL // 60} min"
)

# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #
def delta(cur, key):
    if not prev:
        return None
    d = cur - prev["kpi"][key]
    return eur(d) if key in ("totalCA", "totalComm") else f"{d:+d}"

c = st.columns(4)
c[0].metric("CA total", eur(k["totalCA"]), delta(k["totalCA"], "totalCA") if prev else None)
c[1].metric("Commission", eur(k["totalComm"]), delta(k["totalComm"], "totalComm") if prev else None)
c[2].metric("Campagnes", f"{k['count']}", delta(k["count"], "count") if prev else None)
c[3].metric("Actives", f"{k['actives']}")

c = st.columns(4)
c[0].metric("CA \u00e0 facturer", eur(k["aFacturer"]))
c[1].metric("Commission \u00e0 facturer", eur(k["commAFacturer"]))
c[2].metric("Factures \u00e0 envoyer", f"{k['facturesAEnvoyer']}")
c[3].metric("CA actives", eur(k["caActives"]))

st.divider()

# --------------------------------------------------------------------------- #
# Tabs
# --------------------------------------------------------------------------- #
t_over, t_brands, t_talents, t_plan, t_global = st.tabs(
    ["Vue d'ensemble", "Marques", "Talents", "Planning", "Global 3 ans"]
)

MONTHS_FR = ["Jan", "F\u00e9v", "Mar", "Avr", "Mai", "Jui",
             "Jul", "Ao\u00fb", "Sep", "Oct", "Nov", "D\u00e9c"]

with t_over:
    left, right = st.columns([2, 1])
    with left:
        st.subheader("CA & commission par mois")
        monthly = pd.DataFrame({
            "CA": yb["caFact"].reindex(range(1, 13)).fillna(0),
            "Commission": yb["benFact"].reindex(range(1, 13)).fillna(0),
        })
        monthly.index = MONTHS_FR
        st.bar_chart(monthly)
    with right:
        st.subheader("Statuts")
        if not yb["status"].empty:
            st.bar_chart(yb["status"])
        st.subheader("Plateformes")
        if not yb["plat"].empty:
            st.bar_chart(yb["plat"])

with t_brands:
    st.subheader(f"Top marques {year}")
    st.dataframe(
        yb["brands_top"],
        hide_index=True, use_container_width=True,
        column_config={
            "marque": "Marque",
            "volume": st.column_config.NumberColumn("Volume"),
            "budget": st.column_config.NumberColumn("Budget (\u20ac)", format="%d"),
            "ytd_growth_pct": st.column_config.NumberColumn("Croiss. YTD %", format="%+d%%"),
        },
    )
    if not yb["brands_top"].empty:
        st.bar_chart(yb["brands_top"].set_index("marque")["budget"])

with t_talents:
    st.subheader(f"Top talents par commission {year}")
    if not yb["talents"].empty:
        st.bar_chart(yb["talents"].head(20))

    st.subheader("Stats talents (actifs 2026)")
    ts = data["talents"].copy()
    if not ts.empty:
        ts["top_brands"] = ts["top_brands"].apply(lambda x: ", ".join(x))
        st.dataframe(
            ts[["name", "manager", "ca_2026", "ca_2025", "ca_2024",
                "comm_2026", "camps_2026", "camps_2025", "days_inactive", "top_brands"]],
            hide_index=True, use_container_width=True,
            column_config={
                "name": "Talent", "manager": "Manager",
                "ca_2026": st.column_config.NumberColumn("CA 2026", format="%d"),
                "ca_2025": st.column_config.NumberColumn("CA 2025", format="%d"),
                "ca_2024": st.column_config.NumberColumn("CA 2024", format="%d"),
                "comm_2026": st.column_config.NumberColumn("Comm 2026", format="%d"),
                "camps_2026": "Camp. 26", "camps_2025": "Camp. 25",
                "days_inactive": st.column_config.NumberColumn("Inactif (j)"),
                "top_brands": "Top marques",
            },
        )

with t_plan:
    pl = data["planning"]
    labels = {
        "previews": "\U0001F4C5 Previews \u00e0 venir",
        "posts": "\U0001F4E4 Posts \u00e0 venir",
        "revisions": "\u267B\uFE0F R\u00e9visions",
        "noDates": "\u2753 Sans date",
    }
    for key in ["previews", "posts", "revisions", "noDates"]:
        dfp = pl[key]
        st.subheader(f"{labels[key]} ({len(dfp)})")
        if dfp.empty:
            st.caption("Rien \u00e0 afficher.")
        else:
            st.dataframe(dfp, hide_index=True, use_container_width=True)

with t_global:
    at = data["alltime"]
    c = st.columns(3)
    c[0].metric("CA total (3 ans)", eur(at["totalCA"]))
    c[1].metric("Commission (3 ans)", eur(at["totalComm"]))
    c[2].metric("Campagnes", f"{at['count']}")
    st.subheader("Top marques (3 ans)")
    st.dataframe(
        at["brands"], hide_index=True, use_container_width=True,
        column_config={
            "marque": "Marque", "volume": "Volume",
            "budget": st.column_config.NumberColumn("Budget (\u20ac)", format="%d"),
        },
    )
    st.subheader("Top talents par commission (3 ans)")
    if not at["talents"].empty:
        st.bar_chart(at["talents"])
