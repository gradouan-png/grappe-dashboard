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
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
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
    """Liste (brute) des créateurs marqués partis, dans l'onglet 'Inactifs'."""
    try:
        ws = _client().open_by_key(SHEET_ID).worksheet("Inactifs")
        vals = ws.col_values(1)
    except Exception:
        return []
    out = []
    for v in vals:
        s = str(v).strip()
        if s and s.lower() not in ("inactifs", "talent", "talents", "nom", "name"):
            out.append(s)
    return out


def _write_inactifs(names):
    """Réécrit entièrement l'onglet 'Inactifs' (le crée s'il n'existe pas)."""
    ss = _client().open_by_key(SHEET_ID)
    try:
        ws = ss.worksheet("Inactifs")
    except Exception:
        ws = ss.add_worksheet(title="Inactifs", rows=200, cols=1)
    ws.clear()
    body = [["Inactifs"]] + [[n] for n in sorted(set(names))]
    ws.update(range_name="A1", values=body)


def apply_inactifs(new_names):
    """Écrit + vide le cache. Renvoie True si OK, sinon affiche l'erreur."""
    try:
        _write_inactifs(new_names)
    except Exception as e:
        st.error("Impossible d'écrire dans le Sheet. Il faut le partager en **\u00c9diteur** "
                 "avec dashboard@grappe-gifting.iam.gserviceaccount.com.\n\nD\u00e9tail : %s" % e)
        return False
    st.cache_data.clear()
    return True


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
    monthly["Campagnes"] = monthly["month"].map(dy.groupby("month").size()).fillna(0).astype(int)
    monthly["Nb"] = monthly["month"].map(dy.groupby("month").size()).fillna(0).astype(int)

    pipe = dy[(dy["status"] != STATUS_FAIT) & (dy["status"] != "")]
    pipeline = pipe.groupby("status").agg(montant=("remun", "sum"), nb=("remun", "size"))
    if not pipeline.empty:
        pipeline["montant"] = pipeline["montant"].round().astype(int)
        pipeline["nb"] = pipeline["nb"].astype(int)

    return {"kpi": kpi, "brands": brands, "monthly": monthly, "pipeline": pipeline}


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


def _managers(scope, years):
    if scope.empty:
        return pd.DataFrame()
    mgr = sorted(scope.loc[scope["manager"] != "", "manager"].unique())
    base = pd.DataFrame(index=mgr)
    for y in years:
        dy = scope[scope["year"] == y]
        base = base.join(dy.groupby("manager")["remun"].sum().rename("ca_%d" % y))
        base = base.join(dy.groupby("manager")["comm"].sum().rename("comm_%d" % y))
        base = base.join(dy.groupby("manager").size().rename("camps_%d" % y))
        base = base.join(dy.groupby("manager")["talent"].nunique().rename("tal_%d" % y))
    for c in base.columns:
        if c.startswith(("ca_", "comm_")):
            base[c] = base[c].fillna(0).round().astype(int)
        else:
            base[c] = base[c].fillna(0).astype(int)
    return base.reset_index().rename(columns={"index": "manager"})


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
    managers = _managers(scope, years)
    vnf_global = int(round(df.loc[df["status"] != STATUS_FAIT, "remun"].sum()))

    bm = scope[(scope["remun"] > 0) & (scope["marque"] != "")]
    if bm.empty:
        brand_year = pd.DataFrame()
        brand_last = pd.Series(dtype="datetime64[ns]")
    else:
        brand_year = bm.pivot_table(index="marque", columns="year", values="remun",
                                    aggfunc="sum", fill_value=0).round().astype(int)
        brand_last = bm.groupby("marque")["date_vente"].max()

    return {
        "updated": pd.Timestamp.now(),
        "rows": int(len(df)),
        "years": years,
        "current_year": int(today.year),
        "current_month": int(today.month),
        "year_data": year_data,
        "talents": talents,
        "managers": managers,
        "vnf_global": vnf_global,
        "brand_year": brand_year,
        "brand_last": brand_last,
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
        y=alt.Y("val:Q", title=ytitle), tooltip=["cat", "val"],
    ).properties(height=height, width="container")


