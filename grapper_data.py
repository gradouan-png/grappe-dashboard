"""
Grapper – couche de donnees.

Remplace le Google Apps Script : au lieu d'un doGet() qui boucle ligne par ligne
et renvoie du JSON, on lit le Sheet une seule fois (gspread) et on calcule tous
les agregats avec pandas (vectorise). Tout est mis en cache par Streamlit, donc
un clic sur un widget ne re-declenche NI l'appel Google NI le recalcul.
"""

import streamlit as st
import pandas as pd
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

# --------------------------------------------------------------------------- #
# Configuration (identique a l'Apps Script)
# --------------------------------------------------------------------------- #
SHEET_ID = "12mBncnRBlwWb2HQB-ySbwOtgTYzK8yenLLDsHBb5rX8"
SHEET_NAME = "Global1"
YEARS = [2024, 2025, 2026]
CLEAN_PLATFORMS = [
    "Tiktok", "IG", "IG reel", "IG Story",
    "UGC", "Ad Code", "YT Short", "YT Intregration",
]
STATUS_FAIT = "Fait"
STATUS_FACTURE = "Facture \u00e0 envoyer"  # "Facture à envoyer"

GS_EPOCH = pd.Timestamp("1899-12-30")  # origine des dates Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
TTL = 600  # secondes de cache (10 min)


# --------------------------------------------------------------------------- #
# Connexion Google (mise en cache : un seul client pour toute la session)
# --------------------------------------------------------------------------- #
@st.cache_resource
def _client():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return gspread.authorize(creds)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _to_dt(values):
    """Convertit une colonne en dates.

    Gere les serials Google Sheets (UNFORMATTED_VALUE -> nombre) ET, en repli,
    les dates au format texte (jj/mm/aaaa ou aaaa-mm-jj).
    """
    s = pd.Series(list(values))
    nums = pd.to_numeric(s, errors="coerce")
    out = GS_EPOCH + pd.to_timedelta(nums, unit="D")
    mask = out.isna() & s.notna() & (s.astype(str).str.strip() != "")
    if mask.any():
        out.loc[mask] = pd.to_datetime(s[mask], errors="coerce", dayfirst=True)
    return out


def _tkey(talent):
    """Extrait le nom lisible depuis l'email talent (logique de l'Apps Script)."""
    if not talent:
        return talent
    k = str(talent).split("@")[0].replace("grapperagency.com", "").rstrip(".").strip()
    return k or str(talent)


def _resolve_columns(header):
    """Associe chaque champ a son index de colonne (robuste aux espaces)."""
    named = {
        "Talents": "talent", "Date vente": "dateVente", "Marques": "marque",
        "Commission": "commission", "Status": "status", "Plateforme": "plateforme",
        "Facture envoy\u00e9": "facture", "Talent Manager": "manager",
        "Date Cr\u00e9ation": "created",
    }
    idx = {k: None for k in list(named.values()) + ["remun", "preview", "post"]}
    for i, h in enumerate(header):
        if h in named:
            idx[named[h]] = i
        if "mun" in h and "ration" in h:      # "Rémunération"
            idx["remun"] = i
        if h == "Preview":
            idx["preview"] = i
        if h == "Post":
            idx["post"] = i
    return idx


# --------------------------------------------------------------------------- #
# 1) Lecture du Sheet -> DataFrame propre  (cache : 1 appel Google / TTL)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=TTL, show_spinner="Lecture du Google Sheet\u2026")
def load_dataframe():
    ws = _client().open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    # UNFORMATTED_VALUE = les dates arrivent en nombres (serials), pas en texte.
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

    def scol(key):  # colonne texte nettoyee
        return pd.Series(col(key)).fillna("").astype(str).str.strip()

    def ncol(key):  # colonne numerique
        return pd.to_numeric(pd.Series(col(key)), errors="coerce").fillna(0.0)

    df = pd.DataFrame({
        "talent": scol("talent"),
        "marque": scol("marque"),
        "status": scol("status"),
        "plateforme": scol("plateforme"),
        "manager": scol("manager"),
        "remun": ncol("remun"),
        "comm": ncol("commission"),
        "facture": ncol("facture"),
        "date_vente": _to_dt(col("dateVente")),
        "created": _to_dt(col("created")),
        "preview": _to_dt(col("preview")),
        "post": _to_dt(col("post")),
    })
    df["year"] = df["date_vente"].dt.year
    df["month"] = df["date_vente"].dt.month
    df["tkey"] = df["talent"].map(_tkey)
    return df


