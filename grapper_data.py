"""
Grapper – couche de donnees (lecture Sheet + agregats pandas, mis en cache).
Annees detectees automatiquement (2024, 2025, 2026, puis 2027... des qu'elles
apparaissent). Fournit tout ce dont app.py a besoin.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = "12mBncnRBlwWb2HQB-ySbwOtgTYzK8yenLLDsHBb5rX8"
SHEET_NAME = "Global1"
CLEAN_PLATFORMS = ["Tiktok", "IG", "IG reel", "IG Story",
                   "UGC", "Ad Code", "YT Short", "YT Intregration"]
STATUS_FAIT = "Fait"
STATUS_FACTURE = "Facture \u00e0 envoyer"

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
        out.loc[mask] = pd.to_datetime(s[mask], errors="coerce", dayfirst=True)
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
        "Facture envoy\u00e9": "facture", "Talent Manager": "manager",
        "Date Cr\u00e9ation": "created",
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


@st.cache_data(ttl=TTL, show_spinner="Lecture du Google Sheet\u2026")
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


# --------------------------------------------------------------------------- #
def _days_in_year(y):
    return pd.Timestamp(year=int(y), month=12, day=31).dayofyear


def _year_block(scope, y, today):
    dy = scope[scope["year"] == y]
    n = len(dy)
    total_ca = float(dy["remun"].sum())
    total_comm = float(dy["comm"].sum())
    active_mask = (dy["status"] != "") & (dy["status"] != STATUS_FAIT) & (dy["status"] != STATUS_FACTURE)
    afact_mask = (dy["remun"] > 0) & (dy["facture"] == 0)

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
        "caActives": int(round(dy.loc[active_mask, "remun"].sum())),
        "facturesAEnvoyer": int((dy["status"] == STATUS_FACTURE).sum()),
        "aFacturer": int(round(dy.loc[afact_mask, "remun"].sum())),
        "commAFacturer": int(round(dy.loc[afact_mask, "comm"].sum())),
        "caMoyen": int(round(total_ca / n)) if n else 0,
        "campsPerMonth": round(n / months_el, 1),
        "campsPerDay": round(n / days_el, 2),
        "tauxComm": round(total_comm / total_ca * 100, 1) if total_ca else 0.0,
        "nbMarques": int(dy.loc[(dy["remun"] > 0) & (dy["marque"] != ""), "marque"].nunique()),
        "nbTalents": int(dy.loc[dy["talent"] != "", "talent"].nunique()),
    }

    status = dy.loc[dy["status"] != "", "status"].value_counts()
    plat = dy.loc[dy["plateforme"].isin(CLEAN_PLATFORMS), "plateforme"].value_counts()

    b = dy[(dy["remun"] > 0) & (dy["marque"] != "")]
    brands = b.groupby("marque").agg(
        budget=("remun", "sum"), volume=("remun", "size"), derniere=("date_vente", "max"))
    if not brands.empty:
        brands["budget"] = brands["budget"].round().astype(int)
        brands["volume"] = brands["volume"].astype(int)

    monthly = pd.DataFrame({"month": range(1, 13)})
    monthly["CA"] = monthly["month"].map(dy.groupby("month")["remun"].sum()).fillna(0).round().astype(int)
    monthly["Commission"] = monthly["month"].map(dy.groupby("month")["comm"].sum()).fillna(0).round().astype(int)

    return {"kpi": kpi, "status": status, "plat": plat, "brands": brands, "monthly": monthly}


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

    act = df[(df["status"] != "") & (df["status"] != STATUS_FAIT) & (df["status"] != STATUS_FACTURE)]
    encours = set(act["talent"].unique())
    base["en_cours"] = [t in encours for t in base.index]
    base["days_inactive"] = (today - base["last_sale"]).dt.days.clip(lower=0)

    for c in base.columns:
        if c.startswith(("ca_", "comm_")):
            base[c] = base[c].fillna(0).round().astype(int)
        elif c.startswith("camps_"):
            base[c] = base[c].fillna(0).astype(int)
    return base.reset_index()


@st.cache_data(ttl=TTL, show_spinner="Calcul des agr\u00e9gats\u2026")
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
