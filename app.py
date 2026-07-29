"""
Grapper - Dashboard Streamlit (FICHIER UNIQUE, tout est ici).
Lance :  streamlit run app.py
"""
import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Grapper Dashboard", page_icon="\U0001F4CA", layout="wide")

MONTHS_FR = ["Jan", "Fév", "Mar", "Avr", "Mai", "Jui",
             "Jul", "Aoû", "Sep", "Oct", "Nov", "Déc"]

# =========================== COUCHE DONNEES ================================= #
SHEET_ID = "12mBncnRBlwWb2HQB-ySbwOtgTYzK8yenLLDsHBb5rX8"
SHEET_NAME = "Global1"
CLEAN_PLATFORMS = ["Tiktok", "IG", "IG reel", "IG Story",
                   "UGC", "Ad Code", "YT Short", "YT Intregration"]
STATUS_FAIT = "Fait"
STATUS_FACTURE = "Facture à envoyer"
GS_EPOCH = pd.Timestamp("1899-12-30")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
TTL = 600
MIN_YEAR = 2024


@st.cache_resource
def _client():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    return gspread.authorize(creds)


def _to_dt(values):
    s = pd.Series(list(values))
    nums = pd.to_numeric(s, errors="coerce")
    out = GS_EPOCH + pd.to_timedelta(nums, unit="D")
    mask = out.isna() & s.notna() & (s.astype(str).str.strip() != "")
    if mask.any():
        out.loc[mask] = pd.to_datetime(s[mask], errors="coerce", dayfirst=True, format="mixed")
    return out


def _tkey(talent):
    if not talent:
        return talent
    k = str(talent).split("@")[0].replace("grapperagency.com", "").rstrip(".").strip()
    return k or str(talent)


def _resolve_columns(header):
    named = {
        "Talents": "talent", "Date vente": "dateVente", "Marques": "marque",
        "Commission": "commission", "Status": "status", "Plateforme": "plateforme",
        "Facture envoyé": "facture", "Talent Manager": "manager",
        "Date Création": "created",
    }
    idx = {k: None for k in list(named.values()) + ["remun", "preview", "post"]}
    for i, h in enumerate(header):
        if h in named:
            idx[named[h]] = i
        if "mun" in h and "ration" in h:
            idx["remun"] = i
        if h == "Preview":
            idx["preview"] = i
        if h == "Post":
            idx["post"] = i
    return idx


@st.cache_data(ttl=TTL, show_spinner="Lecture du Google Sheet…")
def load_dataframe():
    ws = _client().open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    try:
        from gspread.utils import ValueRenderOption
        rows = ws.get_values(value_render_option=ValueRenderOption.unformatted)
    except Exception:
        rows = ws.get_all_values()
    if not rows or len(rows) < 2:
        return pd.DataFrame()

    header = [str(c).strip() for c in rows[0]]
    data = rows[1:]
    idx = _resolve_columns(header)

    def col(key):
        j = idx[key]
        if j is None:
            return [None] * len(data)
        return [r[j] if j < len(r) else None for r in data]

    def scol(key):
        return pd.Series(col(key)).fillna("").astype(str).str.strip()

    def ncol(key):
        return pd.to_numeric(pd.Series(col(key)), errors="coerce").fillna(0.0)

    df = pd.DataFrame({
        "talent": scol("talent"), "marque": scol("marque"), "status": scol("status"),
        "plateforme": scol("plateforme"), "manager": scol("manager"),
        "remun": ncol("remun"), "comm": ncol("commission"), "facture": ncol("facture"),
        "date_vente": _to_dt(col("dateVente")), "created": _to_dt(col("created")),
        "preview": _to_dt(col("preview")), "post": _to_dt(col("post")),
    })
    df["year"] = df["date_vente"].dt.year
    df["month"] = df["date_vente"].dt.month
    df["tkey"] = df["talent"].map(_tkey)
    return df