def monthly_chart(mdf):
    mdf = mdf.copy()
    mdf["Mois"] = [MONTHS_FR[i - 1] for i in mdf["month"]]
    long = mdf.melt(id_vars=["Mois"], value_vars=["CA", "Commission"],
                    var_name="Type", value_name="Montant")
    return alt.Chart(long).mark_bar().encode(
        x=alt.X("Mois:N", sort=MONTHS_FR, title=None), xOffset="Type:N",
        y=alt.Y("Montant:Q", title="€"), color=alt.Color("Type:N", title=None),
        tooltip=["Mois", "Type", "Montant"]).properties(height=380, width="container")


def month_bar(mdf, col, ytitle):
    d = mdf.copy()
    d["Mois"] = [MONTHS_FR[i - 1] for i in d["month"]]
    return alt.Chart(d).mark_bar().encode(
        x=alt.X("Mois:N", sort=MONTHS_FR, title=None),
        y=alt.Y(col + ":Q", title=ytitle), tooltip=["Mois", col],
    ).properties(height=360, width="container")


try:
    MANAGER_CODE = str(st.secrets["access"]["code"])
except Exception:
    MANAGER_CODE = ""

with st.sidebar:
    st.title("📊 Grapper")
    if st.button("🔄 Rafraîchir les données", width="stretch"):
        st.cache_data.clear()
        st.rerun()

data = compute_all()
if data is None:
    st.error("Aucune donnée lue depuis le Sheet. Vérifie l'accès du compte de service.")
    st.stop()

years = data["years"]
with st.sidebar:
    year = st.radio("Année", sorted(years, reverse=True), index=0)

# --- Accès données financières : champ masqué, révélé par Cmd/Ctrl + D ---
if "full" not in st.session_state:
    st.session_state.full = (not MANAGER_CODE)

# Déverrouillage instantané par lien secret :  ...streamlit.app/?key=LECODE
if MANAGER_CODE and st.query_params.get("key") == MANAGER_CODE:
    st.session_state.full = True
    st.query_params.clear()
    st.rerun()

import streamlit.components.v1 as components
components.html(
    """
    <script>
    (function(){
        function handler(e){
            if ((e.metaKey || e.ctrlKey) && e.shiftKey &&
                (e.key === 'u' || e.key === 'U' || e.code === 'KeyU')) {
                e.preventDefault();
                var w = window.parent || window;
                try {
                    var u = new URL(w.location.href);
                    u.searchParams.set('unlock', '1');
                    w.location.href = u.toString();
                } catch (err) {
                    var u2 = new URL(window.location.href);
                    u2.searchParams.set('unlock', '1');
                    window.location.href = u2.toString();
                }
            }
        }
        try { window.parent.document.addEventListener('keydown', handler, true); } catch (e) {}
        try { document.addEventListener('keydown', handler, true); } catch (e) {}
    })();
    </script>
    """, height=0)


@st.dialog("Accès données financières")
def _unlock():
    st.write("Saisis le code pour afficher les données financières.")
    code_in = st.text_input("Code", type="password")
    col1, col2 = st.columns(2)
    if col1.button("Déverrouiller", width="stretch"):
        if MANAGER_CODE and code_in == MANAGER_CODE:
            st.session_state.full = True
            st.query_params.clear()
            st.rerun()
        else:
            st.error("Code incorrect.")
    if col2.button("Annuler", width="stretch"):
        st.query_params.clear()
        st.rerun()


if "unlock" in st.query_params and not st.session_state.full:
    _unlock()

full = st.session_state.full
with st.sidebar:
    st.caption("🔓 Vue complète" if full else "🔒 Vue restreinte")
    if full and MANAGER_CODE and st.button("🔒 Verrouiller", width="stretch"):
        st.session_state.full = False
        st.rerun()
    if not MANAGER_CODE:
        st.caption("⚠️ Configure [access] / code dans les Secrets.")

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


if full:
    c = st.columns(4)
    c[0].metric("CA total", eur(k["totalCA"]), dm("totalCA"))
    c[1].metric("Commission", eur(k["totalComm"]), dm("totalComm"))
    c[2].metric("Campagnes vendues", f"{k['count']}", dn("count"))
    c[3].metric("En cours (actives)", f"{k['actives']}")
    c = st.columns(4)
    c[0].metric("Vendu non facturé (global)", eur(data["vnf_global"]))
    c[1].metric("Prix moyen / campagne", eur(k["caMoyen"]))
    c[2].metric("Factures à envoyer", f"{k['facturesAEnvoyer']}")
    c[3].metric("Talents actifs", f"{k['nbTalents']}")
    c = st.columns(3)
    c[0].metric("Campagnes / mois", f"{k['campsPerMonth']:.1f}")
    c[1].metric("Campagnes / jour", f"{k['campsPerDay']:.2f}")
    c[2].metric("Taux de commission", f"{k['tauxComm']:.1f} %")
