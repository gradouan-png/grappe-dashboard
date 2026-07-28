"""
Grapper - Dashboard Streamlit.
Lance :  streamlit run app.py
"""
import numpy as np
import pandas as pd
import streamlit as st

import grapper_data as gd

st.set_page_config(page_title="Grapper Dashboard", page_icon="\U0001F4CA", layout="wide")

MONTHS_FR = ["Jan", "F\u00e9v", "Mar", "Avr", "Mai", "Jui",
             "Jul", "Ao\u00fb", "Sep", "Oct", "Nov", "D\u00e9c"]


def eur(x):
    try:
        return f"{int(round(x)):,} \u20ac".replace(",", " ")
    except (TypeError, ValueError):
        return "\u2014"


def pct(cur, prev):
    cur = np.asarray(cur, dtype=float)
    prev = np.asarray(prev, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(prev > 0, (cur - prev) / prev * 100.0, np.nan)
    return np.round(out, 0)


# --------------------------------------------------------------------------- #
with st.sidebar:
    st.title("\U0001F4CA Grapper")
    if st.button("\U0001F504 Rafra\u00eechir les donn\u00e9es", width="stretch"):
        st.cache_data.clear()
        st.rerun()

data = gd.compute_all()
if data is None:
    st.error("Aucune donn\u00e9e lue depuis le Sheet. V\u00e9rifie l'acc\u00e8s du compte de service.")
    st.stop()

years = data["years"]
with st.sidebar:
    year = st.radio("Ann\u00e9e", sorted(years, reverse=True), index=0)

yd = data["year_data"][year]
prevd = data["year_data"].get(year - 1)
k = yd["kpi"]
kprev = prevd["kpi"] if prevd else None

st.caption(f"{data['rows']} lignes \u00b7 mis \u00e0 jour "
           f"{data['updated'].strftime('%d/%m/%Y %H:%M')} \u00b7 cache {gd.TTL // 60} min")


def dm(key):
    return eur(k[key] - kprev[key]) if kprev else None


def dn(key):
    return f"{k[key] - kprev[key]:+d}" if kprev else None


c = st.columns(4)
c[0].metric("CA total", eur(k["totalCA"]), dm("totalCA"))
c[1].metric("Commission", eur(k["totalComm"]), dm("totalComm"))
c[2].metric("Campagnes vendues", f"{k['count']}", dn("count"))
c[3].metric("En cours (actives)", f"{k['actives']}")

c = st.columns(4)
c[0].metric("CA \u00e0 facturer", eur(k["aFacturer"]))
c[1].metric("Commission \u00e0 facturer", eur(k["commAFacturer"]))
c[2].metric("Prix moyen / campagne", eur(k["caMoyen"]))
c[3].metric("Factures \u00e0 envoyer", f"{k['facturesAEnvoyer']}")

c = st.columns(4)
c[0].metric("Campagnes / mois", f"{k['campsPerMonth']:.1f}")
c[1].metric("Campagnes / jour", f"{k['campsPerDay']:.2f}")
c[2].metric("Taux de commission", f"{k['tauxComm']:.1f} %")
c[3].metric("Talents actifs", f"{k['nbTalents']}")

st.divider()

tab_over, tab_comp, tab_brands, tab_talents = st.tabs(
    ["\U0001F4CA Vue d'ensemble", "\U0001F4C8 Comparaison N / N-1",
     "\U0001F3F7\uFE0F Marques", "\U0001F9D1\u200D\U0001F3A4 Talents"]
)

# --------------------------------------------------------------------------- #
with tab_over:
    left, right = st.columns([2, 1])
    with left:
        st.subheader(f"CA & commission par mois \u2014 {year}")
        m = yd["monthly"].copy()
        m.index = MONTHS_FR
        st.bar_chart(m[["CA", "Commission"]])
    with right:
        st.subheader("Statuts")
        if not yd["status"].empty:
            st.bar_chart(yd["status"])
        st.subheader("Plateformes")
        if not yd["plat"].empty:
            st.bar_chart(yd["plat"])

# --------------------------------------------------------------------------- #
with tab_comp:
    if not prevd:
        st.subheader(f"{year} vs {year - 1}")
        st.info(f"Pas de donn\u00e9es pour {year - 1}.")
    else:
        cur, prv = yd["monthly"], prevd["monthly"]

        # Estimation fin d'annee (seulement pour l'annee en cours)
        if year == data["current_year"]:
            m = data["current_month"]
            mth = MONTHS_FR[m - 1]
            cur_ca = float(cur["CA"].iloc[:m].sum())
            prev_ca = float(prv["CA"].iloc[:m].sum())
            prev_ca_full = float(prv["CA"].sum())
            cur_co = float(cur["Commission"].iloc[:m].sum())
            prev_co = float(prv["Commission"].iloc[:m].sum())
            prev_co_full = float(prv["Commission"].sum())
            share_ca = prev_ca / prev_ca_full if prev_ca_full else 0
            share_co = prev_co / prev_co_full if prev_co_full else 0
            est_ca = cur_ca / share_ca if share_ca > 0 else None
            est_co = cur_co / share_co if share_co > 0 else None

            def gpct(a, b):
                return f"{(a - b) / b * 100:+.0f}% vs {year - 1}" if (b and a is not None) else "\u2014"

            st.subheader(f"\U0001F52E Estimation fin {year}")
            cc = st.columns(3)
            cc[0].metric(f"CA cumul\u00e9 (Jan\u2192{mth})", eur(cur_ca), gpct(cur_ca, prev_ca))
            cc[1].metric(f"Estimation CA {year}",
                         eur(est_ca) if est_ca is not None else "\u2014",
                         gpct(est_ca, prev_ca_full) if est_ca is not None else None)
            cc[2].metric(f"Estimation Commission {year}",
                         eur(est_co) if est_co is not None else "\u2014",
                         gpct(est_co, prev_co_full) if est_co is not None else None)
            st.caption(
                f"Projection bas\u00e9e sur la saisonnalit\u00e9 de {year - 1} : la part du CA "
                f"r\u00e9alis\u00e9e de janvier \u00e0 {mth} l'an dernier est appliqu\u00e9e au cumul de {year}.")
            st.divider()

        st.subheader(f"{year} vs {year - 1} \u2014 mois par mois")
        comp = pd.DataFrame({"Mois": MONTHS_FR})
        comp[f"CA {year}"] = cur["CA"].values
        comp[f"CA {year - 1}"] = prv["CA"].values
        comp["\u0394 CA"] = comp[f"CA {year}"] - comp[f"CA {year - 1}"]
        comp["\u0394 CA %"] = pct(cur["CA"].values, prv["CA"].values)
        comp[f"Comm {year}"] = cur["Commission"].values
        comp[f"Comm {year - 1}"] = prv["Commission"].values
        comp["\u0394 Comm"] = comp[f"Comm {year}"] - comp[f"Comm {year - 1}"]

        st.bar_chart(pd.DataFrame(
            {f"CA {year}": cur["CA"].values, f"CA {year - 1}": prv["CA"].values},
            index=MONTHS_FR))

        eurc = st.column_config.NumberColumn(format="%d \u20ac")
        st.dataframe(
            comp, hide_index=True, width="stretch",
            column_config={
                f"CA {year}": eurc, f"CA {year - 1}": eurc, "\u0394 CA": eurc,
                "\u0394 CA %": st.column_config.NumberColumn(format="%+d%%"),
                f"Comm {year}": eurc, f"Comm {year - 1}": eurc, "\u0394 Comm": eurc,
            })

# --------------------------------------------------------------------------- #
with tab_brands:
    st.subheader(f"Marques \u2014 {year} vs {year - 1}")
    cur = yd["brands"]
    if cur.empty:
        st.info("Aucune marque pour cette ann\u00e9e.")
    else:
        prv = prevd["brands"] if (prevd and not prevd["brands"].empty) else None
        m = pd.DataFrame(index=cur.index)
        m[f"Budget {year}"] = cur["budget"].astype(int)
        m[f"Camp. {year}"] = cur["volume"].astype(int)
        if prv is not None:
            m[f"Budget {year - 1}"] = prv["budget"].reindex(cur.index).fillna(0).astype(int)
            m[f"Camp. {year - 1}"] = prv["volume"].reindex(cur.index).fillna(0).astype(int)
        else:
            m[f"Budget {year - 1}"] = 0
            m[f"Camp. {year - 1}"] = 0
        m["\u00c9vol. %"] = pct(m[f"Budget {year}"].values, m[f"Budget {year - 1}"].values)
        m["Derni\u00e8re campagne"] = cur["derniere"]
        m = m.reset_index().sort_values(f"Budget {year}", ascending=False)
        show = m.head(40)

        eurc = st.column_config.NumberColumn(format="%d \u20ac")
        st.dataframe(
            show[["marque", f"Budget {year}", f"Budget {year - 1}", "\u00c9vol. %",
                  f"Camp. {year}", f"Camp. {year - 1}", "Derni\u00e8re campagne"]],
            hide_index=True, width="stretch",
            column_config={
                "marque": "Marque",
                f"Budget {year}": eurc, f"Budget {year - 1}": eurc,
                "\u00c9vol. %": st.column_config.NumberColumn(format="%+d%%"),
                "Derni\u00e8re campagne": st.column_config.DateColumn(format="DD/MM/YYYY"),
            })
        st.caption("Clique un en-t\u00eate de colonne pour trier (croissant \u2194 d\u00e9croissant).")
        st.bar_chart(show.set_index("marque")[f"Budget {year}"].head(20))

# --------------------------------------------------------------------------- #
with tab_talents:
    st.subheader(f"Talents actifs \u2014 {year}")
    t = data["talents"]
    cay, commy, campsy = f"ca_{year}", f"comm_{year}", f"camps_{year}"
    if t.empty or campsy not in t.columns:
        st.info("Aucun talent.")
    else:
        act = t[t[campsy] > 0].copy()
        if act.empty:
            st.info(f"Aucun talent actif en {year}.")
        else:
            act["prix_moyen"] = (act[cay] / act[campsy]).round().astype(int)
            act["statut"] = np.where(
                act["en_cours"], "\U0001F7E2 En cours",
                "\u26AA " + act["days_inactive"].astype(int).astype(str) + " j")
            act["derniere"] = pd.to_datetime(act["last_sale"])
            act = act.sort_values(cay, ascending=False)

            st.bar_chart(act.set_index("name")[cay].head(15))

            cmax = max(int(act[cay].max()), 1)
            disp = act[["name", "manager", cay, "prix_moyen", campsy, commy,
                        "statut", "derniere", "top_brands"]]
            st.dataframe(
                disp, hide_index=True, width="stretch",
                column_config={
                    "name": "Talent", "manager": "Manager",
                    cay: st.column_config.ProgressColumn(
                        f"CA {year}", format="%d \u20ac", min_value=0, max_value=cmax),
                    "prix_moyen": st.column_config.NumberColumn("Prix moyen", format="%d \u20ac"),
                    campsy: "Campagnes",
                    commy: st.column_config.NumberColumn("Commission", format="%d \u20ac"),
                    "statut": "Statut",
                    "derniere": st.column_config.DateColumn("Derni\u00e8re vente", format="DD/MM/YYYY"),
                    "top_brands": "Top marques",
                })
            st.caption("\U0001F7E2 = campagne en cours \u00b7 \u26AA = inactif depuis N jours")
