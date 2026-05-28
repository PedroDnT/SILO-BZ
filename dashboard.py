"""
iliquid_nightly — local analytics dashboard

Install:  pip install streamlit plotly
Run:      streamlit run dashboard.py
"""

import os
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

import urllib.request
import json

load_dotenv()

st.set_page_config(page_title="iliquid_nightly", page_icon="📊", layout="wide")

import psycopg2
import psycopg2.extras


# ── helpers ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)  # refresh once per hour
def _fetch_cdi() -> float:
    """Fetch latest daily CDI rate from BCB SGS API (series 12)."""
    try:
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados/ultimos/1?formato=json"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        return float(data[0]["valor"])
    except Exception:
        return 0.084  # fallback if BCB API is unavailable


def _f(val, default=0.0) -> float:
    """Safe float — handles None/NaN from SQL NULLs."""
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


@st.cache_resource
def _client():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


@st.cache_resource
def _pg_conn():
    url = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
    if not url:
        return None
    url = "".join(url.split())
    return psycopg2.connect(url)


@st.cache_data(ttl=300)
def pg_query(sql: str) -> pd.DataFrame:
    conn = _pg_conn()
    if conn is None:
        return pd.DataFrame()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception as e:
        conn.rollback()
        st.warning(f"Query error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def rpc(fn: str, **params) -> pd.DataFrame:
    try:
        result = _client().rpc(fn, params).execute()
        return pd.DataFrame(result.data) if result.data else pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ {fn}: {e}")
        return pd.DataFrame()


_L = dict(margin=dict(t=10, b=0), legend=dict(orientation="h", y=-0.18))  # common layout


# ── sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📊 iliquid_nightly")
    st.caption("Brazilian fund analytics")

    lookback = st.selectbox("Period", ["6 months", "1 year", "2 years", "3 years"], index=1)
    n_months = {"6 months": 6, "1 year": 12, "2 years": 24, "3 years": 36}[lookback]
    start_date = (date.today() - timedelta(days=n_months * 30)).isoformat()
    end_date   = date.today().isoformat()

    live_cdi = _fetch_cdi()
    cdi = st.number_input(
        "CDI monthly %", value=live_cdi, min_value=0.0, max_value=5.0,
        step=0.001, format="%.4f",
        help="Auto-fetched from BCB SGS series 12 (refreshes hourly). Edit to override.",
    )
    st.caption(f"Live CDI: **{live_cdi:.4f}%** (BCB API)")

    st.divider()
    entity = st.selectbox("Entity for rankings", ["fii", "fidc", "fi", "fiagro", "fip"])


# ── tabs ─────────────────────────────────────────────────────────────────────

tabs = st.tabs([
    "🌐 Market", "🏆 Rankings", "📉 FIDC Credit",
    "📈 Securities", "💹 Yield Universe", "🔍 Fund Search",
    "📊 Fund Activity", "🚨 Suspicious", "🔧 Ops",
])
t_market, t_rank, t_fidc, t_securit, t_yield, t_search, t_activity, t_suspicious, t_ops = tabs


# ═══════════════════════════════════════════════════════════════════════════════
# 🌐 MARKET
# ═══════════════════════════════════════════════════════════════════════════════

with t_market:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("AUM by entity type")
        df = rpc("industry_aum_trend", start_date=start_date, end_date=end_date)
        if not df.empty:
            fig = px.line(df, x="period", y="total_aum", color="entity_type",
                          labels={"total_aum": "AUM (R$)", "period": "", "entity_type": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("FII vs FIAGRO — AUM")
        df = rpc("cross_entity_comparison", entity_types=["fii", "fiagro"],
                 p_metric="aum", start_date=start_date, end_date=end_date)
        if not df.empty:
            fig = px.bar(df, x="period", y="agg_value", color="entity_type",
                         barmode="group",
                         labels={"agg_value": "AUM (R$)", "period": "", "entity_type": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    c3, c4 = st.columns(2)

    with c3:
        st.subheader("FII yield distribution — latest period")
        df = rpc("yield_distribution", p_entity_type="fii",
                 p_period=end_date, benchmark_rate=cdi)
        if not df.empty:
            row = df.iloc[0]
            pcts = ["p10", "p25", "median", "p75", "p90"]
            vals  = [_f(row.get(p)) for p in pcts]
            fig = go.Figure(go.Bar(
                x=pcts, y=vals,
                marker_color=["#636EFA", "#636EFA", "#EF553B", "#636EFA", "#636EFA"],
            ))
            fig.add_hline(y=cdi, line_dash="dash", line_color="green",
                          annotation_text=f"CDI {cdi:.3f}%",
                          annotation_position="top right")
            fig.update_layout(yaxis_title="Monthly yield %", **_L)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                f"n={int(_f(row.get('n_funds')))} funds · "
                f"median {_f(row.get('median')):.3f}% · "
                f"above CDI: {int(_f(row.get('n_above_benchmark')))}"
            )

    with c4:
        st.subheader("Quotaholder trend (FII)")
        df = rpc("quotaholder_trend", p_entity_type="fii",
                 start_date=start_date, end_date=end_date)
        if not df.empty:
            fig = px.line(df, x="period", y="total_cotistas",
                          labels={"total_cotistas": "Quotaholders", "period": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Data freshness")
    df = rpc("data_coverage", start_date=(date.today() - timedelta(days=90)).isoformat(),
             end_date=end_date)
    if not df.empty:
        st.dataframe(df.sort_values(["entity_type", "period"], ascending=[True, False]),
                     use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 🏆 RANKINGS
# ═══════════════════════════════════════════════════════════════════════════════

with t_rank:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader(f"Top 20 {entity.upper()} — AUM")
        df = rpc("fund_ranking", p_entity_type=entity, p_metric="aum", p_limit=20)
        if not df.empty:
            df["label"] = df["cnpj"]
            df = df.sort_values("metric_value")
            fig = px.bar(df, x="metric_value", y="label", orientation="h",
                         labels={"metric_value": "AUM (R$)", "label": ""}, height=520)
            fig.update_layout(margin=dict(t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader(f"Top 20 {entity.upper()} — Yield")
        df = rpc("fund_ranking", p_entity_type=entity, p_metric="yield", p_limit=20)
        if not df.empty:
            df["label"] = df["cnpj"]
            df = df.sort_values("metric_value")
            fig = px.bar(df, x="metric_value", y="label", orientation="h",
                         labels={"metric_value": "Monthly yield %", "label": ""},
                         height=520)
            fig.update_layout(margin=dict(t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)

    st.divider()
    c3, c4, c5, c6 = st.columns(4)
    df_hhi = rpc("market_concentration", p_entity_type=entity)
    if not df_hhi.empty:
        latest = df_hhi.sort_values("period").iloc[-1]
        c3.metric("Entity", entity.upper())
        c4.metric("HHI", f"{_f(latest.get('hhi')):.0f}",
                  help="<1000 competitive · 1000–2500 moderate · >2500 concentrated")
        c5.metric("Top-5 share",  f"{_f(latest.get('top5_share')):.1%}")
        c6.metric("Top-10 share", f"{_f(latest.get('top10_share')):.1%}")

    st.subheader(f"{entity.upper()} — Monthly sector stats")
    df = rpc("entity_monthly_stats", p_entity_type=entity,
             start_date=start_date, end_date=end_date)
    if not df.empty:
        c7, c8 = st.columns(2)
        with c7:
            fig = px.line(df, x="period", y="total_aum",
                          labels={"total_aum": "Total AUM (R$)", "period": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)
        with c8:
            fig = px.line(df, x="period", y="median_yield",
                          labels={"median_yield": "Median yield %", "period": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 📉 FIDC CREDIT
# ═══════════════════════════════════════════════════════════════════════════════

with t_fidc:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Sector delinquency rate")
        df = rpc("fidc_delinquency_trend", start_date=start_date, end_date=end_date)
        if not df.empty:
            fig = px.line(df, x="period", y="avg_inadimpl_rate",
                          labels={"avg_inadimpl_rate": "Avg delinquency %", "period": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("% Funds with delinquency")
        df = rpc("fidc_delinquency_trend", start_date=start_date, end_date=end_date)
        if not df.empty:
            fig = px.area(df, x="period",
                          y=["pct_funds_delinquent", "pct_funds_high_delinq"],
                          labels={"value": "%", "period": "", "variable": ""},
                          color_discrete_map={
                              "pct_funds_delinquent": "#FFA15A",
                              "pct_funds_high_delinq": "#EF553B",
                          })
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Top 10 most delinquent FIDCs")
    df = rpc("fund_ranking", p_entity_type="fidc", p_metric="inadimpl_rate", p_limit=10)
    if not df.empty:
        st.dataframe(df[["rank_pos", "cnpj", "metric_value"]].rename(columns={
            "rank_pos": "#", "cnpj": "CNPJ", "metric_value": "Delinquency rate %",
        }), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Fund deep-dive (tranche + subordination)")
    fidc_cnpj = st.text_input("FIDC CNPJ", placeholder="07727002000126",
                               help="Paste a CNPJ from the table above")

    if fidc_cnpj:
        c3, c4 = st.columns(2)
        with c3:
            st.caption("Tranche performance")
            df = rpc("fidc_tranche_performance", p_cnpj=fidc_cnpj,
                     start_date=start_date, end_date=end_date)
            if not df.empty:
                fig = px.line(df, x="period", y="vl_rentab_mes", color="classe_serie",
                              labels={"vl_rentab_mes": "Monthly return %", "period": "",
                                      "classe_serie": "Tranche"})
                fig.update_layout(**_L)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df.head(20), use_container_width=True, hide_index=True)

        with c4:
            st.caption("Subordination ratio")
            df = rpc("fidc_subordination_trend", p_cnpj=fidc_cnpj,
                     start_date=start_date, end_date=end_date)
            if not df.empty:
                fig = px.line(df, x="period", y="subordination_ratio",
                              labels={"subordination_ratio": "Subordination ratio", "period": ""})
                fig.add_hline(y=0.0, line_dash="dot", line_color="red")
                fig.update_layout(**_L)
                st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 📈 SECURITIES
# ═══════════════════════════════════════════════════════════════════════════════

with t_securit:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Issuance trend by type")
        df = rpc("security_issuance_trend", start_date=start_date, end_date=end_date)
        if not df.empty:
            fig = px.bar(df, x="period", y="total_value", color="instrument_type",
                         barmode="stack",
                         labels={"total_value": "Volume (R$)", "period": "",
                                 "instrument_type": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Maturity ladder")
        df = rpc("security_maturity_ladder")
        if not df.empty:
            fig = px.bar(df, x="maturity_bucket", y="total_value", color="instrument_type",
                         barmode="group",
                         labels={"total_value": "Volume (R$)", "maturity_bucket": "",
                                 "instrument_type": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    c3, c4 = st.columns(2)

    with c3:
        st.subheader("Adimplente vs Inadimplente %")
        df = rpc("security_issuance_trend", start_date=start_date, end_date=end_date)
        if not df.empty:
            total = df["n_adimplente"] + df["n_inadimplente"]
            df["pct_inadimpl"] = df["n_inadimplente"] / total.replace(0, float("nan")) * 100
            fig = px.line(df, x="period", y="pct_inadimpl", color="instrument_type",
                          labels={"pct_inadimpl": "% Inadimplente", "period": "",
                                  "instrument_type": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    with c4:
        st.subheader("Distressed securities")
        df = rpc("distressed_securities")
        if not df.empty:
            show = [c for c in ["cnpj_securit", "codigo_isin", "instrument_type",
                                 "situacao_mes", "valor_certificados", "data_vencimento"]
                    if c in df.columns]
            st.dataframe(df[show].head(20), use_container_width=True, hide_index=True)
        else:
            st.info("No distressed securities.")


# ═══════════════════════════════════════════════════════════════════════════════
# 💹 YIELD UNIVERSE
# ═══════════════════════════════════════════════════════════════════════════════

with t_yield:
    st.subheader("Cross-domain yield: FII + FIAGRO + CRA + CRI vs CDI")
    st.caption(f"CDI monthly benchmark: **{cdi:.4f}%** (edit in sidebar)")

    df = rpc("yield_universe",
             entity_types=["fii", "fiagro"],
             instrument_types=["cra_classe", "cri_classe"],
             start_date=start_date, end_date=end_date,
             benchmark_rate=cdi)

    if not df.empty:
        c1, c2 = st.columns(2)

        with c1:
            st.caption("Yield over time by domain")
            fig = px.line(df.dropna(subset=["yield_mes"]),
                          x="period", y="yield_mes", color="domain",
                          labels={"yield_mes": "Monthly yield %", "period": "", "domain": ""})
            fig.add_hline(y=cdi, line_dash="dash", line_color="green",
                          annotation_text=f"CDI {cdi:.3f}%")
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            st.caption("Spread vs CDI (latest period)")
            latest_period = df["period"].max()
            df_latest = df[df["period"] == latest_period].dropna(subset=["spread_vs_benchmark"])
            if not df_latest.empty:
                fig = px.histogram(df_latest, x="spread_vs_benchmark", color="domain",
                                   barmode="overlay", nbins=40,
                                   labels={"spread_vs_benchmark": "Spread vs CDI %",
                                           "domain": ""})
                fig.add_vline(x=0, line_dash="dash", line_color="red")
                fig.update_layout(**_L)
                st.plotly_chart(fig, use_container_width=True)

        st.subheader(f"Top 50 by yield — {latest_period}")
        show_cols = [c for c in ["domain", "instrument", "identifier",
                                  "yield_mes", "spread_vs_benchmark", "aum"]
                     if c in df_latest.columns]
        st.dataframe(
            df_latest[show_cols].sort_values("yield_mes", ascending=False).head(50),
            use_container_width=True, hide_index=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 🔍 FUND SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

with t_search:
    c1, c2 = st.columns([3, 1])
    with c1:
        query = st.text_input("Search by name or CNPJ", placeholder="kinea, btg, xp…")
    with c2:
        filter_entity = st.selectbox("Entity", ["(all)", "fi", "fidc", "fii", "fip", "fiagro"])

    if query:
        params = dict(query=query, limit_n=30)
        if filter_entity != "(all)":
            params["p_entity_type"] = filter_entity
        df = rpc("search_funds", **params)

        if df.empty:
            st.info("No results.")
        else:
            show = [c for c in ["cnpj", "entity_type", "fund_name",
                                  "first_period", "last_period", "latest_aum"]
                    if c in df.columns]
            st.dataframe(df[show], use_container_width=True, hide_index=True)

            cnpj_sel = st.selectbox(
                "Inspect fund",
                df["cnpj"].tolist(),
                format_func=lambda c: next(
                    (f"{r['fund_name']} ({c})" for _, r in df[df.cnpj == c].iterrows()
                     if r.get("fund_name")), c),
            )

            if cnpj_sel:
                profile = rpc("fund_profile", p_cnpj=cnpj_sel)
                if not profile.empty:
                    p = profile.iloc[0]
                    st.subheader(p.get("fund_name") or cnpj_sel)
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Latest AUM", f"R$ {_f(p.get('latest_aum')):,.0f}")
                    m2.metric("Peak AUM",   f"R$ {_f(p.get('peak_aum')):,.0f}")
                    m3.metric("Months reported", int(_f(p.get("n_months_reported"))))
                    m4.metric("Status", "Active ✅" if p.get("is_active") else "Inactive ⚠️")

                c3, c4 = st.columns(2)
                with c3:
                    nav = rpc("fund_nav_series", p_cnpj=cnpj_sel,
                              start_date=start_date, end_date=end_date)
                    if not nav.empty:
                        fig = px.line(nav, x="period", y="vl_patrim_liq",
                                      labels={"vl_patrim_liq": "AUM (R$)", "period": ""})
                        fig.update_layout(**_L)
                        st.plotly_chart(fig, use_container_width=True)

                with c4:
                    flows = rpc("fund_flow_trend", p_cnpj=cnpj_sel,
                                start_date=start_date, end_date=end_date)
                    if not flows.empty and "net_flow" in flows.columns:
                        fig = px.bar(flows, x="period", y="net_flow",
                                     labels={"net_flow": "Net flow (R$)", "period": ""},
                                     color=flows["net_flow"].apply(
                                         lambda v: "in" if _f(v) >= 0 else "out"),
                                     color_discrete_map={"in": "#00CC96", "out": "#EF553B"})
                        fig.update_layout(**_L)
                        st.plotly_chart(fig, use_container_width=True)

                # Peer ranking
                if profile is not None and not profile.empty:
                    etype = profile.iloc[0].get("entity_type")
                    if etype:
                        rank_df = rpc("fund_ranking", p_entity_type=etype,
                                      p_metric="aum", p_limit=100)
                        if not rank_df.empty:
                            match = rank_df[rank_df["cnpj"] == cnpj_sel]
                            if not match.empty:
                                st.caption(
                                    f"Peer rank (AUM): **#{int(match.iloc[0]['rank_pos'])}** "
                                    f"out of top 100 {etype.upper()} funds"
                                )


# ═══════════════════════════════════════════════════════════════════════════════
# 📊 FUND ACTIVITY
# ═══════════════════════════════════════════════════════════════════════════════

with t_activity:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("New fund registrations per month")
        df = rpc("new_funds_per_period", start_date=start_date, end_date=end_date)
        if not df.empty:
            fig = px.bar(df, x="period", y="n_new", color="entity_type",
                         barmode="stack",
                         labels={"n_new": "New funds", "period": "", "entity_type": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("FII vs FIDC — fund count trend")
        df = rpc("cross_entity_comparison", entity_types=["fii", "fidc"],
                 p_metric="aum", start_date=start_date, end_date=end_date)
        if not df.empty:
            fig = px.line(df, x="period", y="n_funds", color="entity_type",
                          labels={"n_funds": "# Funds reporting", "period": "", "entity_type": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Zombie funds — stopped reporting 90+ days ago")
    df_zombie = rpc("data_coverage",
                    start_date=(date.today() - timedelta(days=365)).isoformat(),
                    end_date=end_date)
    if not df_zombie.empty and "months_since_last_report" in df_zombie.columns:
        zombies = df_zombie[df_zombie["months_since_last_report"] > 3]
        if not zombies.empty:
            st.dataframe(zombies.sort_values("months_since_last_report", ascending=False),
                         use_container_width=True, hide_index=True)
        else:
            st.success("No zombie funds detected.")

    st.subheader("Name coverage by entity")
    df_names = rpc("search_funds", query="", limit_n=1)  # warm up
    try:
        rows = _client().table("dim_fund").select(
            "entity_type, fund_name"
        ).execute().data
        if rows:
            df_cov = pd.DataFrame(rows)
            summary = (df_cov.groupby("entity_type")
                       .agg(total=("fund_name", "count"),
                            with_name=("fund_name", lambda x: x.notna().sum()))
                       .reset_index())
            summary["pct"] = (summary["with_name"] / summary["total"] * 100).round(1)
            fig = px.bar(summary, x="entity_type", y="pct",
                         labels={"pct": "% with name", "entity_type": ""},
                         color="pct", color_continuous_scale="greens", range_color=[0, 100])
            fig.update_layout(margin=dict(t=10, b=0), coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 🚨 SUSPICIOUS DEALS
# ═══════════════════════════════════════════════════════════════════════════════

with t_suspicious:
    st.caption(
        "Screens for patterns that can obscure actual financial health: cross-fund "
        "circular flows, zombie funds, captive vehicles, evergreen aging, subordination "
        "erosion, yield decoupling, and overdue securitizations."
    )

    # ── Combined watchlist ────────────────────────────────────────────────────
    st.subheader("Red-flag watchlist — FIDCs with multiple signals")
    df_watch = pg_query("""
        WITH ranked AS (
            SELECT cnpj, period, vl_patrim_liq,
                   ROUND(100.0 * vl_inadimpl / NULLIF(vl_patrim_liq, 0), 2) AS inadimpl_rate,
                   ROW_NUMBER() OVER (PARTITION BY cnpj ORDER BY period DESC) AS rn_desc
            FROM cvm_fidc_mensal WHERE vl_patrim_liq > 0
        ),
        now_  AS (SELECT cnpj, period, vl_patrim_liq, inadimpl_rate FROM ranked WHERE rn_desc = 1),
        prev_ AS (SELECT cnpj, vl_patrim_liq AS prev_pl, inadimpl_rate AS prev_rate
                  FROM ranked WHERE rn_desc = 7),
        zombie AS (
            SELECT n.cnpj FROM now_ n JOIN prev_ p ON p.cnpj = n.cnpj
            WHERE n.inadimpl_rate - p.prev_rate >= 1.5
              AND n.vl_patrim_liq > p.prev_pl AND n.vl_patrim_liq > 50e6
        ),
        evergreen AS (
            SELECT cnpj FROM (
                SELECT cnpj,
                       AVG(100.0 * vl_inad_30 / NULLIF(vl_total_inad, 0)) AS avg_short,
                       STDDEV(100.0 * vl_inad_30 / NULLIF(vl_total_inad, 0)) AS sd_short
                FROM cvm_fidc_aging WHERE vl_total_inad > 1e6
                GROUP BY cnpj HAVING COUNT(*) >= 6
            ) t WHERE avg_short > 70 AND sd_short < 10
        ),
        fund_nav AS (
            SELECT cnpj, period,
                   ROUND(100.0 *
                       SUM(qt_cota * vl_cota) FILTER (
                           WHERE LOWER(classe_serie) LIKE '%junior%'
                              OR LOWER(classe_serie) LIKE '%j_nior%'
                       ) / NULLIF(SUM(qt_cota * vl_cota), 0), 2) AS subord_pct,
                   LAG(ROUND(100.0 *
                       SUM(qt_cota * vl_cota) FILTER (
                           WHERE LOWER(classe_serie) LIKE '%junior%'
                              OR LOWER(classe_serie) LIKE '%j_nior%'
                       ) / NULLIF(SUM(qt_cota * vl_cota), 0), 2))
                       OVER (PARTITION BY cnpj ORDER BY period) AS subord_prev
            FROM cvm_fidc_tranche WHERE vl_cota > 0 AND qt_cota > 0
            GROUP BY cnpj, period
        ),
        erosion AS (
            SELECT DISTINCT cnpj FROM fund_nav
            WHERE subord_prev IS NOT NULL AND subord_pct - subord_prev <= -3
        )
        SELECT n.cnpj, n.period AS latest_period,
               ROUND(n.vl_patrim_liq / 1e6, 1)     AS pl_m,
               n.inadimpl_rate                      AS inadimpl_pct,
               (z.cnpj IS NOT NULL)::int            AS zombie,
               (e.cnpj IS NOT NULL)::int            AS evergreen,
               (er.cnpj IS NOT NULL)::int           AS subord_erosion,
               (z.cnpj IS NOT NULL)::int
             + (e.cnpj IS NOT NULL)::int
             + (er.cnpj IS NOT NULL)::int           AS flag_count
        FROM now_ n
        LEFT JOIN zombie   z  ON z.cnpj  = n.cnpj
        LEFT JOIN evergreen e ON e.cnpj  = n.cnpj
        LEFT JOIN erosion  er ON er.cnpj = n.cnpj
        WHERE (z.cnpj IS NOT NULL OR e.cnpj IS NOT NULL OR er.cnpj IS NOT NULL)
        ORDER BY flag_count DESC, n.vl_patrim_liq DESC
        LIMIT 30
    """)
    if not df_watch.empty:
        df_watch["flag_count"] = df_watch["flag_count"].astype(int)
        st.dataframe(
            df_watch.style.background_gradient(subset=["flag_count"], cmap="Reds"),
            use_container_width=True, hide_index=True,
        )
        c_flags = ["zombie", "evergreen", "subord_erosion"]
        counts = {col: int(df_watch[col].sum()) for col in c_flags if col in df_watch}
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Funds flagged", len(df_watch))
        m2.metric("Zombie signal", counts.get("zombie", 0))
        m3.metric("Evergreen aging", counts.get("evergreen", 0))
        m4.metric("Subord. erosion", counts.get("subord_erosion", 0))
    else:
        st.info("No funds flagged — or POSTGRES_URL not set.")

    st.divider()

    c1, c2 = st.columns(2)

    # ── Zombie funds ──────────────────────────────────────────────────────────
    with c1:
        st.subheader("Zombie FIDCs")
        st.caption("Delinquency +2pp over 6 months while AUM still grew")
        df_zombie = pg_query("""
            WITH ranked AS (
                SELECT cnpj, period, vl_patrim_liq,
                       ROUND(100.0 * vl_inadimpl / NULLIF(vl_patrim_liq, 0), 2) AS inadimpl_rate,
                       ROW_NUMBER() OVER (PARTITION BY cnpj ORDER BY period DESC) AS rn
                FROM cvm_fidc_mensal WHERE vl_patrim_liq > 0
            ),
            now_  AS (SELECT cnpj, period, vl_patrim_liq, inadimpl_rate FROM ranked WHERE rn = 1),
            then_ AS (SELECT cnpj, vl_patrim_liq AS prev_pl, inadimpl_rate AS prev_rate
                      FROM ranked WHERE rn = 7)
            SELECT n.cnpj, n.period AS period_now,
                   ROUND(n.inadimpl_rate, 2)                            AS inadimpl_now_pct,
                   ROUND(t.prev_rate, 2)                                AS inadimpl_6mo_ago_pct,
                   ROUND(n.inadimpl_rate - t.prev_rate, 2)              AS acceleration_pp,
                   ROUND(n.vl_patrim_liq / 1e6, 1)                      AS pl_now_m,
                   ROUND((n.vl_patrim_liq - t.prev_pl) / 1e6, 1)        AS pl_delta_m
            FROM now_ n JOIN then_ t ON t.cnpj = n.cnpj
            WHERE n.inadimpl_rate - t.prev_rate >= 2.0
              AND n.vl_patrim_liq > t.prev_pl AND n.vl_patrim_liq > 50e6
            ORDER BY acceleration_pp DESC LIMIT 20
        """)
        if not df_zombie.empty:
            fig = px.scatter(
                df_zombie, x="pl_delta_m", y="acceleration_pp",
                hover_name="cnpj", size="pl_now_m",
                labels={"pl_delta_m": "AUM growth (R$M)", "acceleration_pp": "Delinquency accel (pp)"},
                color="acceleration_pp", color_continuous_scale="Reds",
            )
            fig.add_vline(x=0, line_dash="dash", line_color="gray")
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.update_layout(**_L, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_zombie, use_container_width=True, hide_index=True)
        else:
            st.success("No zombie FIDCs detected.")

    # ── Captive vehicles ──────────────────────────────────────────────────────
    with c2:
        st.subheader("Captive vehicles")
        st.caption("R$100M+ AUM with ≤10 investors")
        df_captive = pg_query("""
            SELECT cnpj, dt_comptc AS date, tp_fundo, nr_cotst,
                   ROUND(vl_patrim_liq / 1e6, 1) AS pl_m,
                   ROUND(vl_patrim_liq / NULLIF(nr_cotst, 0) / 1e6, 2) AS pl_per_cotista_m
            FROM cvm_fi_diario
            WHERE dt_comptc = (SELECT MAX(dt_comptc) FROM cvm_fi_diario)
              AND nr_cotst BETWEEN 1 AND 10
              AND vl_patrim_liq > 100e6
            ORDER BY vl_patrim_liq DESC LIMIT 20
        """)
        if not df_captive.empty:
            fig = px.bar(
                df_captive.sort_values("pl_m"),
                x="pl_m", y="cnpj", orientation="h",
                color="nr_cotst", color_continuous_scale="Blues_r",
                labels={"pl_m": "AUM (R$M)", "cnpj": "", "nr_cotst": "# Investors"},
            )
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_captive, use_container_width=True, hide_index=True)
        else:
            st.success("No captive vehicles detected.")

    st.divider()
    c3, c4 = st.columns(2)

    # ── Evergreen aging ───────────────────────────────────────────────────────
    with c3:
        st.subheader("Evergreen aging")
        st.caption(">70% of delinquency perpetually in 0-30d bucket (low variance)")
        df_ever = pg_query("""
            WITH monthly AS (
                SELECT cnpj, period,
                       100.0 * vl_inad_30 / NULLIF(vl_total_inad, 0) AS pct_short,
                       100.0 * (COALESCE(vl_inad_360, 0) + COALESCE(vl_inad_maior_1080, 0))
                             / NULLIF(vl_total_inad, 0)               AS pct_long
                FROM cvm_fidc_aging WHERE vl_total_inad > 1e6
            )
            SELECT cnpj, COUNT(*) AS months,
                   ROUND(AVG(pct_short), 1)    AS avg_pct_short,
                   ROUND(STDDEV(pct_short), 1) AS stddev_short,
                   ROUND(AVG(pct_long), 1)     AS avg_pct_long_tail,
                   MAX(period)                 AS latest_period
            FROM monthly
            GROUP BY cnpj HAVING COUNT(*) >= 6
               AND AVG(pct_short) > 70 AND STDDEV(pct_short) < 10
               AND AVG(pct_long) < 5
            ORDER BY avg_pct_short DESC LIMIT 20
        """)
        if not df_ever.empty:
            st.dataframe(df_ever, use_container_width=True, hide_index=True)
        else:
            st.success("No evergreen aging detected.")

    # ── Subordination erosion ─────────────────────────────────────────────────
    with c4:
        st.subheader("Subordination erosion")
        st.caption("Junior quota -3pp+ in a single month")
        df_subord = pg_query("""
            WITH fund_nav AS (
                SELECT cnpj, period,
                       ROUND(100.0 *
                           SUM(qt_cota * vl_cota) FILTER (
                               WHERE LOWER(classe_serie) LIKE '%junior%'
                                  OR LOWER(classe_serie) LIKE '%j_nior%'
                           ) / NULLIF(SUM(qt_cota * vl_cota), 0), 2) AS subord_pct,
                       LAG(ROUND(100.0 *
                           SUM(qt_cota * vl_cota) FILTER (
                               WHERE LOWER(classe_serie) LIKE '%junior%'
                                  OR LOWER(classe_serie) LIKE '%j_nior%'
                           ) / NULLIF(SUM(qt_cota * vl_cota), 0), 2))
                           OVER (PARTITION BY cnpj ORDER BY period) AS subord_prev
                FROM cvm_fidc_tranche WHERE vl_cota > 0 AND qt_cota > 0
                GROUP BY cnpj, period
            )
            SELECT cnpj, period, subord_pct, subord_prev,
                   ROUND(subord_pct - subord_prev, 2) AS delta_pp
            FROM fund_nav
            WHERE subord_prev IS NOT NULL AND subord_pct - subord_prev <= -3
            ORDER BY delta_pp ASC LIMIT 20
        """)
        if not df_subord.empty:
            fig = px.bar(
                df_subord.sort_values("delta_pp"),
                x="delta_pp", y="cnpj", orientation="h",
                labels={"delta_pp": "Junior quota change (pp)", "cnpj": ""},
                color="delta_pp", color_continuous_scale="Reds_r",
            )
            fig.update_layout(**_L, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_subord, use_container_width=True, hide_index=True)
        else:
            st.success("No subordination erosion detected.")

    st.divider()
    c5, c6 = st.columns(2)

    # ── Senior yield decoupled ────────────────────────────────────────────────
    with c5:
        st.subheader("Senior yield decoupled")
        st.caption("Senior return positive while fund inadimpl > 15%")
        df_dec = pg_query("""
            WITH delinq AS (
                SELECT cnpj, period,
                       ROUND(100.0 * vl_inadimpl / NULLIF(vl_patrim_liq, 0), 2) AS inadimpl_rate
                FROM cvm_fidc_mensal WHERE vl_patrim_liq > 50e6
            ),
            senior AS (
                SELECT cnpj, period,
                       ROUND(AVG(vl_rentab_mes) * 100, 4) AS avg_senior_return_pct
                FROM cvm_fidc_tranche
                WHERE (LOWER(classe_serie) LIKE '%senior%'
                    OR LOWER(classe_serie) LIKE '%s_nior%')
                  AND vl_rentab_mes BETWEEN -0.1 AND 0.1
                GROUP BY cnpj, period
            )
            SELECT d.cnpj, d.period, d.inadimpl_rate, s.avg_senior_return_pct
            FROM delinq d JOIN senior s ON s.cnpj = d.cnpj AND s.period = d.period
            WHERE d.inadimpl_rate > 15 AND s.avg_senior_return_pct > 0
            ORDER BY d.inadimpl_rate DESC LIMIT 20
        """)
        if not df_dec.empty:
            fig = px.scatter(
                df_dec, x="inadimpl_rate", y="avg_senior_return_pct",
                hover_name="cnpj",
                labels={"inadimpl_rate": "Delinquency rate %",
                        "avg_senior_return_pct": "Senior return %"},
                color="inadimpl_rate", color_continuous_scale="Oranges",
            )
            fig.update_layout(**_L, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_dec, use_container_width=True, hide_index=True)
        else:
            st.success("No decoupled senior yields detected.")

    # ── Overdue securit ───────────────────────────────────────────────────────
    with c6:
        st.subheader("Overdue securitizations")
        st.caption("CRI/CRA past maturity but status still open")
        df_overdue = pg_query("""
            SELECT instrument_type, cnpj_securit, codigo_isin, numero_serie,
                   data_vencimento, situacao,
                   ROUND(valor_total_integralizado / 1e6, 2) AS integralizado_m,
                   classificacao_risco_atual,
                   data_referencia AS last_report
            FROM cvm_securit_serie s
            WHERE data_vencimento < CURRENT_DATE
              AND data_vencimento IS NOT NULL
              AND situacao IS NOT NULL
              AND LOWER(situacao) NOT IN ('liquidado','vencido','cancelado','encerrado')
              AND data_referencia = (
                  SELECT MAX(s2.data_referencia)
                  FROM cvm_securit_serie s2
                  WHERE s2.cnpj_securit = s.cnpj_securit
                    AND s2.codigo_identificacao = s.codigo_identificacao
              )
            ORDER BY data_vencimento ASC LIMIT 20
        """)
        if not df_overdue.empty:
            st.dataframe(df_overdue, use_container_width=True, hide_index=True)
        else:
            st.success("No overdue securitizations detected.")


# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 OPS
# ═══════════════════════════════════════════════════════════════════════════════

with t_ops:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Ingest log — last 7 days")
        df = rpc("ingest_log_summary",
                 start_date=(date.today() - timedelta(days=7)).isoformat(),
                 end_date=end_date)
        if not df.empty:
            df["error_rate"] = (df["n_error"] / (df["n_runs"]).replace(0, float("nan")) * 100).round(1)
            st.dataframe(
                df.sort_values("n_error", ascending=False),
                use_container_width=True, hide_index=True,
            )

    with c2:
        st.subheader("Ingest — rows per entity (last 30 days)")
        df30 = rpc("ingest_log_summary",
                   start_date=(date.today() - timedelta(days=30)).isoformat(),
                   end_date=end_date)
        if not df30.empty:
            fig = px.bar(df30, x="entity", y="total_rows", color="doc_type",
                         barmode="stack",
                         labels={"total_rows": "Rows upserted", "entity": "",
                                 "doc_type": ""})
            fig.update_layout(**_L)
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Recent errors")
    try:
        errors = (_client().table("cvm_ingest_log")
                  .select("entity, doc_type, status, rows_upserted, error_msg, started_at")
                  .eq("status", "error")
                  .order("started_at", desc=True)
                  .limit(20)
                  .execute().data)
        if errors:
            st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)
        else:
            st.success("No recent errors.")
    except Exception as e:
        st.warning(str(e))

    st.subheader("Table row counts")
    tables = [
        "cvm_fi_diario", "cvm_fidc_mensal", "cvm_fidc_tranche",
        "cvm_fii_mensal", "cvm_securit_serie", "cvm_fund_registry",
        "fact_fund_monthly", "fact_security_monthly",
    ]
    counts = []
    for t in tables:
        try:
            r = _client().table(t).select("*", count="exact", head=True).execute()
            counts.append({"table": t, "rows": r.count})
        except Exception:
            counts.append({"table": t, "rows": None})
    df_cnt = pd.DataFrame(counts)
    fig = px.bar(df_cnt.dropna(), x="table", y="rows",
                 labels={"rows": "Row count", "table": ""})
    fig.update_layout(margin=dict(t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)