else:
    c = st.columns(4)
    c[0].metric("Campagnes vendues", f"{k['count']}", dn("count"))
    c[1].metric("En cours (actives)", f"{k['actives']}")
    c[2].metric("Factures à envoyer", f"{k['facturesAEnvoyer']}")
    c[3].metric("Talents actifs", f"{k['nbTalents']}")
    c = st.columns(2)
    c[0].metric("Campagnes / mois", f"{k['campsPerMonth']:.1f}")
    c[1].metric("Campagnes / jour", f"{k['campsPerDay']:.2f}")

st.divider()

tab_over, tab_comp, tab_pipe, tab_brands, tab_talents, tab_mgr = st.tabs(
    ["📊 Vue d'ensemble", "📈 Comparaison N / N-1", "💼 Pipeline",
     "🏷️ Marques", "🧑‍🎤 Talents", "👔 Managers"])

with tab_over:
    if full:
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
    else:
        st.subheader(f"Campagnes par mois — {year}")
        st.altair_chart(month_bar(yd["monthly"], "Campagnes", "Campagnes"))
        tab = yd["monthly"].copy()
        tab["Mois"] = [MONTHS_FR[i - 1] for i in tab["month"]]
        disp = tab[["Mois", "Campagnes"]]
        total = pd.DataFrame([{"Mois": "TOTAL", "Campagnes": int(tab["Campagnes"].sum())}])
        st.dataframe(pd.concat([disp, total], ignore_index=True), hide_index=True, width="stretch")

with tab_comp:
    if not prevd:
        st.subheader(f"{year} vs {year - 1}")
        st.info(f"Pas de données pour {year - 1}.")
    else:
        cur, prv = yd["monthly"], prevd["monthly"]
        if full:
            if year == data["current_year"]:
                mm = data["current_month"]
                mth = MONTHS_FR[mm - 1]
                cur_ca = float(cur["CA"].iloc[:mm].sum())
                prev_ca = float(prv["CA"].iloc[:mm].sum())
                prev_ca_full = float(prv["CA"].sum())
                cur_co = float(cur["Commission"].iloc[:mm].sum())
                prev_co = float(prv["Commission"].iloc[:mm].sum())
                prev_co_full = float(prv["Commission"].sum())
                share_ca = prev_ca / prev_ca_full if prev_ca_full else 0
                share_co = prev_co / prev_co_full if prev_co_full else 0
                est_ca = cur_ca / share_ca if share_ca > 0 else None
                est_co = cur_co / share_co if share_co > 0 else None

                def gpct(a, b):
                    return f"{(a - b) / b * 100:+.0f}% vs {year - 1}" if (b and a is not None) else "—"

                st.subheader(f"🔮 Estimation fin {year}")
                cc = st.columns(3)
                cc[0].metric(f"CA cumulé (Jan→{mth})", eur(cur_ca), gpct(cur_ca, prev_ca))
                cc[1].metric(f"Estimation CA {year}", eur(est_ca) if est_ca is not None else "—",
                             gpct(est_ca, prev_ca_full) if est_ca is not None else None)
                cc[2].metric(f"Estimation Commission {year}", eur(est_co) if est_co is not None else "—",
                             gpct(est_co, prev_co_full) if est_co is not None else None)
                st.caption(f"Projection basée sur la saisonnalité de {year - 1}.")
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
            cmp_long = pd.DataFrame({"Mois": MONTHS_FR * 2,
                                     "Année": [str(year)] * 12 + [str(year - 1)] * 12,
                                     "CA": list(cur["CA"].values) + list(prv["CA"].values)})
            st.altair_chart(alt.Chart(cmp_long).mark_bar().encode(
                x=alt.X("Mois:N", sort=MONTHS_FR, title=None), xOffset="Année:N",
                y=alt.Y("CA:Q", title="€"), color=alt.Color("Année:N", title=None),
                tooltip=["Mois", "Année", "CA"]).properties(height=340, width="container"))
            eurc = st.column_config.NumberColumn(format="%d €")
            st.dataframe(comp, hide_index=True, width="stretch", column_config={
                f"CA {year}": eurc, f"CA {year - 1}": eurc, "Δ CA": eurc,
                "Δ CA %": st.column_config.NumberColumn(format="%+d%%"),
                f"Comm {year}": eurc, f"Comm {year - 1}": eurc, "Δ Comm": eurc})
        else:
            st.subheader(f"Campagnes {year} vs {year - 1} — mois par mois")
            comp = pd.DataFrame({"Mois": MONTHS_FR})
            comp[f"Camp. {year}"] = cur["Campagnes"].values
            comp[f"Camp. {year - 1}"] = prv["Campagnes"].values
            comp["Δ"] = comp[f"Camp. {year}"] - comp[f"Camp. {year - 1}"]
            cmp_long = pd.DataFrame({"Mois": MONTHS_FR * 2,
                                     "Année": [str(year)] * 12 + [str(year - 1)] * 12,
                                     "Campagnes": list(cur["Campagnes"].values) + list(prv["Campagnes"].values)})
            st.altair_chart(alt.Chart(cmp_long).mark_bar().encode(
                x=alt.X("Mois:N", sort=MONTHS_FR, title=None), xOffset="Année:N",
                y=alt.Y("Campagnes:Q"), color=alt.Color("Année:N", title=None),
                tooltip=["Mois", "Année", "Campagnes"]).properties(height=340, width="container"))
            st.dataframe(comp, hide_index=True, width="stretch")