# --------------------------------------------------------------------------- #
# 2) Agregats par annee (vectorises)
# --------------------------------------------------------------------------- #
def _year_block(scope, y):
    dy = scope[scope["year"] == y]
    actives_mask = (dy["status"] != "") & (dy["status"] != STATUS_FAIT) & (dy["status"] != STATUS_FACTURE)
    afact_mask = (dy["remun"] > 0) & (dy["facture"] == 0)

    kpi = {
        "totalCA": int(round(dy["remun"].sum())),
        "totalComm": int(round(dy["comm"].sum())),
        "count": int(len(dy)),
        "actives": int(actives_mask.sum()),
        "caActives": int(round(dy.loc[actives_mask, "remun"].sum())),
        "facturesAEnvoyer": int((dy["status"] == STATUS_FACTURE).sum()),
        "aFacturer": int(round(dy.loc[afact_mask, "remun"].sum())),
        "commAFacturer": int(round(dy.loc[afact_mask, "comm"].sum())),
    }

    status = dy.loc[dy["status"] != "", "status"].value_counts()

    b = dy[(dy["remun"] > 0) & (dy["marque"] != "")]
    brands = b.groupby("marque").agg(volume=("remun", "size"), budget=("remun", "sum"))
    ytd = b[b["month"] <= 3].groupby("marque")["remun"].sum().rename("ytdBudget")
    brands = brands.join(ytd).fillna({"ytdBudget": 0.0})

    talents = (
        dy[(dy["comm"] > 0) & (dy["tkey"] != "")]
        .groupby("tkey")["comm"].sum().sort_values(ascending=False)
    )
    plat = dy.loc[dy["plateforme"].isin(CLEAN_PLATFORMS), "plateforme"].value_counts()
    caFact = dy.groupby("month")["remun"].sum()
    benFact = dy.groupby("month")["comm"].sum()

    return {"kpi": kpi, "status": status, "brands": brands, "talents": talents,
            "plat": plat, "caFact": caFact, "benFact": benFact}


def _brand_top(cur, prev, n=20):
    """Top marques par budget + croissance YTD (Q1) vs annee precedente."""
    t = cur.sort_values("budget", ascending=False).head(n).copy()
    growth = []
    for m in t.index:
        cv = t.loc[m, "ytdBudget"]
        pv = prev["ytdBudget"].get(m, 0.0) if (prev is not None and m in prev.index) else 0.0
        growth.append(round((cv - pv) / pv * 100) if pv and pv > 0 else None)
    t["ytd_growth_pct"] = growth
    t["budget"] = t["budget"].round().astype(int)
    return t.reset_index()[["marque", "volume", "budget", "ytd_growth_pct"]]


# --------------------------------------------------------------------------- #
# 3) Stats talents (vectorise, joins par annee)
# --------------------------------------------------------------------------- #
def _talent_stats(scope, today):
    if scope.empty:
        return pd.DataFrame()

    base = scope.groupby("talent").agg(
        name=("tkey", "first"),
        manager=("manager", "first"),
        last_sale=("date_vente", "max"),
    )

    def ysum(y, valcol, name):
        return scope[scope["year"] == y].groupby("talent")[valcol].sum().rename(name)

    def ycnt(y, name):
        return scope[scope["year"] == y].groupby("talent").size().rename(name)

    base = base.join(ysum(2024, "remun", "ca_2024"))
    base = base.join(ysum(2025, "remun", "ca_2025"))
    base = base.join(ysum(2026, "remun", "ca_2026"))
    base = base.join(ysum(2026, "comm", "comm_2026"))
    base = base.join(
        scope[(scope["year"] == 2025) & (scope["month"] <= 3)]
        .groupby("talent")["remun"].sum().rename("ca_ytd_2025")
    )
    base = base.join(ycnt(2024, "camps_2024"))
    base = base.join(ycnt(2025, "camps_2025"))
    base = base.join(ycnt(2026, "camps_2026"))

    num = ["ca_2024", "ca_2025", "ca_2026", "comm_2026", "ca_ytd_2025",
           "camps_2024", "camps_2025", "camps_2026"]
    base[num] = base[num].fillna(0)
    base = base[base["camps_2026"] > 0].copy()   # actifs 2026 uniquement

    # Top 3 marques par talent
    bm = scope[(scope["remun"] > 0) & (scope["marque"] != "")]
    counts = (bm.groupby(["talent", "marque"]).size().rename("n").reset_index()
              .sort_values("n", ascending=False))
    topbr = counts.groupby("talent")["marque"].apply(lambda s: list(s)[:3])
    base = base.join(topbr.rename("top_brands"))
    base["top_brands"] = base["top_brands"].apply(lambda v: v if isinstance(v, list) else [])

    base["days_inactive"] = (today - base["last_sale"]).dt.days
    for c in ["ca_2024", "ca_2025", "ca_2026", "comm_2026", "ca_ytd_2025"]:
        base[c] = base[c].round().astype(int)
    for c in ["camps_2024", "camps_2025", "camps_2026"]:
        base[c] = base[c].astype(int)

    return base.sort_values("ca_2026", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 4) Planning (sur toutes les lignes non "Fait")