@st.cache_data(ttl=TTL)
def load_inactifs():
    """Noms (ou emails) des créateurs partis, listés dans un onglet 'Inactifs'."""
    try:
        ws = _client().open_by_key(SHEET_ID).worksheet("Inactifs")
        vals = ws.col_values(1)
    except Exception:
        return set()
    out = set()
    for v in vals:
        s = str(v).strip().lower()
        if s and s not in ("inactifs", "talent", "talents", "nom", "name"):
            out.add(s)
    return out


def _days_in_year(y):
    return pd.Timestamp(year=int(y), month=12, day=31).dayofyear


def _year_block(scope, y, today):
    dy = scope[scope["year"] == y]
    n = len(dy)
    total_ca = float(dy["remun"].sum())
    total_comm = float(dy["comm"].sum())
    active_mask = (dy["status"] != "") & (dy["status"] != STATUS_FAIT) & (dy["status"] != STATUS_FACTURE)

    if y == today.year:
        months_el = max(int(today.month), 1)
        days_el = max((today - pd.Timestamp(year=int(y), month=1, day=1)).days + 1, 1)
    elif y < today.year:
        months_el, days_el = 12, _days_in_year(y)
    else:
        months_el, days_el = 1, 1

    kpi = {
        "totalCA": int(round(total_ca)),
        "totalComm": int(round(total_comm)),
        "count": int(n),
        "actives": int(active_mask.sum()),
        "facturesAEnvoyer": int((dy["status"] == STATUS_FACTURE).sum()),
        "venduNonFacture": int(round(dy.loc[dy["status"] != STATUS_FAIT, "remun"].sum())),
        "caMoyen": int(round(total_ca / n)) if n else 0,
        "campsPerMonth": round(n / months_el, 1),
        "campsPerDay": round(n / days_el, 2),
        "tauxComm": round(total_comm / total_ca * 100, 1) if total_ca else 0.0,
        "nbMarques": int(dy.loc[(dy["remun"] > 0) & (dy["marque"] != ""), "marque"].nunique()),
        "nbTalents": int(dy.loc[dy["talent"] != "", "talent"].nunique()),
    }

    b = dy[(dy["remun"] > 0) & (dy["marque"] != "")]
    brands = b.groupby("marque").agg(
        budget=("remun", "sum"), volume=("remun", "size"), derniere=("date_vente", "max"))
    if not brands.empty:
        brands["budget"] = brands["budget"].round().astype(int)
        brands["volume"] = brands["volume"].astype(int)

    monthly = pd.DataFrame({"month": range(1, 13)})
    monthly["CA"] = monthly["month"].map(dy.groupby("month")["remun"].sum()).fillna(0).round().astype(int)
    monthly["Commission"] = monthly["month"].map(dy.groupby("month")["comm"].sum()).fillna(0).round().astype(int)

    return {"kpi": kpi, "brands": brands, "monthly": monthly}


def _talents(df, scope, years, today):
    if scope.empty:
        return pd.DataFrame()
    base = scope.groupby("talent").agg(
        name=("tkey", "first"), manager=("manager", "first"),
        last_sale=("date_vente", "max"))
    for y in years:
        dy = scope[scope["year"] == y]
        base = base.join(dy.groupby("talent")["remun"].sum().rename("ca_%d" % y))
        base = base.join(dy.groupby("talent")["comm"].sum().rename("comm_%d" % y))
        base = base.join(dy.groupby("talent").size().rename("camps_%d" % y))

    bm = scope[(scope["remun"] > 0) & (scope["marque"] != "")]
    counts = (bm.groupby(["talent", "marque"]).size().rename("n").reset_index()
              .sort_values("n", ascending=False))
    topbr = counts.groupby("talent")["marque"].apply(lambda s: ", ".join(list(s)[:3]))
    base = base.join(topbr.rename("top_brands"))
    base["top_brands"] = base["top_brands"].fillna("")

    base["days_inactive"] = (today - base["last_sale"]).dt.days.clip(lower=0)

    for c in base.columns:
        if c.startswith(("ca_", "comm_")):
            base[c] = base[c].fillna(0).round().astype(int)
        elif c.startswith("camps_"):
            base[c] = base[c].fillna(0).astype(int)
    return base.reset_index()