with tab_pipe:
    pl = yd["pipeline"]
    if pl.empty:
        st.subheader(f"Pipeline — {year}")
        st.info("Aucune campagne en cours (hors « Fait »).")
    else:
        p = pl.reset_index().sort_values("montant" if full else "nb", ascending=False)
        if full:
            st.subheader(f"Pipeline par statut (en €) — {year}")
            st.metric("Total en pipeline (hors « Fait »)", eur(int(p["montant"].sum())))
            st.altair_chart(bar_sorted(p["status"], p["montant"]))
            st.dataframe(p.rename(columns={"status": "Statut", "montant": "Montant", "nb": "Nb campagnes"}),
                         hide_index=True, width="stretch",
                         column_config={"Montant": st.column_config.NumberColumn(format="%d €")})
        else:
            st.subheader(f"Pipeline par statut (nb campagnes) — {year}")
            st.metric("Campagnes en cours (hors « Fait »)", f"{int(p['nb'].sum())}")
            st.altair_chart(bar_sorted(p["status"], p["nb"], ytitle="Campagnes"))
            st.dataframe(p[["status", "nb"]].rename(columns={"status": "Statut", "nb": "Nb campagnes"}),
                         hide_index=True, width="stretch")

with tab_brands:
    cur = yd["brands"]
    st.subheader(f"Marques — {year} vs {year - 1}")
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
        if full:
            st.dataframe(show[["marque", f"Budget {year}", f"Budget {year - 1}", "Évol. %",
                               f"Camp. {year}", f"Camp. {year - 1}", "Dernière campagne"]],
                         hide_index=True, width="stretch", column_config={
                             "marque": "Marque", f"Budget {year}": eurc, f"Budget {year - 1}": eurc,
                             "Évol. %": st.column_config.NumberColumn(format="%+d%%"),
                             "Dernière campagne": st.column_config.DateColumn(format="DD/MM/YYYY")})
            st.altair_chart(bar_sorted(show["marque"].head(20), show[f"Budget {year}"].head(20)))
        else:
            sc = show.sort_values(f"Camp. {year}", ascending=False)
            st.dataframe(sc[["marque", f"Camp. {year}", f"Camp. {year - 1}", "Dernière campagne"]],
                         hide_index=True, width="stretch", column_config={
                             "marque": "Marque",
                             "Dernière campagne": st.column_config.DateColumn(format="DD/MM/YYYY")})
            st.altair_chart(bar_sorted(sc["marque"].head(20), sc[f"Camp. {year}"].head(20), ytitle="Campagnes"))
        st.caption("Clique un en-tête de colonne pour trier.")

    by = data["brand_year"]
    bl = data["brand_last"]
    st.divider()
    st.subheader("😴 Marques à relancer (dormantes)")
    if by.empty or year not in by.columns:
        st.info("Pas assez d'historique.")
    else:
        prior = [c for c in by.columns if c < year]
        if not prior:
            st.info(f"Pas d'année avant {year} pour comparer.")
        else:
            dormant = by[(by[prior].sum(axis=1) > 0) & (by[year] == 0)]
            if dormant.empty:
                st.success("Aucune marque dormante 🎉")
            else:
                rows = []
                for marque in dormant.index:
                    last_y = max([y2 for y2 in prior if by.loc[marque, y2] > 0])
                    rows.append({"Marque": marque, "Dernier budget": int(by.loc[marque, last_y]),
                                 "Dernière année": int(last_y), "Dernière campagne": bl.get(marque)})
                d = pd.DataFrame(rows).sort_values("Dernier budget", ascending=False)
                st.caption(f"Actives avant {year}, aucune campagne en {year}.")
                if full:
                    st.dataframe(d, hide_index=True, width="stretch", column_config={
                        "Dernier budget": st.column_config.NumberColumn(format="%d €"),
                        "Dernière campagne": st.column_config.DateColumn(format="DD/MM/YYYY")})
                else:
                    st.dataframe(d[["Marque", "Dernière année", "Dernière campagne"]].sort_values(
                        "Dernière année", ascending=False), hide_index=True, width="stretch",
                        column_config={"Dernière campagne": st.column_config.DateColumn(format="DD/MM/YYYY")})

    st.divider()
    st.subheader("🆕 Nouvelles marques vs récurrentes")
    if by.empty or year not in by.columns:
        st.info("Pas de données.")
    else:
        prior = [c for c in by.columns if c < year]
        now = by[by[year] > 0]
        if now.empty:
            st.info(f"Aucune marque en {year}.")
        elif not prior:
            st.caption(f"Pas d'historique avant {year} : distinction impossible.")
        else:
            prior_sum = by[prior].sum(axis=1)
            new_mask = np.array([prior_sum.get(mq, 0) == 0 for mq in now.index])
            nb_new = int(new_mask.sum())
            nb_rec = int(len(now) - nb_new)
            if full:
                ca_new = int(now[year].values[new_mask].sum())
                ca_rec = int(now[year].sum() - ca_new)
                cc = st.columns(4)
                cc[0].metric("Nouvelles marques", f"{nb_new}")
                cc[1].metric("CA nouvelles", eur(ca_new))
                cc[2].metric("Marques récurrentes", f"{nb_rec}")
                cc[3].metric("CA récurrentes", eur(ca_rec))
            else:
                cc = st.columns(2)
                cc[0].metric("Nouvelles marques", f"{nb_new}")
                cc[1].metric("Marques récurrentes", f"{nb_rec}")
            new_list = now[new_mask].sort_values(year, ascending=False)
            if not new_list.empty:
                st.caption("Nouvelles marques acquises cette année :")
                if full:
                    nl = pd.DataFrame({"Marque": new_list.index, f"CA {year}": new_list[year].astype(int)})
                    st.dataframe(nl, hide_index=True, width="stretch",
                                 column_config={f"CA {year}": st.column_config.NumberColumn(format="%d €")})
                else:
                    st.dataframe(pd.DataFrame({"Marque": new_list.index}), hide_index=True, width="stretch")

