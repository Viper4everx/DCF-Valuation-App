import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# =============================================================================
#  PRO DCF VALUATION TOOL
#  ---------------------------------------------------------------------------
#  A multi-method equity valuation app built with Streamlit.
#  Pulls live financial data from Yahoo Finance, runs a 10-year DCF model,
#  and presents results across five UI tabs.
#
#  ARCHITECTURE OVERVIEW
#  ---------------------------------------------------------------------------
#  The file is split into two logical halves:
#
#  ── BACKEND (runs on every rerender, top-level scope) ──────────────────────
#
#  SECTION 1  Config & CSS            Global page config and custom dark-theme
#                                     styles injected via st.markdown.
#
#  SECTION 2  PDF Generator           create_pdf() — builds a downloadable
#                                     one-page valuation report via ReportLab.
#
#  SECTION 3  Helper Functions        fmt_comma(), clean_currency() — small
#                                     utilities for formatting and parsing
#                                     user-editable number inputs.
#
#  SECTION 4  Data Engine             get_yahoo_data() — the main data fetch.
#                                     Cached with @st.cache_data (1hr TTL).
#                                     Fetches: price, financials, beta, FX,
#                                     4yr historical data, and peer comps
#                                     (parallelized via ThreadPoolExecutor).
#                                     Returns 11 values to session state.
#
#  SECTION 5  Input Setup             Ticker input, session state init,
#                                     currency symbol resolution, company
#                                     name banner, and Valuation Compass
#                                     (sector-aware method guidance panel).
#
#  SECTION 6  Sidebar — Drivers       WACC auto-calc (CAPM), revenue growth,
#                                     EBIT margin, tax rate, terminal growth,
#                                     exit multiple, NWC driver, SBC toggle.
#                                     All sidebar inputs feed into Sections
#                                     7–9 as plain Python variables.
#
#  SECTION 7  Calculation Engine      10-year two-phase DCF projection.
#                                     Growth decays linearly from g_rev (Y1)
#                                     to safe_ltg (Y10). Produces df_base
#                                     which feeds the editable table.
#
#  SECTION 8  Interactive Table       Renders df_base as an editable
#  (tab_model)                        st.data_editor. Edits here override
#                                     the formula projections in Section 9.
#
#  SECTION 9  Valuation Logic         Three independent methods, weighted avg:
#                                       Method 1 (40%) — Gordon Growth DCF
#                                         10yr explicit + Gordon terminal
#                                       Method 2 (30%) — Conservative DCF
#                                         WACC+1.5%, LTG floored at 2%
#                                       Method 3 (30%) — Peer EV/EBITDA
#                                         Sector median × 0.9 maturity disc.
#                                     Outputs: p_g, p_c, p_e, avg_int, mos_pct
#
#  ── FRONTEND (UI rendering, inside tab blocks) ─────────────────────────────
#
#  SECTION 10  Results Display        Valuation summary card (price vs range),
#  (tab_model)                        rating, PDF download, and three bridge
#                                     tables showing EV → equity walk for
#                                     each method.
#
#  TAB 1  Base Data                   Editable Year 0 financials form.
#                                     Yahoo-imported values, user can override.
#
#  TAB 2  DCF Model                   FCF projection table + Section 10 output.
#
#  TAB 3  Returns & Sensitivity       Rate-of-return table (entry price ×
#                                     horizon), required growth solver,
#                                     WACC/LTG sensitivity heatmap,
#                                     Monte Carlo simulation (correlated
#                                     multivariate normal draws).
#
#  TAB 4  Historical                  4-year revenue/margin/FCF table with
#                                     trend charts and CAGR vs model callout.
#
#  TAB 5  Comparables                 Sector peer EV/EBITDA and P/E table
#                                     with peer median vs exit multiple badge.
#
#  VALUATION COMPASS                  Displayed above tabs after ticker load.
#                                     Maps Yahoo sector → recommended methods
#                                     with PRIMARY / SECONDARY / CAUTION /
#                                     AVOID ratings. Covers 11 sector profiles.
#
#  KEY DESIGN DECISIONS
#  ---------------------------------------------------------------------------
#  • All computation runs OUTSIDE tab blocks so every tab shares the same
#    model state — no stale values when switching tabs.
#  • edited_df (the user-editable table) overrides formula projections in
#    Section 9, allowing manual scenario overrides without breaking the model.
#  • safe_ltg = min(ltg, wacc - 0.015) prevents the Gordon Growth denominator
#    going negative (which would produce nonsensical results).
#  • Mid-year discounting ((1+wacc)^-(y-0.5)) is used throughout — more
#    accurate than end-of-year for businesses with continuous cash flows.
#  • SBC toggle: when ON (default), SBC is NOT added back to FCF because
#    EBIT already has it deducted — adding it back would double-count it.
#  • Peer comps are fetched in parallel (ThreadPoolExecutor, 5 workers) to
#    avoid the ~8s sequential Yahoo API delay on first load.
#  • @st.cache_data(ttl=3600) means data only re-fetches once per hour per
#    ticker, even across rerenders triggered by slider/input changes.
#
#  DEPENDENCIES
#  ---------------------------------------------------------------------------
#  streamlit, pandas, numpy, yfinance, reportlab
# =============================================================================