@st.cache_data(ttl=TTL, show_spinner="Calcul des agrégats…")
def compute_all():
    df = load_dataframe()
    if df.empty:
        return None
    today = pd.Timestamp(date.today())

    present = [int(y) for y in pd.Series(df["year"].dropna().unique())
               if MIN_YEAR <= int(y) <= today.year + 1]
    last = max(present) if present else 2026
    last = max(last, 2026)
    years = list(range(MIN_YEAR, last + 1))

    scope = df[df["year"].isin(years)].copy()
    scope["year"] = scope["year"].astype(int)
    scope["month"] = scope["month"].astype(int)

    year_data = {y: _year_block(scope, y, today) for y in years}
    talents = _talents(df, scope, years, today)

    return {
        "updated": pd.Timestamp.now(),
        "rows": int(len(df)),
        "years": years,
        "current_year": int(today.year),
        "current_month": int(today.month),
        "year_data": year_data,
        "talents": talents,
    }


# =============================== INTERFACE ================================== #
def eur(x):
    try:
        return f"{int(round(x)):,} €".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def pct(cur, prev):
    cur = np.asarray(cur, dtype=float)
    prev = np.asarray(prev, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(prev > 0, (cur - prev) / prev * 100.0, np.nan)
    return np.round(out, 0)


def bar_sorted(labels, values, ytitle="€", height=340):
    d = pd.DataFrame({"cat": list(labels), "val": list(values)})
    return alt.Chart(d).mark_bar().encode(
        x=alt.X("cat:N", sort="-y", title=None),
        y=alt.Y("val:Q", title=ytitle),
        tooltip=["cat", "val"],
    ).properties(height=height, width="container")


def monthly_chart(mdf):
    mdf = mdf.copy()
    mdf["Mois"] = [MONTHS_FR[i - 1] for i in mdf["month"]]
    long = mdf.melt(id_vars=["Mois"], value_vars=["CA", "Commission"],
                    var_name="Type", value_name="Montant")
    return alt.Chart(long).mark_bar().encode(
        x=alt.X("Mois:N", sort=MONTHS_FR, title=None),
        xOffset="Type:N",
        y=alt.Y("Montant:Q", title="€"),
        color=alt.Color("Type:N", title=None),
        tooltip=["Mois", "Type", "Montant"],
    ).properties(height=380, width="container")


with st.sidebar:
    st.title("\U0001F4CA Grapper")
    if st.button("\U0001F504 Rafraîchir les données", width="stretch"):
        st.cache_data.clear()
        st.rerun()

data = compute_all()
if data is None:
    st.error("Aucune donnée lue depuis le Sheet. Vérifie l'accès du compte de service.")
    st.stop()

years = data["years"]
with st.sidebar:
    year = st.radio("Année", sorted(years, reverse=True), index=0)

yd = data["year_data"][year]
prevd = data["year_data"].get(year - 1)
k = yd["kpi"]
kprev = prevd["kpi"] if prevd else None

st.caption(f"{data['rows']} lignes · mis à jour "
           f"{data['updated'].strftime('%d/%m/%Y %H:%M')} · cache {TTL // 60} min")


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
c[0].metric("Vendu non facturé", eur(k["venduNonFacture"]))
c[1].metric("Prix moyen / campagne", eur(k["caMoyen"]))
c[2].metric("Factures à envoyer", f"{k['facturesAEnvoyer']}")
c[3].metric("Talents actifs", f"{k['nbTalents']}")

c = st.columns(3)
c[0].metric("Campagnes / mois", f"{k['campsPerMonth']:.1f}")
c[1].metric("Campagnes / jour", f"{k['campsPerDay']:.2f}")
c[2].metric("Taux de commission", f"{k['tauxComm']:.1f} %")

st.divider()

tab_over, tab_comp, tab_brands, tab_talents = st.tabs(
    ["\U0001F4CA Vue d'ensemble", "\U0001F4C8 Comparaison N / N-1",
     "\U0001F3F7\uFE0F Marques", "\U0001F9D1\u200D\U0001F3A4 Talents"]
)

# ------------------------------- Vue d'ensemble ---------------------------- #
with tab_over:
    st.subheader(f"CA & commission par mois — {year}")
    st.altair_chart(monthly_chart(yd["monthly"]))

    tab = yd["monthly"].copy()
    tab["Mois"] = [MONTHS_FR[i - 1] for i in tab["month"]]
    tab["Cumul CA"] = tab["CA"].cumsum()
    tab["Cumul Comm"] = tab["Commission"].cumsum()
    disp = tab[["Mois", "CA", "Commission", "Cumul CA", "Cumul Comm"]]
    total = pd.DataFrame([{"Mois": "TOTAL", "CA": int(tab["CA"].sum()),
                           "Commission": int(tab["Commission"].sum()),
                           "Cumul CA": int(tab["CA"].sum()),
                           "Cumul Comm": int(tab["Commission"].sum())}])
    disp = pd.concat([disp, total], ignore_index=True)
    eurc = st.column_config.NumberColumn(format="%d €")
    st.dataframe(disp, hide_index=True, width="stretch",
                 column_config={"CA": eurc, "Commission": eurc,
                                "Cumul CA": eurc, "Cumul Comm": eurc})

# ------------------------------- Comparaison ------------------------------- #
with tab_comp:
    if not prevd:
        st.subheader(f"{year} vs {year - 1}")
        st.info(f"Pas de données pour {year - 1}.")
    else:
        cur, prv = yd["monthly"], prevd["monthly"]

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
                return f"{(a - b) / b * 100:+.0f}% vs {year - 1}" if (b and a is not None) else "—"

            st.subheader(f"\U0001F52E Estimation fin {year}")
            cc = st.columns(3)
            cc[0].metric(f"CA cumulé (Jan→{mth})", eur(cur_ca), gpct(cur_ca, prev_ca))
            cc[1].metric(f"Estimation CA {year}",
                         eur(est_ca) if est_ca is not None else "—",
                         gpct(est_ca, prev_ca_full) if est_ca is not None else None)
            cc[2].metric(f"Estimation Commission {year}",
                         eur(est_co) if est_co is not None else "—",
                         gpct(est_co, prev_co_full) if est_co is not None else None)
            st.caption(
                f"Projection basée sur la saisonnalité de {year - 1} : la part du CA "
                f"réalisée de janvier à {mth} l'an dernier est appliquée au cumul de {year}.")
            st.divider()

        st.subheader(f"{year} vs {year - 1} — mois par mois")
        comp = pd.DataFrame({"Mois": MONTHS_FR})
        comp[f"CA {year}"] = cur["CA"].values
        comp[f"CA {year - 1}"] = prv["CA"].values
        comp["Δ CA"] = comp[f"CA {year}"] - comp[f"CA {year - 1}"]
        comp["Δ CA %"] = pct(cur["CA"].values, prv["CA"].values)
        comp[f"Comm {year}"] = cur["Commission"].values
        comp[f"Comm {year - 1}"] = prv["Commission"].values
        comp["Δ Comm"] = comp[f"Comm {year}"] - comp[f"Comm {year - 1}"]

        cmp_long = pd.DataFrame({
            "Mois": MONTHS_FR * 2,
            "Année": [str(year)] * 12 + [str(year - 1)] * 12,
            "CA": list(cur["CA"].values) + list(prv["CA"].values)})
        st.altair_chart(alt.Chart(cmp_long).mark_bar().encode(
            x=alt.X("Mois:N", sort=MONTHS_FR, title=None),
            xOffset="Année:N",
            y=alt.Y("CA:Q", title="€"),
            color=alt.Color("Année:N", title=None),
            tooltip=["Mois", "Année", "CA"]).properties(height=340, width="container"))

        eurc = st.column_config.NumberColumn(format="%d €")
        st.dataframe(
            comp, hide_index=True, width="stretch",
            column_config={
                f"CA {year}": eurc, f"CA {year - 1}": eurc, "Δ CA": eurc,
                "Δ CA %": st.column_config.NumberColumn(format="%+d%%"),
                f"Comm {year}": eurc, f"Comm {year - 1}": eurc, "Δ Comm": eurc,
            })

# ------------------------------- Marques ----------------------------------- #
with tab_brands:
    st.subheader(f"Marques — {year} vs {year - 1}")
    cur = yd["brands"]
    if cur.empty:
        st.info("Aucune marque pour cette année.")
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
        m["Évol. %"] = pct(m[f"Budget {year}"].values, m[f"Budget {year - 1}"].values)
        m["Dernière campagne"] = cur["derniere"]
        m = m.reset_index().sort_values(f"Budget {year}", ascending=False)
        show = m.head(40)

        eurc = st.column_config.NumberColumn(format="%d €")
        st.dataframe(
            show[["marque", f"Budget {year}", f"Budget {year - 1}", "Évol. %",
                  f"Camp. {year}", f"Camp. {year - 1}", "Dernière campagne"]],
            hide_index=True, width="stretch",
            column_config={
                "marque": "Marque",
                f"Budget {year}": eurc, f"Budget {year - 1}": eurc,
                "Évol. %": st.column_config.NumberColumn(format="%+d%%"),
                "Dernière campagne": st.column_config.DateColumn(format="DD/MM/YYYY"),
            })
        st.caption("Clique un en-tête de colonne pour trier (croissant ↔ décroissant).")
        st.altair_chart(bar_sorted(show["marque"].head(20), show[f"Budget {year}"].head(20)))

# ------------------------------- Talents ----------------------------------- #
with tab_talents:
    st.subheader(f"Talents actifs — {year}")
    t = data["talents"]
    cay, commy, campsy = f"ca_{year}", f"comm_{year}", f"camps_{year}"
    if t.empty or campsy not in t.columns:
        st.info("Aucun talent.")
    else:
        inactifs = load_inactifs()
        if inactifs:
            keep = ~(t["name"].str.lower().isin(inactifs) | t["talent"].str.lower().isin(inactifs))
            t = t[keep]

        act = t[t[campsy] > 0].copy()
        if act.empty:
            st.info(f"Aucun talent actif en {year}.")
        else:
            noms = sorted(act["name"].unique())
            hide = st.multiselect("Masquer des talents (cette session)", noms)
            if hide:
                act = act[~act["name"].isin(hide)]

            days = act["days_inactive"].astype(int)
            seuil = int(max(45, np.percentile(days, 75))) if len(days) else 45

            act["prix_moyen"] = (act[cay] / act[campsy]).round().astype(int)
            act["depuis"] = days
            act["alerte"] = np.where(days > seuil, "\U0001F534", "")
            act["derniere"] = pd.to_datetime(act["last_sale"])
            act = act.sort_values(cay, ascending=False)

            st.altair_chart(bar_sorted(act["name"].head(15), act[cay].head(15)))

            cmax = max(int(act[cay].max()), 1)
            disp = act[["name", "manager", cay, "prix_moyen", campsy, commy,
                        "depuis", "alerte", "derniere", "top_brands"]]
            st.dataframe(
                disp, hide_index=True, width="stretch",
                column_config={
                    "name": "Talent", "manager": "Manager",
                    cay: st.column_config.ProgressColumn(
                        f"CA {year}", format="%d €", min_value=0, max_value=cmax),
                    "prix_moyen": st.column_config.NumberColumn("Prix moyen", format="%d €"),
                    campsy: "Campagnes",
                    commy: st.column_config.NumberColumn("Commission", format="%d €"),
                    "depuis": st.column_config.NumberColumn("Depuis dern. collab (j)", format="%d j"),
                    "alerte": "⚠️",
                    "derniere": st.column_config.DateColumn("Dernière vente", format="DD/MM/YYYY"),
                    "top_brands": "Top marques",
                })
            st.caption(
                f"\U0001F534 = pas de collab depuis plus de {seuil} jours "
                f"(seuil = 75e percentile des délais). "
                f"Pour retirer définitivement un créateur parti, ajoute son nom dans un "
                f"onglet « Inactifs » du Google Sheet (une ligne par nom).")