with tab_talents:
    st.subheader(f"Talents actifs — {year}")
    t = data["talents"]
    cay, commy, campsy = f"ca_{year}", f"comm_{year}", f"camps_{year}"
    if t.empty or campsy not in t.columns:
        st.info("Aucun talent.")
    else:
        inactifs = load_inactifs()
        low = {x.lower() for x in inactifs}
        if full:
            with st.expander("⚙️ Gérer les créateurs (retirer / réactiver)"):
                all_names = sorted(data["talents"]["name"].unique())
                choix = [n for n in all_names if n.lower() not in low]
                a_retirer = st.multiselect("Retirer des créateurs partis", choix)
                if st.button("Retirer définitivement", disabled=not a_retirer):
                    if apply_inactifs(set(inactifs) | set(a_retirer)):
                        st.rerun()
                if inactifs:
                    a_react = st.multiselect("Réactiver des créateurs", sorted(inactifs))
                    if st.button("Réactiver", disabled=not a_react):
                        if apply_inactifs(set(inactifs) - set(a_react)):
                            st.rerun()
                    st.caption("Actuellement masqués : " + ", ".join(sorted(inactifs)))
        if low:
            t = t[~(t["name"].str.lower().isin(low) | t["talent"].str.lower().isin(low))]
        act = t[t[campsy] > 0].copy()
        if act.empty:
            st.info(f"Aucun talent actif en {year}.")
        else:
            days = act["days_inactive"].astype(int)
            seuil = int(max(45, np.percentile(days, 75))) if len(days) else 45
            act["prix_moyen"] = (act[cay] / act[campsy]).round().astype(int)
            act["depuis"] = days
            act["alerte"] = np.where(days > seuil, "🔴", "")
            act["derniere"] = pd.to_datetime(act["last_sale"])
            if full:
                act = act.sort_values(cay, ascending=False)
                st.altair_chart(bar_sorted(act["name"].head(15), act[cay].head(15)))
                cmax = max(int(act[cay].max()), 1)
                disp = act[["name", "manager", cay, "prix_moyen", campsy, commy,
                            "depuis", "alerte", "derniere", "top_brands"]]
                st.dataframe(disp, hide_index=True, width="stretch", column_config={
                    "name": "Talent", "manager": "Manager",
                    cay: st.column_config.ProgressColumn(f"CA {year}", format="%d €", min_value=0, max_value=cmax),
                    "prix_moyen": st.column_config.NumberColumn("Prix moyen", format="%d €"),
                    campsy: "Campagnes",
                    commy: st.column_config.NumberColumn("Commission", format="%d €"),
                    "depuis": st.column_config.NumberColumn("Depuis dern. collab (j)", format="%d j"),
                    "alerte": "⚠️",
                    "derniere": st.column_config.DateColumn("Dernière vente", format="DD/MM/YYYY"),
                    "top_brands": "Top marques"})
            else:
                act = act.sort_values(campsy, ascending=False)
                st.altair_chart(bar_sorted(act["name"].head(15), act[campsy].head(15), ytitle="Campagnes"))
                disp = act[["name", "manager", campsy, "depuis", "alerte", "derniere", "top_brands"]]
                st.dataframe(disp, hide_index=True, width="stretch", column_config={
                    "name": "Talent", "manager": "Manager", campsy: "Campagnes",
                    "depuis": st.column_config.NumberColumn("Depuis dern. collab (j)", format="%d j"),
                    "alerte": "⚠️",
                    "derniere": st.column_config.DateColumn("Dernière vente", format="DD/MM/YYYY"),
                    "top_brands": "Top marques"})
            st.caption(f"🔴 = pas de collab depuis plus de {seuil} jours (75e percentile)."
                       + ("" if full else " Vue restreinte : données financières masquées."))