# ==========================================
# SECTION 1 — CONFIGURATION & STYLING
# Sets page layout, injects custom dark-theme CSS via st.markdown.
# ==========================================
st.set_page_config(page_title="Pro DCF Valuation Tool", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
body { font-family: 'Inter', sans-serif; background: linear-gradient(135deg, #1e1e2f 0%, #2a2a3e 100%); color: #f0f2f6; }

/* Cards */
.glass-card { background: rgba(255,255,255,0.05); border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; }
.val-card { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 24px; border: 1px solid rgba(255,255,255,0.08); height: 100%; transition: transform 0.2s; }
.val-card:hover { transform: translateY(-3px); }

/* Typography */
.val-label { font-size: 11px; font-weight: 700; opacity: 0.5; letter-spacing: 1px; text-transform: uppercase; }
.val-price { font-size: 42px; font-weight: 700; margin: 4px 0 16px 0; color: #fff; }
.val-title { font-size: 18px; font-weight: 600; margin-bottom: 4px; color: #fff; }
.val-sub { font-size: 12px; opacity: 0.6; margin-bottom: 20px; }
.status-under { color: #4ade80; font-weight: 700; }
.status-over { color: #f87171; font-weight: 700; }
.text-blue { color: #60a5fa; }
.text-purple { color: #a78bfa; }
.text-green { color: #34d399; }
.text-orange { color: #fb923c; }
.border-purple { border-left: 5px solid #8b5cf6; }
.border-green { border-left: 5px solid #10b981; }
.border-orange { border-left: 5px solid #fb923c; }

/* Overrides */
div[data-testid="stExpander"] { background-color: rgba(255,255,255,0.02); border-radius: 12px; }
div[data-testid="stButton"] button { min-width: 100px !important; }
th { text-align: center !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="text-align:center; margin-bottom: 30px;">Pro DCF Valuation Tool</h1>', unsafe_allow_html=True)

# ==========================================
# SECTION 2 — PDF GENERATION ENGINE
# create_pdf(): builds a one-page valuation report using ReportLab.
# Called in Section 10 when valuation results are available.
# ==========================================
def create_pdf(ticker, date, price, int_val, upside, wacc, ltg, exit_m, c_curr):
    """Generates a downloadable PDF report"""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 24)
    c.drawString(50, height - 50, f"Valuation Report: {ticker}")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 80, f"Date: {date}")
    c.line(50, height - 100, width - 50, height - 100)

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 140, "Valuation Results")
    c.setFont("Helvetica", 14)
    c.drawString(50, height - 170, f"Current Price: {c_curr}{price:,.2f}")
    c.drawString(50, height - 190, f"Intrinsic Value: {c_curr}{int_val:,.2f}")
    
    status = "UNDERVALUED" if upside >= 0 else "OVERVALUED"
    c.drawString(50, height - 210, f"Upside: {upside:+.1%} ({status})")

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 260, "Key Assumptions")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 290, f"WACC: {wacc:.1%}")
    c.drawString(50, height - 310, f"Terminal Growth: {ltg:.1%}")
    c.drawString(50, height - 330, f"Exit Multiple: {exit_m}x")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# ==========================================
# SECTION 3 — HELPER FUNCTIONS
# fmt_comma(): formats a float as a comma-separated string.
# clean_currency(): strips currency symbols and parses user text inputs back to float.
# ==========================================
def fmt_comma(val):
    if pd.isna(val) or np.isnan(val): return "0.00"
    return f"{val:,.2f}"

def clean_currency(val, symbol="$"):
    if isinstance(val, (int, float)): 
        if np.isnan(val): return 0.0
        return float(val)
    if pd.isna(val) or val == "": return 0.0
    clean = str(val).replace(',', '').replace(symbol, '').replace('€', '').replace('£', '').replace('¥', '').strip()
    try: return float(clean)
    except: return 0.0

# ==========================================
# SECTION 4 — DATA ENGINE
# get_yahoo_data(ticker): single cached function that fetches everything from Yahoo.
# Cached @st.cache_data(ttl=3600) — only re-runs once per hour per ticker.
# Returns: financials, price, shares, FX, historical 4yr data, peer comps, company name.
# Peer comps are fetched in parallel via ThreadPoolExecutor (5 workers).
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_yahoo_data(ticker):
    try:
        tk = yf.Ticker(ticker)
        
        try: info = tk.info
        except: info = {}
        if info is None: info = {}

        # 1. Market Data
        try: price = tk.fast_info.last_price
        except: 
            hist = tk.history(period="1d")
            price = hist['Close'].iloc[-1] if not hist.empty else 0.0

        # === SHARE COUNT LOGIC ===
        shares = info.get('impliedSharesOutstanding')
        if not shares: shares = info.get('sharesOutstanding')
        
        if not shares:
            try: shares = tk.fast_info.shares_outstanding
            except: pass
            
        if not shares or shares < 1000:
            try:
                mkt_cap = tk.fast_info.market_cap
                if mkt_cap and price > 0:
                    shares = mkt_cap / price
            except: pass
            
        if not shares: shares = 1e9 
        shares = shares / 1e6 

        industry = info.get('industry', 'Unknown')
        company_name = info.get('shortName') or info.get('longName') or ticker
        price_curr = info.get('currency', 'USD')
        fin_curr = info.get('financialCurrency', price_curr)
        
        actual_ev_ebitda = info.get('enterpriseToEbitda')
        if actual_ev_ebitda is None or np.isnan(actual_ev_ebitda): actual_ev_ebitda = 0.0
        
        beta_raw = info.get('beta')
        
        try:
            tnx = yf.Ticker("^TNX")
            rf_rate = tnx.fast_info.last_price
            if not rf_rate or np.isnan(rf_rate): rf_rate = 4.0
        except:
            rf_rate = 4.0
        
        fx_rate = 1.0
        fx_msg = ""
        
        if price_curr != fin_curr:
            pair = f"{fin_curr}{price_curr}=X"
            try:
                fx = yf.Ticker(pair)
                rate = fx.fast_info.last_price
                if rate:
                    fx_rate = rate
                    fx_msg = f"Converted {fin_curr} to {price_curr} (Rate: {fx_rate:.3f})"
            except:
                fx_msg = f"⚠️ FX Error: Could not fetch rate for {pair}."

        inc = tk.income_stmt
        bs = tk.balance_sheet
        cf = tk.cashflow

        if inc.empty: raise ValueError("Yahoo Finance returned no data. You may be rate-limited.")

        try:
            last_date_obj = inc.columns[0]
            last_date_str = last_date_obj.strftime('%Y-%m-%d')
        except:
            last_date_str = "Latest Filing"

        def get_val(df, keys):
            if df.empty: return 0.0
            for k in keys:
                if k in df.index:
                    val = df.loc[k].iloc[0]
                    if pd.isna(val) or np.isnan(val): return 0.0
                    return val
            return 0.0

        data = {}

        # Auto-detect scale — Yahoo returns financials in different units depending on
        # the company. Most large-caps return full units (divide by 1e6 to get $M),
        # but some (e.g. Workday) return in thousands (divide by 1e3).
        # We cross-check against market cap to resolve ambiguous cases.
        raw_rev = get_val(inc, ['Total Revenue', 'Total Net Sales'])

        if raw_rev == 0:
            scale = 1e6  # unknown, use default
        elif raw_rev >= 1e10:
            scale = 1e6  # clearly full units — >$10B in any unit system
        elif raw_rev >= 1e6:
            # Ambiguous: could be thousands ($1B–$10B revenue) or full units ($1M–$10M revenue)
            # Use market cap to decide: if mkt cap >> raw_rev/1e3, it's thousands
            try:
                mkt_cap = tk.fast_info.market_cap or 0
                rev_if_thousands = raw_rev / 1e3   # interpret as $M
                rev_if_full      = raw_rev / 1e6   # interpret as $M
                # Price/Sales sanity: if P/S < 0.1 or > 1000 something is wrong
                ps_thousands = mkt_cap / (rev_if_thousands * 1e6) if rev_if_thousands > 0 else 999
                ps_full      = mkt_cap / (rev_if_full      * 1e6) if rev_if_full      > 0 else 999
                # Pick whichever gives a more sensible P/S ratio (between 0.1 and 200)
                ok_t = 0.1 <= ps_thousands <= 200
                ok_f = 0.1 <= ps_full      <= 200
                if ok_t and not ok_f:
                    scale = 1e3
                elif ok_f and not ok_t:
                    scale = 1e6
                else:
                    scale = 1e3  # default to thousands when ambiguous
            except:
                scale = 1e3  # default to thousands
        elif raw_rev >= 1e3:
            scale = 1.0  # already in millions
        else:
            scale = 1e6  # fallback

        factor = fx_rate / scale

        data['Revenue'] = get_val(inc, ['Total Revenue', 'Total Net Sales']) * factor
        data['EBIT']    = get_val(inc, ['Operating Income', 'EBIT']) * factor
        data['PreTaxIncome'] = get_val(inc, ['Pretax Income']) * factor
        data['TaxProvision'] = get_val(inc, ['Tax Provision']) * factor

        data['Depreciation'] = get_val(cf, ['Depreciation And Amortization']) * factor
        if data['Depreciation'] == 0:
            data['Depreciation'] = get_val(inc, ['Reconciled Depreciation']) * factor

        data['Capex'] = abs(get_val(cf, ['Capital Expenditure', 'Capital Expenditures'])) * factor
        data['SBC'] = get_val(cf, ['Stock Based Compensation']) * factor
        data['ChangeInWC'] = get_val(cf, ['Change In Working Capital', 'Changes In Cash', 'Change To Netincome']) * factor

        data['Debt'] = get_val(bs, ['Total Debt', 'Long Term Debt']) * factor
        data['Cash'] = get_val(bs, ['Cash And Cash Equivalents']) * factor
        data['Interest'] = abs(get_val(inc, ['Interest Expense', 'Interest Expense Non Operating'])) * factor
        
        # === FIX: CLEAN BETA ===
        if beta_raw is None or np.isnan(beta_raw):
            data['Beta'] = 1.0 # Default to Market Beta
        else:
            data['Beta'] = float(beta_raw)
            
        data['RiskFree'] = rf_rate
        
        # Country Risk
        country = info.get('country', 'United States')
        country_risk = 0.0
        if country == 'China': country_risk = 1.5
        elif country == 'Brazil': country_risk = 2.2
        elif country not in ['United States', 'Canada', 'United Kingdom', 'Germany', 'France', 'Japan']: country_risk = 1.0
        data['CountryRisk'] = country_risk
        
        # ==========================================
        # HISTORICAL FINANCIALS (last 4 years)
        # ==========================================
        hist_data = []
        try:
            def get_series(df, keys):
                for k in keys:
                    if k in df.index:
                        return df.loc[k]
                return pd.Series(dtype=float)

            rev_series  = get_series(inc, ['Total Revenue', 'Total Net Sales'])
            ebit_series = get_series(inc, ['Operating Income', 'EBIT'])
            da_series_cf = get_series(cf, ['Depreciation And Amortization'])
            capex_series = get_series(cf, ['Capital Expenditure', 'Capital Expenditures'])
            sbc_series  = get_series(cf, ['Stock Based Compensation'])
            nwc_series  = get_series(cf, ['Change In Working Capital'])
            tax_series  = get_series(inc, ['Tax Provision'])
            pretax_series = get_series(inc, ['Pretax Income'])

            for col in inc.columns[:4]:   # up to 4 years
                try:
                    yr_label = col.strftime('%Y') if hasattr(col, 'strftime') else str(col)
                    rev_v  = float(rev_series.get(col, 0) or 0) * factor
                    ebit_v = float(ebit_series.get(col, 0) or 0) * factor
                    da_v   = float(da_series_cf.get(col, 0) or 0) * factor
                    cap_v  = abs(float(capex_series.get(col, 0) or 0)) * factor
                    sbc_v  = float(sbc_series.get(col, 0) or 0) * factor
                    nwc_v  = float(nwc_series.get(col, 0) or 0) * factor
                    tax_v  = float(tax_series.get(col, 0) or 0) * factor
                    pt_v   = float(pretax_series.get(col, 0) or 0) * factor
                    ebit_margin = (ebit_v / rev_v * 100) if rev_v else 0.0
                    tr = (tax_v / pt_v) if pt_v > 0 else 0.21
                    tr = min(max(tr, 0.05), 0.40)
                    nopat_v = ebit_v * (1 - tr)
                    fcff_v = nopat_v + da_v - cap_v + nwc_v + sbc_v
                    hist_data.append({
                        'Year': yr_label,
                        'Revenue': rev_v,
                        'EBIT Margin %': round(ebit_margin, 1),
                        'D&A': da_v,
                        'Capex': cap_v,
                        'SBC': sbc_v,
                        'FCFF': fcff_v,
                    })
                except Exception:
                    pass
            hist_data = list(reversed(hist_data))  # oldest → newest
        except Exception:
            hist_data = []

        # ==========================================
        # COMPARABLES: sector peers from Yahoo (parallelized)
        # ==========================================
        comp_data = []
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            sector = info.get('sector', '')
            recs = tk.recommendations
            peer_tickers = []
            if recs is not None and not recs.empty:
                if 'symbol' in recs.columns:
                    peer_tickers = recs['symbol'].dropna().unique().tolist()[:6]
            if not peer_tickers:
                sector_peers = {
                    'Technology': ['MSFT','GOOGL','META','AMZN','AAPL'],
                    'Consumer Cyclical': ['AMZN','TSLA','HD','MCD','NKE'],
                    'Healthcare': ['JNJ','UNH','PFE','ABBV','MRK'],
                    'Financial Services': ['JPM','BAC','WFC','GS','MS'],
                    'Energy': ['XOM','CVX','COP','SLB','EOG'],
                    'Industrials': ['HON','UPS','CAT','DE','RTX'],
                    'Communication Services': ['GOOGL','META','NFLX','DIS','T'],
                    'Consumer Defensive': ['PG','KO','PEP','WMT','COST'],
                    'Utilities': ['NEE','DUK','SO','D','AEP'],
                    'Real Estate': ['AMT','PLD','CCI','EQIX','SPG'],
                    'Basic Materials': ['LIN','APD','ECL','NEM','FCX'],
                }
                peer_tickers = [t for t in sector_peers.get(sector, ['SPY','QQQ','IWM','VTI','DIA']) if t != ticker][:5]

            def fetch_peer(pt):
                try:
                    pi = yf.Ticker(pt).info
                    if pi is None: return None
                    ev_eb  = pi.get('enterpriseToEbitda')
                    pe     = pi.get('trailingPE')
                    name   = pi.get('shortName', pt)[:20]
                    mktcap = pi.get('marketCap', 0) or 0
                    if ev_eb and not np.isnan(float(ev_eb)) and float(ev_eb) > 0:
                        return {
                            'Ticker': pt,
                            'Name': name,
                            'EV/EBITDA': round(float(ev_eb), 1),
                            'P/E': round(float(pe), 1) if pe and not np.isnan(float(pe)) else None,
                            'Mkt Cap $B': round(mktcap / 1e9, 1) if mktcap else None,
                        }
                except Exception:
                    pass
                return None

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(fetch_peer, pt): pt for pt in peer_tickers[:5]}
                for future in as_completed(futures):
                    result = future.result()
                    if result is not None:
                        comp_data.append(result)

            # Re-sort to match original peer_tickers order
            order = {pt: i for i, pt in enumerate(peer_tickers[:5])}
            comp_data.sort(key=lambda r: order.get(r['Ticker'], 99))

        except Exception:
            comp_data = []

        return data, price, shares, fx_msg, price_curr, industry, actual_ev_ebitda, last_date_str, hist_data, comp_data, company_name
        
    except Exception as e:
        return None, 0.0, 1.0, f"Connection Error: {str(e)}", "USD", "Unknown", None, "Unknown", [], [], ""

# ==========================================
# SECTION 5 — INPUT SETUP & SESSION STATE
# Handles ticker input, unpacks get_yahoo_data() into session_state,
# resolves currency symbol, renders company name banner,
# and runs the Valuation Compass (sector-aware method guidance).
# ==========================================
c_tick, c_refresh, c_space, c_pdf = st.columns([1, 0.4, 3.6, 1], vertical_alignment="bottom")

with c_tick:
    ticker = st.text_input("Ticker", "").upper()

with c_refresh:
    if st.button("🔄", help="Force refresh — clears cached data and re-fetches from Yahoo"):
        get_yahoo_data.clear()
        if 'last_ticker' in st.session_state:
            del st.session_state['last_ticker']
        st.rerun()

pdf_spot = c_pdf.empty()

if 'y0' not in st.session_state:
    st.session_state.y0 = {k:0.0 for k in ['Revenue','EBIT','Depreciation','Capex','Debt','Cash','Interest','Beta','RiskFree','CountryRisk','SBC','ChangeInWC','PreTaxIncome','TaxProvision']}

if 'reset_key' not in st.session_state:
    st.session_state.reset_key = 0

if 'hist_data' not in st.session_state:
    st.session_state.hist_data = []

if 'comp_data' not in st.session_state:
    st.session_state.comp_data = []

curr_symbol = "$"
industry_name = "Unknown"
last_filing_date = "Unknown"

if ticker:
    with st.spinner(f"Analysing {ticker}..."):
        if 'last_ticker' not in st.session_state or st.session_state.last_ticker != ticker:
            d, cur_price, shares_def, fx_msg, currency, ind_name, ev_ebitda, file_date, hist_data, comp_data, company_name = get_yahoo_data(ticker)
            if d:
                st.session_state.y0 = d
                st.session_state.last_price = cur_price
                st.session_state.last_shares = shares_def
                st.session_state.last_ticker = ticker
                st.session_state.fx_msg = fx_msg
                st.session_state.currency = currency
                st.session_state.industry = ind_name
                st.session_state.ev_ebitda_actual = ev_ebitda
                st.session_state.file_date = file_date
                st.session_state.hist_data = hist_data
                st.session_state.comp_data = comp_data
                st.session_state.company_name = company_name
                st.session_state.reset_key += 1
            else:
                st.error(f"Unable to fetch data: {fx_msg}")
                st.warning("Yahoo Finance might be blocking requests. Please wait 60 seconds and try again.")
                cur_price, shares_def = 0.0, 1.0
                st.session_state.fx_msg = ""
                st.session_state.currency = "USD"
                st.session_state.industry = "Unknown"
                st.session_state.ev_ebitda_actual = None
                st.session_state.file_date = "Unknown"
                st.session_state.hist_data = []
                st.session_state.comp_data = []
        else:
            cur_price = st.session_state.last_price
            shares_def = st.session_state.last_shares
            fx_info = st.session_state.get('fx_msg', "")
            curr_code = st.session_state.get('currency', 'USD')
            industry_name = st.session_state.get('industry', 'Unknown')
            file_date = st.session_state.get('file_date', "Unknown")
            curr_symbol = "€" if curr_code == 'EUR' else "£" if curr_code == 'GBP' else "¥" if curr_code in ['CNY','JPY'] else "$"
            last_filing_date = file_date

    if st.session_state.get('fx_msg'):
        st.info(f"💱 {st.session_state.fx_msg}")
else:
    st.info("👈 Enter a stock ticker (e.g. NVDA, AAPL) to begin analysis.")
    shares_def = 1.0
    cur_price = 0.0

# Company name banner
company_name_display = st.session_state.get('company_name', '')
if company_name_display and ticker:
    ind_display = st.session_state.get('industry', '')
    st.markdown(f"""
    <div style="margin: 8px 0 18px 0;">
      <span style="font-size: 26px; font-weight: 700; color: #fff;">{company_name_display}</span>
      <span style="font-size: 16px; color: #60a5fa; margin-left: 10px; font-weight: 600;">({ticker})</span>
      {'<span style="font-size: 12px; color: rgba(255,255,255,0.45); margin-left: 12px;">· ' + ind_display + '</span>' if ind_display and ind_display != 'Unknown' else ''}
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# VALUATION COMPASS
# ==========================================
if ticker and st.session_state.get('company_name'):
    _sector   = st.session_state.get('industry', 'Unknown')
    _industry = st.session_state.get('industry', 'Unknown')

    # Map sector → method guidance
    # Each method: (label, status, note)
    # status: "primary" | "secondary" | "caution" | "avoid"
    COMPASS = {
        'Semiconductors': [
            ("DCF",           "primary",   "Core method — predictable capex cycle"),
            ("EV/EBITDA",     "primary",   "Standard acquisition & peer metric"),
            ("EV/Revenue",    "secondary", "Useful when margins are depressed"),
            ("P/E",           "caution",   "Distorted by amortization of acquisitions"),
            ("DDM",           "avoid",     "Most semis pay little/no dividend"),
            ("P/Book",        "avoid",     "Asset base not reflective of value"),
        ],
        'Technology': [
            ("DCF",           "primary",   "Best for mature profitable tech"),
            ("EV/EBITDA",     "primary",   "Peer comparison standard"),
            ("EV/Revenue",    "secondary", "Use if margins are still low/negative"),
            ("P/E",           "caution",   "GAAP EPS often distorted by SBC & amort."),
            ("DDM",           "avoid",     "Growth companies rarely pay dividends"),
            ("P/Book",        "avoid",     "Intangibles dominate — book is meaningless"),
        ],
        'Software—Application': [
            ("DCF",           "primary",   "Use unlevered FCF — SaaS is predictable"),
            ("EV/Revenue",    "primary",   "Market standard for SaaS multiples"),
            ("EV/EBITDA",     "secondary", "Only if company is profitable"),
            ("P/E",           "caution",   "SBC & amortization distort GAAP EPS"),
            ("DDM",           "avoid",     "SaaS companies reinvest, don't pay divs"),
            ("P/Book",        "avoid",     "Pure intangible business"),
        ],
        'Banks—Diversified': [
            ("P/Book",        "primary",   "Core bank valuation metric"),
            ("P/E",           "primary",   "Clean earnings metric for banks"),
            ("DDM",           "secondary", "Works well for dividend-paying banks"),
            ("DCF",           "caution",   "Hard to separate capex from lending"),
            ("EV/EBITDA",     "avoid",     "Meaningless for financials — debt is product"),
            ("EV/Revenue",    "avoid",     "Not applicable to financial business model"),
        ],
        'Insurance': [
            ("P/Book",        "primary",   "Tangible book drives insurance value"),
            ("P/E",           "primary",   "Normalized earnings are clean"),
            ("DDM",           "secondary", "Insurers are reliable dividend payers"),
            ("DCF",           "caution",   "Reserve uncertainty makes FCF noisy"),
            ("EV/EBITDA",     "avoid",     "Not applicable to insurance model"),
            ("EV/Revenue",    "avoid",     "Premium revenue ≠ economic value"),
        ],
        'Utilities—Regulated Electric': [
            ("DDM",           "primary",   "Regulated utilities = bond-like dividends"),
            ("DCF",           "primary",   "Stable, forecastable FCF"),
            ("EV/EBITDA",     "secondary", "Rate base multiples are standard"),
            ("P/E",           "secondary", "Useful for regulated rate-of-return cos."),
            ("P/Book",        "caution",   "Rate base ≠ book value"),
            ("EV/Revenue",    "avoid",     "Revenue regulated — not a value driver"),
        ],
        'Real Estate': [
            ("P/FFO",         "primary",   "FFO (Funds from Ops) is the REIT standard"),
            ("DCF",           "primary",   "NAV-based DCF is widely used"),
            ("EV/EBITDA",     "secondary", "Useful for non-REIT real estate cos."),
            ("DDM",           "secondary", "REITs must pay 90% of income as divs"),
            ("P/E",           "avoid",     "Depreciation destroys GAAP EPS for REITs"),
            ("P/Book",        "avoid",     "Book value lags property market values"),
        ],
        'Oil & Gas E&P': [
            ("EV/EBITDA",     "primary",   "Industry standard — EV/EBITDAX common"),
            ("DCF",           "primary",   "Reserve-based NAV DCF is standard"),
            ("EV/Revenue",    "secondary", "Useful when EBITDA is negative"),
            ("P/E",           "caution",   "DD&A and impairments distort EPS badly"),
            ("DDM",           "caution",   "Only for mature producers with stable divs"),
            ("P/Book",        "avoid",     "Reserve values not on balance sheet"),
        ],
        'Drug Manufacturers': [
            ("DCF",           "primary",   "Pipeline NPV is core — risk-adjust each drug"),
            ("EV/EBITDA",     "primary",   "Standard for large pharma"),
            ("P/E",           "secondary", "Works for profitable mature pharma"),
            ("EV/Revenue",    "secondary", "Useful for pre-profit biotech"),
            ("DDM",           "caution",   "Only large pharma pays reliable dividends"),
            ("P/Book",        "avoid",     "Intangibles (patents) dominate"),
        ],
        'Consumer Defensive': [
            ("DCF",           "primary",   "Stable cash flows make DCF reliable"),
            ("P/E",           "primary",   "Clean, predictable earnings"),
            ("EV/EBITDA",     "secondary", "Good peer comparison tool"),
            ("DDM",           "secondary", "Staples are reliable dividend payers"),
            ("EV/Revenue",    "caution",   "Low-margin business — revenue alone misleading"),
            ("P/Book",        "avoid",     "Brand value not on balance sheet"),
        ],
        'Industrials': [
            ("EV/EBITDA",     "primary",   "Capex-heavy — EBITDA strips out depreciation"),
            ("DCF",           "primary",   "Works well with stable FCF"),
            ("P/E",           "secondary", "Good for mature, profitable industrials"),
            ("EV/Revenue",    "caution",   "Low margins make revenue multiples unreliable"),
            ("DDM",           "caution",   "Only mature cos. with consistent dividends"),
            ("P/Book",        "avoid",     "Asset values vary widely"),
        ],
        'E-Commerce & Retail': [
            ("EV/Revenue",    "primary",   "Low margins make revenue scale the key metric"),
            ("EV/EBITDA",     "primary",   "Standard retail & marketplace comparison"),
            ("DCF",           "secondary", "Useful but sensitive to margin assumptions"),
            ("P/E",           "caution",   "Margins often too thin or volatile for P/E"),
            ("DDM",           "avoid",     "Retailers rarely pay meaningful dividends"),
            ("P/Book",        "avoid",     "Asset base doesn't reflect brand/logistics value"),
        ],
        'Consumer Cyclical': [
            ("EV/EBITDA",     "primary",   "Standard for discretionary consumer companies"),
            ("DCF",           "primary",   "Works well for established consumer brands"),
            ("P/E",           "secondary", "Clean for profitable consumer businesses"),
            ("EV/Revenue",    "caution",   "Only useful if margins are depressed"),
            ("DDM",           "caution",   "Only for mature cos. with consistent dividends"),
            ("P/Book",        "avoid",     "Brand value not on balance sheet"),
        ],
    }

    # Fuzzy match — use both sector AND industry for accuracy
    # Yahoo's industry field is more specific than sector
    _ind_lower = _industry.lower()
    _sec_lower = _sector.lower()

    matched_key = None

    # ── Industry-level overrides (checked first — most specific) ──
    RETAIL_INDUSTRIES = [
        'internet retail', 'e-commerce', 'ecommerce', 'online retail',
        'specialty retail', 'department stores', 'discount stores',
        'grocery', 'apparel retail', 'home improvement retail',
        'auto & truck dealerships', 'retail',
    ]
    SOFTWARE_INDUSTRIES = [
        'software', 'saas', 'cloud', 'information technology',
        'financial data', 'stock exchange', 'data & analytics', 'financial technology',
        'fintech', 'electronic trading', 'financial software', 'business software',
        'application software', 'infrastructure software', 'it services',
    ]
    SEMI_INDUSTRIES = [
        'semiconductor', 'chip', 'integrated circuit', 'electronic component',
        'electronic equipment', 'hardware', 'computer hardware',
    ]
    BANK_INDUSTRIES = [
        'bank', 'commercial bank', 'savings institution', 'credit union',
        'mortgage', 'consumer lending', 'corporate lending',
    ]

    # Retail/e-commerce checked BEFORE software to prevent 'internet retail' → software
    if any(x in _ind_lower for x in RETAIL_INDUSTRIES):
        matched_key = 'E-Commerce & Retail'
    elif any(x in _ind_lower for x in SOFTWARE_INDUSTRIES):
        matched_key = 'Software—Application'
    elif any(x in _ind_lower for x in SEMI_INDUSTRIES):
        matched_key = 'Semiconductors'
    elif any(x in _ind_lower for x in BANK_INDUSTRIES):
        matched_key = 'Banks—Diversified'

    # ── Sector-level match (if industry didn't resolve it) ──
    if not matched_key:
        for key in COMPASS:
            if key.lower() in _sec_lower or _sec_lower in key.lower():
                matched_key = key
                break

    # ── Broad sector fallbacks ──
    if not matched_key:
        if any(x in _sec_lower for x in ['utility', 'utilities', 'electric', 'gas distribution']):
            matched_key = 'Utilities—Regulated Electric'
        elif any(x in _sec_lower for x in ['real estate', 'reit']):
            matched_key = 'Real Estate'
        elif any(x in _sec_lower for x in ['oil', 'gas', 'energy', 'petroleum', 'e&p']):
            matched_key = 'Oil & Gas E&P'
        elif any(x in _sec_lower for x in ['pharma', 'drug', 'biotech', 'health']):
            matched_key = 'Drug Manufacturers'
        elif any(x in _sec_lower for x in ['retail', 'e-commerce', 'cyclical']):
            matched_key = 'E-Commerce & Retail'
        elif any(x in _sec_lower for x in ['software', 'saas', 'cloud']):
            matched_key = 'Software—Application'
        elif any(x in _sec_lower for x in ['tech', 'semi', 'chip', 'hardware', 'electronic']):
            matched_key = 'Semiconductors'
        elif any(x in _sec_lower for x in ['financial', 'bank', 'credit', 'insurance', 'asset management']):
            matched_key = 'Banks—Diversified'
        elif any(x in _sec_lower for x in ['consumer', 'food', 'beverage', 'household', 'staple']):
            matched_key = 'Consumer Defensive'
        elif any(x in _sec_lower for x in ['industrial', 'aerospace', 'defence', 'machinery', 'transport']):
            matched_key = 'Industrials'
        else:
            matched_key = 'Technology'  # generic fallback

    methods = COMPASS[matched_key]

    STATUS_STYLE = {
        "primary":   ("✅", "#4ade80", "rgba(74,222,128,0.08)", "2px solid rgba(74,222,128,0.3)",  "PRIMARY"),
        "secondary": ("🔵", "#60a5fa", "rgba(96,165,250,0.08)", "2px solid rgba(96,165,250,0.3)",  "SECONDARY"),
        "caution":   ("⚠️", "#fb923c", "rgba(251,146,60,0.08)", "2px solid rgba(251,146,60,0.3)",  "CAUTION"),
        "avoid":     ("❌", "#f87171", "rgba(248,113,113,0.06)","2px solid rgba(248,113,113,0.25)","AVOID"),
    }

    IN_MODEL = {"DCF", "EV/EBITDA"}

    st.markdown(f"###### 🧭 Valuation Compass — *{matched_key}*")

    cols = st.columns(3)
    for i, (method, status, note) in enumerate(methods):
        icon, color, bg, border, label = STATUS_STYLE[status]
        in_model_tag = (
            f"<span style='background:rgba(96,165,250,0.2);color:#60a5fa;"
            f"font-size:9px;border-radius:3px;padding:1px 5px;"
            f"margin-left:5px;font-weight:700;'>IN MODEL</span>"
            if method in IN_MODEL else ""
        )
        with cols[i % 3]:
            st.markdown(
                f"<div style='background:{bg};border:{border};border-radius:8px;"
                f"padding:12px 14px;margin-bottom:8px;min-height:72px;'>"
                f"<div style='font-size:12px;font-weight:700;color:{color};margin-bottom:4px;'>"
                f"{icon} {method}"
                f"<span style='font-size:9px;opacity:0.65;margin-left:5px;"
                f"background:rgba(255,255,255,0.06);border-radius:3px;padding:1px 4px;'>"
                f"{label}</span>"
                f"{in_model_tag}"
                f"</div>"
                f"<div style='font-size:11px;opacity:0.6;line-height:1.4;'>{note}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

    st.caption(f"Sector: *{_sector}*  ·  ✅ Primary  🔵 Secondary  ⚠️ Caution  ❌ Avoid  ·  IN MODEL = used in DCF tab")

date_display = st.session_state.get('file_date', 'Unknown')

# ==========================================
# MAIN TAB LAYOUT
# Five tabs defined here. All computation above already ran.
# Tabs only contain rendering code — no calculations inside tab blocks.
# ==========================================
tab_data, tab_model, tab_returns, tab_hist, tab_comp = st.tabs([
    "📋 Base Data",
    "📊 DCF Model",
    "📈 Returns & Sensitivity",
    "🕐 Historical",
    "🏢 Comparables",
])

# TAB 1 — BASE DATA
# Editable form for Year 0 financials imported from Yahoo.
# User can override Revenue, EBIT, D&A, Capex, Debt, Cash, Shares, SBC, NWC.
# Form submit updates session_state so changes persist across rerenders.
with tab_data:
    st.markdown(f"#### Year 0 Financials (Ended {date_display})")
    st.caption("Figures imported from Yahoo Finance. Unlock to override any value.")
    with st.form("y0_form"):
        # ROW 1
        c1, c2, c3, c4 = st.columns(4)
        r_in_str = c1.text_input("Revenue", value=fmt_comma(st.session_state.y0.get('Revenue', 0)))
        e_in_str = c2.text_input("EBIT", value=fmt_comma(st.session_state.y0.get('EBIT', 0)))
        d_in_str = c3.text_input("D&A", value=fmt_comma(st.session_state.y0.get('Depreciation', 0)))
        c_in_str = c4.text_input("Capex", value=fmt_comma(st.session_state.y0.get('Capex', 0)))
        
        # ROW 2
        c5, c6, c7, c8 = st.columns(4)
        debt_in_str = c5.text_input("Total Debt", value=fmt_comma(st.session_state.y0.get('Debt', 0)))
        cash_in_str = c6.text_input("Total Cash", value=fmt_comma(st.session_state.y0.get('Cash', 0)))
        shares_in_str = c7.text_input("Diluted Shares", value=fmt_comma(shares_def))
        sbc_in_str = c8.text_input("Stock Based Comp", value=fmt_comma(st.session_state.y0.get('SBC', 0)))
        
        # ROW 3 - ADDED EXPLICIT NWC EDIT
        st.caption("Change in Working Capital (Year 0 from Cash Flow Statement)")
        nwc_in_str = st.text_input("Change in NWC", value=fmt_comma(st.session_state.y0.get('ChangeInWC', 0)))
        
        # Convert back to float
        r_in = clean_currency(r_in_str, curr_symbol)
        e_in = clean_currency(e_in_str, curr_symbol)
        d_in = clean_currency(d_in_str, curr_symbol)
        c_in = clean_currency(c_in_str, curr_symbol)
        debt_in = clean_currency(debt_in_str, curr_symbol)
        cash_in = clean_currency(cash_in_str, curr_symbol)
        shares_in = clean_currency(shares_in_str, curr_symbol)
        sbc_in = clean_currency(sbc_in_str, curr_symbol)
        nwc_in = clean_currency(nwc_in_str, curr_symbol)
        
        if shares_in == 0: shares_in = 1.0
        
        if st.form_submit_button("Update Model", use_container_width=True):
            st.session_state.y0['ChangeInWC'] = nwc_in

# ==========================================
# SECTION 6 — SIDEBAR: SCENARIO & DRIVERS
# Scenario presets (Bull/Bear/Base) apply multipliers to growth and margin defaults.
# WACC auto-calculated via CAPM (beta × ERP + risk-free + country risk).
# All outputs (wacc, g_rev, margin_tgt, tax_rate, ltg, cap_r, dep_r, nwc_r, sbc_r_fcf)
# are plain Python variables used directly in Sections 7–9.
# ==========================================
with st.sidebar:
    st.header("Configuration")
    scenario = st.selectbox("Scenario Mode", ["Base Case", "Bull Case 🚀", "Bear Case 🐻"])
    
    if "Bull" in scenario:
        mult_g, mult_m, mult_e = 1.10, 1.05, 1.10
        st.success("Growth +10%, Margin +5%")
    elif "Bear" in scenario:
        mult_g, mult_m, mult_e = 0.90, 0.95, 0.90
        st.warning("Growth -10%, Margin -5%")
    else:
        mult_g, mult_m, mult_e = 1.0, 1.0, 1.0

    st.divider()
    
    # === AUTOMATED WACC CALCULATION (CAPM) ===
    st.subheader("WACC Logic")
    
    beta_in = st.session_state.y0.get('Beta', 1.0)
    rf_in = st.session_state.y0.get('RiskFree', 4.0)
    country_risk = st.session_state.y0.get('CountryRisk', 0.0)
    interest_in = st.session_state.y0.get('Interest', 0.0)
    debt_val = st.session_state.y0.get('Debt', 0.0)
    equity_val = cur_price * shares_in
    
    erp = 5.0 
    cost_equity = (rf_in + (beta_in * erp) + country_risk) / 100
    
    if debt_val > 0:
        cost_debt = interest_in / debt_val
    else:
        cost_debt = (rf_in + 1.5) / 100
        
    if cost_debt > 0.15: cost_debt = 0.08 
    
    total_cap = equity_val + debt_val
    if total_cap <= 0: total_cap = 1.0
    w_e = equity_val / total_cap
    w_d = debt_val / total_cap
    
    pre_tax = st.session_state.y0.get('PreTaxIncome', 0)
    tax_prov = st.session_state.y0.get('TaxProvision', 0)
    if pre_tax > 0 and tax_prov > 0:
        eff_tax_rate = (tax_prov / pre_tax)
        if eff_tax_rate > 0.40 or eff_tax_rate < 0.05: eff_tax_rate = 0.21 
    else:
        eff_tax_rate = 0.21
    
    calc_wacc = (w_e * cost_equity) + (w_d * cost_debt * (1 - eff_tax_rate))
    calc_wacc_pct = calc_wacc * 100
    
    if calc_wacc_pct < 6.0: calc_wacc_pct = 6.0
    if np.isnan(calc_wacc_pct): calc_wacc_pct = 9.0 # Absolute safety net
    
    with st.expander("Show WACC Calculation"):
        st.caption(f"Risk-Free Rate: {rf_in:.2f}%")
        st.caption(f"Country Risk: {country_risk:.2f}%")
        st.caption(f"Beta: {beta_in:.2f}")
        st.caption(f"Cost of Equity: {cost_equity:.1%}")
        st.caption(f"Cost of Debt (After Tax): {cost_debt*(1-eff_tax_rate):.1%}")
        st.caption(f"Weight: {w_e:.0%} Eq / {w_d:.0%} Dbt")
        st.divider()
        st.write(f"**Calculated WACC: {calc_wacc_pct:.1f}%**")
        
    wacc = st.number_input("WACC %", value=float(f"{calc_wacc_pct:.1f}"), step=0.1, format="%.1f", key=f"w_{ticker}_{scenario}_{st.session_state.reset_key}") / 100
    
    st.divider()
    st.subheader("Drivers")
    
    current_margin = (e_in / r_in) if r_in > 0 else 0.0
    
    real_ev_ebitda = st.session_state.get('ev_ebitda_actual')
    if real_ev_ebitda and real_ev_ebitda > 0:
        def_mult = real_ev_ebitda
        st.caption(f"Used Market Multiple: {def_mult:.1f}x")
    else:
        if current_margin > 0.30: def_mult = 18.0 
        elif current_margin < 0.10: def_mult = 8.0
        else: def_mult = 12.0
    
    if current_margin > 0.30: def_growth = 15.0
    elif current_margin < 0.10: def_growth = 3.0
    else: def_growth = 5.0

    g_rev = st.number_input("Revenue Growth %", value=def_growth * mult_g, step=0.5, format="%.1f", key=f"g_{ticker}_{scenario}_{st.session_state.reset_key}") / 100
    m_def = (current_margin * 100)
    margin_tgt = st.number_input("EBIT Margin %", value=float(f"{m_def * mult_m:.1f}"), step=0.5, format="%.1f", key=f"m_{ticker}_{scenario}_{st.session_state.reset_key}") / 100
    tax_rate = st.number_input("Tax Rate %", value=float(f"{eff_tax_rate*100:.1f}"), step=1.0, format="%.1f", key=f"t_{ticker}_{scenario}_{st.session_state.reset_key}") / 100
    ltg = st.number_input("Terminal Growth %", value=2.5, step=0.1, format="%.1f", key=f"l_{ticker}_{scenario}_{st.session_state.reset_key}") / 100
    exit_mult = st.number_input("Exit Multiple (x)", value=def_mult * mult_e, step=0.5, format="%.1f", key=f"e_{ticker}_{scenario}_{st.session_state.reset_key}")
    
    term_cap_ratio = st.slider("Terminal Capex / D&A", 0.5, 1.5, 1.0, 0.1, help="1.0 means Capex matches Depreciation")

    # === GLOBAL RATIOS (Calculated Once, Used Everywhere) ===
    cap_r = c_in/r_in if r_in > 0 else 0
    dep_r = d_in/r_in if r_in > 0 else 0
    
    # NEW NWC LOGIC
    st.markdown("---")
    st.markdown("**Working Capital**")
    
    real_nwc_y0 = nwc_in # From the form above
    
    # Calculate what % of revenue the current NWC change represents (as a proxy)
    # Ideally NWC is % of Change in Revenue.
    # If Rev Change is 0, we can't div by 0, so we default to 0.
    
    # Defaulting the slider:
    # If Y0 NWC is 0, default 0%. If it exists, check ratio vs last year revenue (approx).
    # Since we don't have Y-1 revenue easily, we use current Revenue as a proxy base
    # or just set a safe default if the math is weird.
    
    default_nwc_pct = (real_nwc_y0 / r_in * 100) if r_in != 0 else 0.0
    if default_nwc_pct > 20: default_nwc_pct = 5.0 # Clamp outliers for default
    if default_nwc_pct < -20: default_nwc_pct = -5.0
    
    nwc_driver_pct = st.number_input("NWC % of Change in Rev", value=float(f"{default_nwc_pct:.2f}"), step=0.5, help="Controls automatic NWC calculation. Positive = Cash Outflow (Investment in WC)")
    nwc_r = nwc_driver_pct / 100
    
    sbc_r = (sbc_in / r_in) if r_in > 0 else 0.0

    st.markdown("---")
    st.markdown("**SBC Treatment**")
    sbc_as_cost = st.toggle(
        "Treat SBC as Real Cost",
        value=True,
        help=(
            "ON (recommended): SBC is subtracted from FCF — it dilutes shareholders and should be treated as a real expense. "
            "OFF: SBC is added back as a non-cash item (inflates intrinsic value for high-SBC companies)."
        )
    )
    if sbc_as_cost:
        st.caption("✅ SBC deducted from FCF (dilution cost)")
        # Net effect: subtract SBC from FCF. Since NOPAT already excludes SBC
        # (EBIT from income stmt includes SBC expense), adding it back would be wrong.
        # Setting sbc_r = 0 means we don't add it back. Correct treatment.
        sbc_r_fcf = 0.0
    else:
        st.caption("⚠️ SBC added back (non-cash addback mode)")
        sbc_r_fcf = sbc_r

# ==========================================
# SECTION 7 — CALCULATION ENGINE (10-YEAR TWO-PHASE DCF)
# Builds df_base: Year 0 actuals + Years 1–10 projections.
# Growth decays linearly from g_rev (Year 1) to safe_ltg (Year 10).
# Uses margin_tgt, dep_r, cap_r, nwc_r, sbc_r_fcf ratios from Section 6.
# Output: df_base (DataFrame) used by the editable table in Section 8.
# ==========================================
# Phase 1 (Y1–5): explicit forecast at user growth, decaying toward mid-growth
# Phase 2 (Y6–10): growth continues decaying from mid-growth to terminal rate
years = range(1, 11)
base_data = []

safe_ltg = min(ltg, wacc - 0.015)

if r_in > 0:
    nopat0 = e_in * (1 - tax_rate)
    fcff0  = nopat0 + d_in - c_in + nwc_in
    base_data.append({'Year': 0, 'Revenue': r_in, 'EBIT': e_in, 'NOPAT': nopat0,
                       'D&A': d_in, 'Capex': c_in, 'Change in NWC': nwc_in, 'FCFF': fcff0, 'PV': 0.0})

    prev_rev = r_in
    # Decay: Y1 starts at g_rev, reaches safe_ltg by Y10
    for y in years:
        # Linear decay from g_rev (Y1) to safe_ltg (Y10)
        current_g = g_rev + (safe_ltg - g_rev) * ((y - 1) / 9)
        current_g = max(current_g, safe_ltg)

        rev   = prev_rev * (1 + current_g)
        ebit  = rev * margin_tgt
        nopat = ebit * (1 - tax_rate)
        da    = rev * dep_r
        capex = rev * cap_r
        dnwc  = (rev - prev_rev) * nwc_r
        sbc_proj = rev * sbc_r_fcf
        fcff  = nopat + da - capex - dnwc + sbc_proj

        pv = fcff * ((1 + wacc)**-(y - 0.5))  # mid-year convention

        base_data.append({'Year': y, 'Revenue': rev, 'EBIT': ebit, 'NOPAT': nopat,
                           'D&A': da, 'Capex': capex, 'Change in NWC': dnwc, 'FCFF': fcff, 'PV': pv})
        prev_rev = rev
else:
    for y in range(0, 11):
        base_data.append({'Year': y, 'Revenue': 0.0, 'EBIT': 0.0, 'NOPAT': 0.0,
                           'D&A': 0.0, 'Capex': 0.0, 'Change in NWC': 0.0, 'FCFF': 0.0, 'PV': 0.0})

df_base = pd.DataFrame(base_data).set_index('Year')

# ==========================================
# SECTION 8 — INTERACTIVE FCF TABLE (renders in tab_model)
# Displays df_base as an editable st.data_editor.
# When Unlock toggle is ON, users can override any projected cell.
# edited_df captures user overrides and feeds directly into Section 9.
# Reset button increments reset_key, forcing df_base to regenerate.
# ==========================================
with tab_model:
    c_title, c_space, c_tools = st.columns([5, 3, 2], vertical_alignment="bottom")
    with c_title: st.subheader(f"Projected Free Cash Flow (Millions {curr_symbol})")
    with c_tools:
        t_col, b_col = st.columns([1, 1], gap="small")
        with t_col: is_unlocked = st.toggle("Unlock", value=False)
        with b_col:
            if st.button("↺ Reset", use_container_width=True):
                st.session_state.reset_key += 1
                st.rerun()

    display_cols = [f"Year {y}" for y in range(11)]
    disabled_cols = display_cols if not is_unlocked else ["Year 0"]

    df_display = df_base.T
    df_display.columns = display_cols
    df_formatted = df_display.map(lambda x: f"{x:,.2f}")

    edited_df = st.data_editor(
        df_formatted,
        use_container_width=True,
        disabled=disabled_cols,
        key=f"editor_{st.session_state.reset_key}"
    )

# ==========================================
# SECTION 9 — VALUATION LOGIC (THREE INDEPENDENT METHODS)
# Reads from edited_df (respects any manual overrides from Section 8).
# Method 1 (40%): Gordon Growth — 10yr FCF + normalized Gordon terminal.
# Method 2 (30%): Conservative DCF — WACC+1.5%, LTG floored at 2% GDP.
# Method 3 (30%): Peer EV/EBITDA — sector median × 0.9 maturity discount.
# Weighted intrinsic value → avg_int. Upside → mos_pct.
# All three EVs and equity prices available for bridge tables in Section 10.
#    Method 1 (40%): 10yr DCF + Gordon Growth terminal
#    Method 2 (30%): 10yr DCF + Conservative (WACC+1.5%, LTG floored at 2%)
#    Method 3 (30%): 10yr DCF + Peer-relative EV/EBITDA terminal (sector median)
# ==========================================
try:
    fcf_stream = []
    for y in years:
        col_name = f"Year {y}"
        rev_edit   = clean_currency(edited_df.loc['Revenue',      col_name], curr_symbol)
        ebit_edit  = clean_currency(edited_df.loc['EBIT',         col_name], curr_symbol)
        da_edit    = clean_currency(edited_df.loc['D&A',          col_name], curr_symbol)
        capex_edit = clean_currency(edited_df.loc['Capex',        col_name], curr_symbol)

        try:
            dnwc_final = clean_currency(edited_df.loc['Change in NWC', col_name], curr_symbol)
        except:
            prev_col   = f"Year {y-1}"
            rev_prev   = clean_currency(edited_df.loc['Revenue', prev_col], curr_symbol)
            dnwc_final = (rev_edit - rev_prev) * nwc_r

        sbc_proj    = rev_edit * sbc_r_fcf
        nopat       = ebit_edit * (1 - tax_rate)
        fcff_recalc = nopat + da_edit - capex_edit - dnwc_final + sbc_proj
        pv_recalc   = fcff_recalc * ((1 + wacc)**-(y - 0.5))
        fcf_stream.append(pv_recalc)

        if y == 10:
            ebitda10_final = ebit_edit + da_edit
            da10_final     = da_edit

    sum_pv_final = sum(fcf_stream)

    # ── Normalized terminal FCF (Capex → maintenance level at Y10) ──
    term_capex_norm    = da10_final * term_cap_ratio
    fcf10_normalized   = (ebitda10_final - da10_final) * (1 - tax_rate) + da10_final - term_capex_norm

    # ── Method 1: Gordon Growth (40%) ──
    tv_g     = fcf10_normalized * (1 + safe_ltg) / (wacc - safe_ltg)
    pv_tv_g  = tv_g * ((1 + wacc)**-10)

    # ── Method 2: Conservative DCF (30%) ──
    # WACC+1.5%, LTG floored at 2% (approx long-run nominal GDP)
    wacc_cons    = wacc + 0.015
    safe_ltg_cons = min(max(safe_ltg, 0.02), wacc_cons - 0.015)
    tv_c         = fcf10_normalized * (1 + safe_ltg_cons) / (wacc_cons - safe_ltg_cons)
    pv_tv_c      = tv_c * ((1 + wacc)**-10)   # discount at base WACC for comparability

    # ── Method 3: Peer-relative EV/EBITDA (30%) ──
    # Use sector median from comparables; fall back to user exit_mult only if no peers
    comp_rows_val  = st.session_state.get('comp_data', [])
    peer_multiples = [r['EV/EBITDA'] for r in comp_rows_val if r.get('EV/EBITDA')]
    if peer_multiples:
        peer_mult_med = float(np.median(peer_multiples))
        # Apply a slight discount (10%) to the peer median — mature companies
        # trade at a discount to the current sector average at terminal stage
        terminal_mult = peer_mult_med * 0.90
        mult_source   = f"Peer median {peer_mult_med:.1f}x × 0.9 discount"
    else:
        terminal_mult = exit_mult   # fall back to user input
        mult_source   = f"User input {exit_mult:.1f}x (no peers loaded)"

    tv_e    = ebitda10_final * terminal_mult
    pv_tv_e = tv_e * ((1 + wacc)**-10)

    # ── Bridge to equity value ──
    net_debt = debt_in - cash_in

    def get_equity_price(pv_tv):
        ev = sum_pv_final + pv_tv
        eq = ev - net_debt
        return (eq / shares_in) if shares_in > 0 else 0.0, ev

    p_g, ev_g = get_equity_price(pv_tv_g)
    p_c, ev_c = get_equity_price(pv_tv_c)
    p_e, ev_e = get_equity_price(pv_tv_e)

    # ── Weighted intrinsic value ──
    w1, w2, w3 = 0.40, 0.30, 0.30
    avg_int = w1 * p_g + w2 * p_c + w3 * p_e
    mos_pct = (avg_int - cur_price) / cur_price if cur_price > 0 else 0.0

except Exception as e:
    p_g, p_c, p_e, avg_int, mos_pct = 0, 0, 0, 0, 0
    ev_g, ev_c, ev_e = 0, 0, 0
    terminal_mult = exit_mult
    mult_source   = "N/A"
    sum_pv_final  = 0
    pv_tv_g = pv_tv_c = pv_tv_e = 0


# ==========================================
# SECTION 10 — RESULTS VISUALIZATION (renders in tab_model)
# Summary card: current price vs intrinsic range, rating, PDF download button.
# Three bridge cards (one per method) showing: PV FCFs → EV → net debt → equity.
# Method labels show weights and data source (peer multiple or fallback).
# ==========================================
with tab_model:
    st.divider()
    if cur_price > 0 and r_in > 0:
        model_prices = [p_g, p_c, p_e]
        min_val = min(model_prices)
        max_val = max(model_prices)

        mos_conservative = (min_val - cur_price) / cur_price
        mos_aggressive   = (max_val - cur_price) / cur_price

        if mos_conservative > 0:
            main_color = "status-under"; rating_txt = "STRONG BUY"
        elif mos_pct > 0.20:
            main_color = "status-under"; rating_txt = "STRONG BUY"
        elif mos_pct > 0:
            main_color = "text-orange";  rating_txt = "MODERATE BUY"
        else:
            main_color = "status-over";  rating_txt = "OVERVALUED"

        html_code = f"""
<div class="glass-card">
<div style="display:flex; justify-content: space-around; align-items: center; margin-bottom: 15px;">
<div style="text-align:center;">
  <div class="val-label">CURRENT PRICE</div>
  <div class="val-price">{curr_symbol}{cur_price:,.2f}</div>
</div>
<div style="text-align:center;">
  <div class="val-label">INTRINSIC RANGE</div>
  <div class="val-price text-blue" style="font-size: 32px; margin-bottom: 5px;">
    {curr_symbol}{min_val:,.0f} – {curr_symbol}{max_val:,.0f}
  </div>
  <div style="font-size: 12px; opacity: 0.8;">Average: {curr_symbol}{avg_int:,.2f}</div>
</div>
<div style="text-align:center;">
  <div class="val-label">RATING</div>
  <div class="val-price {main_color}" style="font-size: 32px;">{rating_txt}</div>
  <div class="{main_color}">Avg Upside: {mos_pct:+.1%}</div>
</div>
</div>
<div style="background: rgba(255,255,255,0.1); height: 8px; border-radius: 4px; position: relative; margin: 0 20px;">
  <div style="position: absolute; left: 10%; right: 10%; top: 0; bottom: 0; background: #60a5fa; opacity: 0.3; border-radius: 4px;"></div>
  <div style="position: absolute; left: 10%; top: 12px; font-size: 10px; color: #60a5fa;">Low<br>{mos_conservative:+.0%}</div>
  <div style="position: absolute; right: 10%; top: 12px; font-size: 10px; text-align: right; color: #60a5fa;">High<br>{mos_aggressive:+.0%}</div>
</div>
<div style="text-align: center; font-size: 11px; margin-top: 25px; opacity: 0.6;">
  Conservative Upside: <strong>{mos_conservative:+.1%}</strong> &nbsp;|&nbsp; Aggressive Upside: <strong>{mos_aggressive:+.1%}</strong>
</div>
</div>"""
        st.markdown(html_code, unsafe_allow_html=True)

        pdf_bytes = create_pdf(ticker, pd.Timestamp.now().strftime('%Y-%m-%d'), cur_price, avg_int, mos_pct, wacc, safe_ltg, exit_mult, curr_symbol)
        pdf_spot.download_button(label="📄 Download PDF", data=pdf_bytes, file_name=f"{ticker}_Valuation.pdf", mime="application/pdf")

        st.markdown("<br>", unsafe_allow_html=True)

        def make_bridge(pv_fcf, pv_tv, ev, debt, cash, eq, horizon=10):
            return pd.DataFrame({
                "Component": [f"PV of {horizon}yr Cash Flows", "PV of Terminal Value",
                               "Enterprise Value", "Less: Net Debt", "Equity Value"],
                "Value": [pv_fcf, pv_tv, ev, debt - cash, eq]
            }).set_index("Component")

        bridge_format = f"{curr_symbol}{{:,.2f}}M"
        c_g, c_c, c_e = st.columns(3)

        with c_g:
            st.markdown(f"""<div class="val-card border-purple">
              <div class="val-label">METHOD 1 · 40% WEIGHT</div>
              <div class="val-title">Gordon Growth DCF</div>
              <div class="val-sub">10yr explicit · {safe_ltg:.1%} terminal growth</div>
              <div class="val-label">IMPLIED SHARE PRICE</div>
              <div class="val-price text-purple">{curr_symbol}{p_g:,.2f}</div>
              <div class="val-ev"><span>EV: </span><strong>{curr_symbol}{ev_g:,.2f}M</strong></div>
            </div>""", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### Bridge (Gordon Growth)")
            st.dataframe(make_bridge(sum_pv_final, pv_tv_g, ev_g, debt_in, cash_in,
                         ev_g-(debt_in-cash_in)).style.format(bridge_format), use_container_width=True)

        with c_c:
            st.markdown(f"""<div class="val-card border-orange">
              <div class="val-label">METHOD 2 · 30% WEIGHT</div>
              <div class="val-title">Conservative DCF 🛡️</div>
              <div class="val-sub">WACC+1.5% · LTG floored at 2% (nominal GDP)</div>
              <div class="val-label">IMPLIED SHARE PRICE</div>
              <div class="val-price text-orange">{curr_symbol}{p_c:,.2f}</div>
              <div class="val-ev"><span>EV: </span><strong>{curr_symbol}{ev_c:,.2f}M</strong></div>
            </div>""", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### Bridge (Conservative)")
            st.dataframe(make_bridge(sum_pv_final, pv_tv_c, ev_c, debt_in, cash_in,
                         ev_c-(debt_in-cash_in)).style.format(bridge_format), use_container_width=True)

        with c_e:
            st.markdown(f"""<div class="val-card border-green">
              <div class="val-label">METHOD 3 · 30% WEIGHT</div>
              <div class="val-title">Peer-Relative EV/EBITDA 🏢</div>
              <div class="val-sub">{mult_source}</div>
              <div class="val-label">IMPLIED SHARE PRICE</div>
              <div class="val-price text-green">{curr_symbol}{p_e:,.2f}</div>
              <div class="val-ev"><span>EV: </span><strong>{curr_symbol}{ev_e:,.2f}M</strong></div>
            </div>""", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### Bridge (Peer EV/EBITDA)")
            st.dataframe(make_bridge(sum_pv_final, pv_tv_e, ev_e, debt_in, cash_in,
                         ev_e-(debt_in-cash_in)).style.format(bridge_format), use_container_width=True)

        st.caption(f"Weighted intrinsic value: 40% Gordon + 30% Conservative + 30% Peer EV/EBITDA. "
                   f"Peer multiple: {mult_source}.")

    else:
        st.info("👈 Enter a ticker and configure your assumptions to see valuation results.")

# TAB 3 — RETURNS & SENSITIVITY
# Part A: Rate-of-return table — rows = entry prices (±40% of current),
#          columns = time horizons (1/2/3/5/7/10yr), cells = implied CAGR.
#          Green = beats WACC hurdle, amber = positive but sub-WACC, red = negative.
# Part B: Required growth solver — binary search for the revenue CAGR
#          that makes intrinsic value = current price.
# Part C: Sensitivity heatmap — 5×5 grid of WACC vs terminal growth.
# Part D: Monte Carlo — correlated multivariate normal draws across
#          growth, margin, WACC. Runs 1k–10k simulations. Shows histogram
#          and P10/P50/P90 percentiles.
with tab_returns:

    # ---- Rate of Return ----
    if cur_price > 0 and r_in > 0 and avg_int > 0:
        st.subheader("📈 Rate of Return")
        ror_col1, ror_col2 = st.columns(2)

        with ror_col1:
            st.markdown("**Rate of Return by Entry Price & Horizon**")
            st.caption(f"Assumes stock converges to intrinsic value ({curr_symbol}{avg_int:,.2f}). Green = beats WACC hurdle ({wacc:.1%}).")

            horizons = [1, 2, 3, 5, 7, 10]
            # Entry prices: -40% to +20% of current price in steps, always include current
            offsets = [-0.40, -0.30, -0.20, -0.10, 0.0, +0.10, +0.20]
            entry_prices = [cur_price * (1 + o) for o in offsets]

            # Build table rows
            ror_rows = []
            for ep in entry_prices:
                row = {}
                label = f"{curr_symbol}{ep:,.2f}"
                if abs(ep - cur_price) < 0.01:
                    label += " ◀ now"
                row["Entry Price"] = label
                for h in horizons:
                    if avg_int > 0 and ep > 0:
                        cagr = (avg_int / ep) ** (1/h) - 1
                    else:
                        cagr = 0.0
                    row[f"{h}yr"] = cagr
                ror_rows.append(row)

            df_ror = pd.DataFrame(ror_rows).set_index("Entry Price")

            # Style: green if > wacc, red if < 0, amber in between
            def style_ror(val):
                if val >= wacc:
                    intensity = min(int((val - wacc) / wacc * 200), 120)
                    return f'background-color: rgba(74,222,128,{0.15 + intensity/600:.2f}); color: #4ade80; font-weight:700;'
                elif val >= 0:
                    return 'background-color: rgba(251,146,60,0.15); color: #fb923c; font-weight:600;'
                else:
                    return 'background-color: rgba(248,113,113,0.15); color: #f87171; font-weight:600;'

            st.dataframe(
                df_ror.style
                    .format("{:+.1%}")
                    .map(style_ror),
                use_container_width=True,
                height=300,
            )

        with ror_col2:
            st.markdown("**Revenue Growth Required to Justify Current Price**")
            try:
                def price_at_growth(g_try):
                    safe_ltg_try = min(ltg, wacc - 0.015)
                    decay = 0.0
                    if g_try > safe_ltg_try:
                        decay = (g_try - (g_try + safe_ltg_try)/2) / 4
                    pv_s = 0.0; prev_r = r_in; ebitda5 = 0.0; da5 = 0.0
                    for y in range(1, 6):
                        cg = max(g_try - decay*(y-1), safe_ltg_try)
                        rv = prev_r * (1+cg)
                        eb = rv * margin_tgt; no = eb * (1-tax_rate)
                        da = rv * dep_r; cx = rv * cap_r
                        dn = (rv - prev_r) * nwc_r; sb = rv * sbc_r_fcf
                        pv_s += (no + da - cx - dn + sb) * ((1+wacc)**(-(y-0.5)))
                        prev_r = rv
                        if y == 5: ebitda5 = eb+da; da5 = da
                    tc = da5 * term_cap_ratio
                    fn = (ebitda5-da5)*(1-tax_rate)+da5-tc
                    tv_g2 = fn*(1+safe_ltg_try)/(wacc-safe_ltg_try) * ((1+wacc)**-5)
                    tv_e2 = ebitda5*exit_mult * ((1+wacc)**-5)
                    wacc_c = wacc+0.01; sltg_c = min(safe_ltg_try, wacc_c-0.015)
                    tv_c2 = fn*(1+sltg_c)/(wacc_c-sltg_c) * ((1+wacc)**-5)
                    def ep(tv): return ((pv_s+tv-(debt_in-cash_in))/shares_in) if shares_in>0 else 0
                    return (ep(tv_g2)+ep(tv_e2)+ep(tv_c2))/3

                lo, hi = -0.20, 1.00; req_g = None
                for _ in range(60):
                    mid = (lo+hi)/2
                    if price_at_growth(mid) < cur_price: lo = mid
                    else: hi = mid
                    if abs(hi-lo) < 0.0001: req_g = mid; break

                if req_g is not None:
                    delta   = req_g - g_rev
                    color_g = "#4ade80" if req_g <= g_rev else "#fb923c"
                    verdict = "✅ Current assumptions exceed what's needed" if req_g <= g_rev else "⚠️ Market is pricing in higher growth than modelled"
                    st.markdown(f"""
                    <div class="glass-card" style="text-align:center; padding:18px;">
                      <div class="val-label">Required Revenue CAGR (Y1–5)</div>
                      <div style="font-size:36px; font-weight:700; color:{color_g}; margin:6px 0;">{req_g:.1%}</div>
                      <div style="font-size:12px; opacity:0.7;">Your assumption: {g_rev:.1%} &nbsp;|&nbsp; Delta: {delta:+.1%}</div>
                      <div style="font-size:11px; margin-top:8px; opacity:0.55;">{verdict}</div>
                    </div>
                    """, unsafe_allow_html=True)
            except Exception:
                st.caption("Could not compute required growth.")
    else:
        st.info("Enter a ticker to see return analysis.")

    st.divider()

    # ---- Sensitivity + Monte Carlo side by side ----
    c_sens, c_mc = st.columns(2)

    with c_sens:
        st.subheader("Sensitivity Analysis 🎯")
        st.caption("Implied Share Price based on WACC vs. Terminal Growth")

        def quick_dcf_calc(w, t_g, r_in=r_in, g_rev=g_rev, margin_tgt=margin_tgt,
                            tax_rate=tax_rate, dep_r=dep_r, cap_r=cap_r, nwc_r=nwc_r,
                            sbc_r_fcf=sbc_r_fcf, term_cap_ratio=term_cap_ratio,
                            terminal_mult=terminal_mult,
                            debt_in=debt_in, cash_in=cash_in, shares_in=shares_in):
            """Mirrors main model: 10yr linear decay, normalized terminal FCF,
               blended Gordon (50%) + Peer EV/EBITDA (50%) terminal."""
            safe_t_g = min(t_g, w - 0.015)
            fcf_pv_sum = 0.0
            prev_rev   = r_in
            ebitda10   = 0.0
            da10       = 0.0

            for y in range(1, 11):
                current_g = g_rev + (safe_t_g - g_rev) * ((y - 1) / 9)
                current_g = max(current_g, safe_t_g)
                rev   = prev_rev * (1 + current_g)
                ebit  = rev * margin_tgt
                nopat = ebit * (1 - tax_rate)
                da    = rev * dep_r
                capex = rev * cap_r
                dnwc  = (rev - prev_rev) * nwc_r
                sbc   = rev * sbc_r_fcf
                fcff  = nopat + da - capex - dnwc + sbc
                fcf_pv_sum += fcff * ((1 + w)**-(y - 0.5))
                prev_rev = rev
                if y == 10:
                    ebitda10 = ebit + da
                    da10     = da

            term_capex  = da10 * term_cap_ratio
            fcf10_norm  = (ebitda10 - da10) * (1 - tax_rate) + da10 - term_capex

            tv_gordon   = fcf10_norm * (1 + safe_t_g) / (w - safe_t_g)
            pv_gordon   = tv_gordon  * ((1 + w)**-10)
            tv_peer     = ebitda10   * terminal_mult
            pv_peer     = tv_peer    * ((1 + w)**-10)

            # 50/50 blend of Gordon and peer for sensitivity (conservative mix)
            pv_tv_blend = 0.50 * pv_gordon + 0.50 * pv_peer
            ev  = fcf_pv_sum + pv_tv_blend
            eq  = ev - (debt_in - cash_in)
            return (eq / shares_in) if shares_in > 0 else 0

        wacc_range = [wacc - 0.01, wacc - 0.005, wacc, wacc + 0.005, wacc + 0.01]
        ltg_range  = [ltg  - 0.005, ltg  - 0.0025, ltg, ltg  + 0.0025, ltg  + 0.005]

        sens_data = {}
        for t_g in ltg_range:
            sens_data[f"{t_g:.2%}"] = [quick_dcf_calc(w_r, t_g) for w_r in wacc_range]

        df_sens = pd.DataFrame(sens_data, index=[f"{w:.1%}" for w in wacc_range])
        df_sens.index.name = "WACC"
        df_sens.columns.name = "Terminal Growth"

        def style_sens(val):
            if val == 0: return 'background-color: gray; color: white;'
            color = '#2a2a3e'
            if val > cur_price * 1.1: color = '#105234'
            elif val < cur_price * 0.9: color = '#4a151b'
            return f'background-color: {color}; color: white; border: 1px solid #444;'

        st.dataframe(df_sens.style.format(f"{curr_symbol}{{:,.2f}}").map(style_sens), use_container_width=True)

    with c_mc:
        st.subheader("Monte Carlo Simulation 🎲")
        st.caption("Randomised scenarios to estimate probability distribution of intrinsic value.")

        sim_count = st.slider("Number of Simulations", 1000, 10000, 2000, step=1000)

        if st.button("Run Simulation", use_container_width=True):
            with st.spinner("Simulating..."):
                np.random.seed(42)
                sim_results = []

                means = [g_rev, margin_tgt, wacc]
                sig_g = g_rev * 0.2; sig_m = margin_tgt * 0.15; sig_w = wacc * 0.1
                rho_gm = -0.3; rho_gw = 0.1; rho_mw = 0.05
                cov_matrix = [
                    [sig_g**2,           rho_gm*sig_g*sig_m, rho_gw*sig_g*sig_w],
                    [rho_gm*sig_g*sig_m, sig_m**2,           rho_mw*sig_m*sig_w],
                    [rho_gw*sig_g*sig_w, rho_mw*sig_m*sig_w, sig_w**2          ],
                ]
                draws = np.random.multivariate_normal(means, cov_matrix, sim_count)
                draws[:, 1] = np.clip(draws[:, 1], 0.01, 0.60)

                for i in range(sim_count):
                    g_sim = draws[i, 0]; m_sim = draws[i, 1]; w_sim = draws[i, 2]
                    pv_sum = 0.0; prev_rev_sim = r_in
                    safe_ltg_sim = min(ltg, w_sim - 0.015)

                    ebitda10_sim = 0.0; da10_sim = 0.0

                    for y in range(1, 11):
                        current_g_sim = g_sim + (safe_ltg_sim - g_sim) * ((y - 1) / 9)
                        current_g_sim = max(current_g_sim, safe_ltg_sim)
                        rev_sim   = prev_rev_sim * (1 + current_g_sim)
                        ebit_sim  = rev_sim * m_sim
                        nopat_sim = ebit_sim * (1 - tax_rate)
                        da_sim    = rev_sim * dep_r; capex_sim = rev_sim * cap_r
                        dnwc_sim  = (rev_sim - prev_rev_sim) * nwc_r
                        sbc_sim   = rev_sim * sbc_r_fcf
                        fcff_sim  = nopat_sim + da_sim - capex_sim - dnwc_sim + sbc_sim
                        pv_sum   += fcff_sim * ((1 + w_sim)**-(y - 0.5))
                        prev_rev_sim = rev_sim
                        if y == 10: ebitda10_sim = ebit_sim + da_sim; da10_sim = da_sim

                    # Terminal values
                    term_capex_sim = da10_sim * term_cap_ratio
                    fcf10_norm_sim = (ebitda10_sim - da10_sim)*(1-tax_rate) + da10_sim - term_capex_sim

                    # Gordon Growth terminal
                    tv_g_sim   = fcf10_norm_sim * (1+safe_ltg_sim) / (w_sim-safe_ltg_sim)
                    pv_tv_g_sim = tv_g_sim * ((1+w_sim)**-10)

                    # Conservative terminal (WACC+1.5%)
                    w_cons_sim    = w_sim + 0.015
                    sltg_c_sim    = min(max(safe_ltg_sim, 0.02), w_cons_sim - 0.015)
                    tv_c_sim      = fcf10_norm_sim * (1+sltg_c_sim) / (w_cons_sim-sltg_c_sim)
                    pv_tv_c_sim   = tv_c_sim * ((1+w_sim)**-10)

                    # Peer EV/EBITDA terminal
                    tv_e_sim      = ebitda10_sim * terminal_mult
                    pv_tv_e_sim   = tv_e_sim * ((1+w_sim)**-10)

                    def _ep(tv): return ((pv_sum+tv-(debt_in-cash_in))/shares_in) if shares_in>0 else 0
                    # Weighted same as main model
                    avg_share_price = 0.40*_ep(pv_tv_g_sim) + 0.30*_ep(pv_tv_c_sim) + 0.30*_ep(pv_tv_e_sim)
                    sim_results.append(avg_share_price)

                sim_df = pd.DataFrame(sim_results, columns=["Price"])
                sim_df = sim_df[(sim_df['Price'] > 0) & (sim_df['Price'] < cur_price * 4)]
                counts, bins = np.histogram(sim_df['Price'], bins=30)
                bin_mids = [f"{curr_symbol}{(bins[i]+bins[i+1])/2:.0f}" for i in range(len(bins)-1)]
                st.bar_chart(pd.DataFrame({"Frequency": counts}, index=bin_mids), color="#60a5fa")

                p10 = np.percentile(sim_results, 10)
                p50 = np.percentile(sim_results, 50)
                p90 = np.percentile(sim_results, 90)
                st.markdown(f"""
                <div style="display:flex; justify-content:space-between; font-size:12px; margin-top:10px;">
                  <div class="status-over">P10 (Bear): {curr_symbol}{p10:,.2f}</div>
                  <div class="text-blue">P50 (Base): {curr_symbol}{p50:,.2f}</div>
                  <div class="status-under">P90 (Bull): {curr_symbol}{p90:,.2f}</div>
                </div>
                """, unsafe_allow_html=True)

# TAB 4 — HISTORICAL FINANCIALS
# Shows 4 years of actual revenue, EBIT margin, D&A, Capex, SBC, FCFF.
# Revenue and margin trend charts. CAGR callout vs modelled growth assumption.
# Data sourced from get_yahoo_data() hist_data, stored in session_state.
with tab_hist:
    hist_rows = st.session_state.get('hist_data', [])
    if hist_rows:
        st.subheader("Historical Financials (Last 4 Years)")
        st.caption("Use these to sanity-check your growth and margin assumptions. All values in millions.")

        df_hist = pd.DataFrame(hist_rows).set_index('Year')
        rev_vals   = df_hist['Revenue'].tolist()
        rev_growth = [None] + [(rev_vals[i]/rev_vals[i-1]-1)*100 if rev_vals[i-1] else 0 for i in range(1, len(rev_vals))]
        df_hist.insert(1, 'Rev Growth %', [f"{v:.1f}%" if v is not None else "—" for v in rev_growth])

        display_hist = df_hist.copy()
        for col in ['Revenue', 'D&A', 'Capex', 'SBC', 'FCFF']:
            if col in display_hist.columns:
                display_hist[col] = display_hist[col].apply(lambda x: f"{curr_symbol}{x:,.1f}M")
        display_hist['EBIT Margin %'] = display_hist['EBIT Margin %'].apply(lambda x: f"{x:.1f}%")
        st.dataframe(display_hist, use_container_width=True)

        hc1, hc2 = st.columns(2)
        with hc1:
            st.markdown("**Revenue Trend**")
            st.bar_chart(pd.DataFrame({'Revenue ($M)': df_hist['Revenue']}), color="#60a5fa")
        with hc2:
            st.markdown("**EBIT Margin % Trend**")
            st.line_chart(pd.DataFrame({'EBIT Margin %': df_hist['EBIT Margin %']}), color="#a78bfa")

        if len(rev_vals) >= 2:
            hist_cagr = (rev_vals[-1] / rev_vals[0]) ** (1/max(len(rev_vals)-1, 1)) - 1
            st.info(
                f"📌 Historical Revenue CAGR: **{hist_cagr:.1%}** over {len(rev_vals)-1} years  "
                f"| Your modelled growth: **{g_rev:.1%}**  "
                f"| Delta: **{(g_rev - hist_cagr):+.1%}**"
            )
    else:
        st.info("Enter a ticker above to load historical financials.")

# TAB 5 — PEER COMPARABLES
# Sector peers fetched in parallel during get_yahoo_data().
# Table shows EV/EBITDA, P/E, market cap for up to 5 peers.
# Peer median EV/EBITDA badge vs your exit multiple with pass/warn indicator.
# This median feeds directly into Method 3 of the valuation (Section 9).
with tab_comp:
    comp_rows = st.session_state.get('comp_data', [])
    if comp_rows:
        ind = st.session_state.get('industry', 'Unknown')
        st.subheader(f"Peer Comparables — {ind}")
        st.caption("Sector peers pulled from Yahoo Finance. Use EV/EBITDA median to anchor your exit multiple assumption.")

        df_comp = pd.DataFrame(comp_rows)
        if ticker and cur_price > 0 and r_in > 0:
            ev_ebitda_self = st.session_state.get('ev_ebitda_actual', None)
            self_row = {
                'Ticker': f"▶ {ticker}", 'Name': f"{ticker} (You)",
                'EV/EBITDA': round(ev_ebitda_self, 1) if ev_ebitda_self and ev_ebitda_self > 0 else None,
                'P/E': None, 'Mkt Cap $B': None,
            }
            df_comp = pd.concat([pd.DataFrame([self_row]), df_comp], ignore_index=True)

        peer_ev_ebitda = [r['EV/EBITDA'] for r in comp_rows if r.get('EV/EBITDA')]
        peer_median    = round(float(np.median(peer_ev_ebitda)), 1) if peer_ev_ebitda else None

        def fmt_cell(v, suffix="x"): return f"{v}{suffix}" if v is not None else "N/A"
        df_dc = df_comp.copy()
        df_dc['EV/EBITDA']  = df_comp['EV/EBITDA'].apply(lambda v: fmt_cell(v, "x"))
        df_dc['P/E']        = df_comp['P/E'].apply(lambda v: fmt_cell(v, "x"))
        df_dc['Mkt Cap $B'] = df_comp['Mkt Cap $B'].apply(lambda v: fmt_cell(v, "B"))
        st.dataframe(df_dc.set_index('Ticker'), use_container_width=True)

        if peer_median is not None:
            diff    = exit_mult - peer_median
            color_m = "#4ade80" if abs(diff) < 2 else "#fb923c"
            st.markdown(f"""
            <div class="glass-card" style="margin-top:10px;">
              <div style="display:flex; justify-content:space-around; text-align:center;">
                <div>
                  <div class="val-label">Peer Median EV/EBITDA</div>
                  <div style="font-size:28px; font-weight:700; color:#60a5fa;">{peer_median}x</div>
                </div>
                <div>
                  <div class="val-label">Your Exit Multiple</div>
                  <div style="font-size:28px; font-weight:700; color:#a78bfa;">{exit_mult:.1f}x</div>
                </div>
                <div>
                  <div class="val-label">vs. Peers</div>
                  <div style="font-size:28px; font-weight:700; color:{color_m};">{diff:+.1f}x</div>
                </div>
              </div>
              <div style="text-align:center; font-size:11px; opacity:0.5; margin-top:8px;">
                {'✅ Exit multiple is close to peer median' if abs(diff) < 2 else '⚠️ Exit multiple deviates significantly from peers — double-check your assumption'}
              </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("Enter a ticker above to load peer comparables.")