# --------------------------------------------------------------------------- #
def _planning(df, today):
    active = df[df["status"] != STATUS_FAIT]

    prev = active[active["preview"].notna()].copy()
    prev = prev[prev["preview"].dt.normalize() >= today].sort_values("preview")
    previews = prev.assign(preview=prev["preview"].dt.strftime("%Y-%m-%d"))[
        ["talent", "marque", "status", "preview", "manager"]]

    pst = active[active["post"].notna()].copy()
    pst = pst[pst["post"].dt.normalize() >= today].sort_values("post")
    posts = pst.assign(post=pst["post"].dt.strftime("%Y-%m-%d"))[
        ["talent", "marque", "status", "post", "manager"]]

    nod = active[active["preview"].isna() & active["post"].isna()
                 & (active["status"] != STATUS_FACTURE)].copy()
    nod["created"] = nod["created"].dt.strftime("%Y-%m-%d").fillna("")
    noDates = nod[["talent", "marque", "status", "created", "manager"]]

    rev = active[active["status"].str.lower().str.contains("revision", na=False)].copy()
    rev["jours"] = (today - rev["created"].dt.normalize()).dt.days.fillna(0).astype(int)
    rev = rev.sort_values("jours", ascending=False)
    revisions = rev[["talent", "marque", "status", "jours", "manager"]]

    return {"previews": previews, "posts": posts, "noDates": noDates, "revisions": revisions}


def _alltime(scope):
    b = scope[(scope["remun"] > 0) & (scope["marque"] != "")]
    brands = (b.groupby("marque").agg(volume=("remun", "size"), budget=("remun", "sum"))
              .sort_values("budget", ascending=False).head(20))
    brands["budget"] = brands["budget"].round().astype(int)
    talents = (scope[(scope["comm"] > 0) & (scope["tkey"] != "")]
               .groupby("tkey")["comm"].sum().sort_values(ascending=False).head(20))
    return {
        "totalCA": int(round(scope["remun"].sum())),
        "totalComm": int(round(scope["comm"].sum())),
        "count": int(len(scope)),
        "brands": brands.reset_index(),
        "talents": talents,
    }


# --------------------------------------------------------------------------- #
# 5) Point d'entree : tout est calcule une fois et mis en cache
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=TTL, show_spinner="Calcul des agr\u00e9gats\u2026")
def compute_all():
    df = load_dataframe()
    if df.empty:
        return None

    today = pd.Timestamp(date.today())
    scope = df[df["year"].isin(YEARS)].copy()
    scope["year"] = scope["year"].astype(int)
    scope["month"] = scope["month"].astype(int)

    years = {y: _year_block(scope, y) for y in YEARS}
    for y in YEARS:
        prev = years[y - 1]["brands"] if (y - 1) in years else None
        years[y]["brands_top"] = _brand_top(years[y]["brands"], prev)

    return {
        "updated": pd.Timestamp.now(),
        "rows": int(len(df)),
        "years": years,
        "talents": _talent_stats(scope, today),
        "planning": _planning(df, today),
        "alltime": _alltime(scope),
    }