with tab_mgr:
    st.subheader(f"Performance par Talent Manager — {year}")
    mg = data["managers"]
    cay, commy, campsy, taly = f"ca_{year}", f"comm_{year}", f"camps_{year}", f"tal_{year}"
    if mg.empty or cay not in mg.columns:
        st.info("Aucune donnée manager.")
    else:
        g = mg[mg[campsy] > 0].copy()
        if g.empty:
            st.info(f"Aucun manager actif en {year}.")
        elif full:
            g = g.sort_values(cay, ascending=False)
            prev_ca = f"ca_{year - 1}"
            if prev_ca in g.columns:
                g["Évol. CA %"] = pct(g[cay].values, g[prev_ca].values)
            st.altair_chart(bar_sorted(g["manager"], g[cay]))
            cols = ["manager", cay, commy, campsy, taly]
            cfg = {"manager": "Manager",
                   cay: st.column_config.NumberColumn(f"CA {year}", format="%d €"),
                   commy: st.column_config.NumberColumn("Commission", format="%d €"),
                   campsy: "Campagnes", taly: "Talents"}
            if "Évol. CA %" in g.columns:
                cols.append("Évol. CA %")
                cfg["Évol. CA %"] = st.column_config.NumberColumn(format="%+d%%")
            st.dataframe(g[cols], hide_index=True, width="stretch", column_config=cfg)
        else:
            g = g.sort_values(campsy, ascending=False)
            st.altair_chart(bar_sorted(g["manager"], g[campsy], ytitle="Campagnes"))
            st.dataframe(g[["manager", campsy, taly]], hide_index=True, width="stretch",
                         column_config={"manager": "Manager", campsy: "Campagnes", taly: "Talents"})
