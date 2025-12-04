import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# ==========================================
# 1. CONFIGURATION & STYLING
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
# 2. PDF GENERATION ENGINE
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
# 3. HELPER FUNCTIONS
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
# 4. DATA ENGINE (NAN-PROOF)
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
        factor = fx_rate / 1e6 
        
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
        
        return data, price, shares, fx_msg, price_curr, industry, actual_ev_ebitda, last_date_str
        
    except Exception as e:
        return None, 0.0, 1.0, f"Connection Error: {str(e)}", "USD", "Unknown", None, "Unknown"

# ==========================================
# 5. UI: INPUTS & SETUP
# ==========================================
c_tick, c_space, c_pdf = st.columns([1, 4, 1], vertical_alignment="bottom")

with c_tick:
    ticker = st.text_input("Ticker", "").upper()

pdf_spot = c_pdf.empty()

if 'y0' not in st.session_state:
    st.session_state.y0 = {k:0.0 for k in ['Revenue','EBIT','Depreciation','Capex','Debt','Cash','Interest','Beta','RiskFree','CountryRisk','SBC','ChangeInWC','PreTaxIncome','TaxProvision']}

if 'reset_key' not in st.session_state:
    st.session_state.reset_key = 0

curr_symbol = "$"
industry_name = "Unknown"
last_filing_date = "Unknown"

if ticker:
    with st.spinner(f"Analysing {ticker}..."):
        if 'last_ticker' not in st.session_state or st.session_state.last_ticker != ticker:
            d, cur_price, shares_def, fx_msg, currency, ind_name, ev_ebitda, file_date = get_yahoo_data(ticker)
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

date_display = st.session_state.get('file_date', 'Unknown')
st.markdown(f"### Year 0: Base Financials (Ended {date_display})")

with st.expander("Expand to edit Year 0 Data", expanded=True):
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
        
        # Convert back to float
        r_in = clean_currency(r_in_str, curr_symbol)
        e_in = clean_currency(e_in_str, curr_symbol)
        d_in = clean_currency(d_in_str, curr_symbol)
        c_in = clean_currency(c_in_str, curr_symbol)
        debt_in = clean_currency(debt_in_str, curr_symbol)
        cash_in = clean_currency(cash_in_str, curr_symbol)
        shares_in = clean_currency(shares_in_str, curr_symbol)
        sbc_in = clean_currency(sbc_in_str, curr_symbol)
        if shares_in == 0: shares_in = 1.0
        
        st.form_submit_button("Update Model")

# ==========================================
# 6. SCENARIO & DRIVERS (SIDEBAR)
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
    
    real_nwc = st.session_state.y0.get('ChangeInWC', 0)
    nwc_r = (real_nwc / r_in) if r_in > 0 else 0.0
    if nwc_r > 0.05: nwc_r = 0.05
    if nwc_r < -0.05: nwc_r = -0.05
    
    sbc_r = (sbc_in / r_in) if r_in > 0 else 0.0

# ==========================================
# 7. CALCULATION ENGINE (SMART DECAY)
# ==========================================
years = range(1, 6)
base_data = []

safe_ltg = ltg if ltg < (wacc - 0.015) else (wacc - 0.015)

if r_in > 0:
    nopat0 = e_in * (1 - tax_rate)
    fcff0 = nopat0 + d_in - c_in + real_nwc + sbc_in 
    
    base_data.append({'Year': 0, 'Revenue': r_in, 'EBIT': e_in, 'NOPAT': nopat0, 'D&A': d_in, 'Capex': c_in, 'FCFF': fcff0, 'PV': 0.0})

    prev_rev = r_in

    growth_decay_step = 0.0
    if g_rev > safe_ltg:
        target_y5_growth = (g_rev + safe_ltg) / 2 
        growth_decay_step = (g_rev - target_y5_growth) / 4 
    
    for y in years:
        current_g = g_rev - (growth_decay_step * (y - 1))
        if current_g < safe_ltg: current_g = safe_ltg
        
        rev = prev_rev * (1 + current_g)
        ebit = rev * margin_tgt
        nopat = ebit * (1 - tax_rate)
        
        # Use Global Ratios
        da = rev * dep_r
        capex = rev * cap_r
        dnwc = (rev - prev_rev) * nwc_r
        sbc_proj = rev * sbc_r
        
        fcff = nopat + da - capex - dnwc + sbc_proj
        
        # FIX 5: Mid-year discount
        pv = fcff * ((1 + wacc)**-(y - 0.5))
        
        base_data.append({'Year':y,'Revenue':rev,'EBIT':ebit,'NOPAT':nopat,'D&A':da,'Capex':capex,'FCFF':fcff,'PV':pv})
        prev_rev = rev
else:
    for y in range(0, 6): base_data.append({'Year':y,'Revenue':0.0,'EBIT':0.0,'NOPAT':0.0,'D&A':0.0,'Capex':0.0,'FCFF':0.0,'PV':0.0})

df_base = pd.DataFrame(base_data).set_index('Year')

# ==========================================
# 8. INTERACTIVE TABLE
# ==========================================
st.divider()

c_title, c_space, c_tools = st.columns([5, 3, 2], vertical_alignment="bottom")
with c_title: st.subheader(f"Projected Free Cash Flow (Millions {curr_symbol})")
with c_tools:
    t_col, b_col = st.columns([1, 1], gap="small")
    with t_col: is_unlocked = st.toggle("Unlock", value=False)
    with b_col:
        if st.button("↺ Reset", use_container_width=True):
            st.session_state.reset_key += 1
            st.rerun()

display_cols = [f"Year {y}" for y in range(6)]
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
# 9. VALUATION LOGIC
# ==========================================
try:
    fcf_stream = []
    for y in years:
        col_name = f"Year {y}"
        rev_edit = clean_currency(edited_df.loc['Revenue', col_name], curr_symbol)
        ebit_edit = clean_currency(edited_df.loc['EBIT', col_name], curr_symbol)
        da_edit = clean_currency(edited_df.loc['D&A', col_name], curr_symbol)
        capex_edit = clean_currency(edited_df.loc['Capex', col_name], curr_symbol)
        
        prev_col = f"Year {y-1}"
        rev_prev = clean_currency(edited_df.loc['Revenue', prev_col], curr_symbol)
        
        dnwc = (rev_edit - rev_prev) * nwc_r
        sbc_proj = rev_edit * sbc_r
        
        nopat = ebit_edit * (1 - tax_rate)
        # Recalc FCF
        fcff_recalc = nopat + da_edit - capex_edit - dnwc + sbc_proj
        
        # Mid-year discount
        pv_recalc = fcff_recalc * ((1 + wacc)**-(y - 0.5))
        fcf_stream.append(pv_recalc)
        
        if y == 5:
            fcf5_final = fcff_recalc
            ebitda5_final = ebit_edit + da_edit
            da5_final = da_edit 

    sum_pv_final = sum(fcf_stream)
    
    term_nopat = ebitda5_final * (1 - tax_rate) 
    term_capex = da5_final * term_cap_ratio
    fcf5_normalized = (ebitda5_final - da5_final)*(1-tax_rate) + da5_final - term_capex
    
    tv_g = fcf5_normalized * (1+safe_ltg)/(wacc-safe_ltg)
    pv_tv_g = tv_g * ((1+wacc)**-5)
    
    wacc_cons = wacc + 0.01
    safe_ltg_cons = safe_ltg if safe_ltg < (wacc_cons - 0.015) else (wacc_cons - 0.015)
    tv_c = fcf5_normalized * (1+safe_ltg_cons)/(wacc_cons-safe_ltg_cons)
    pv_tv_c = tv_c * ((1+wacc)**-5)
    
    tv_e = ebitda5_final * exit_mult
    pv_tv_e = tv_e * ((1+wacc)**-5)

    def get_price(pv_tv_val):
        ev = sum_pv_final + pv_tv_val
        eq = ev - (debt_in - cash_in)
        return (eq / shares_in) if shares_in > 0 else 0, ev

    p_g, ev_g = get_price(pv_tv_g)
    p_c, ev_c = get_price(pv_tv_c)
    p_e, ev_e = get_price(pv_tv_e)

    avg_int = (p_g + p_e + p_c) / 3 
    if cur_price > 0: mos_pct = (avg_int - cur_price) / cur_price
    else: mos_pct = 0.0

except Exception as e:
    p_g, p_c, p_e, avg_int, mos_pct = 0,0,0,0,0
    ev_g, ev_c, ev_e = 0,0,0

# ==========================================
# 10. RESULTS VISUALIZATION
# ==========================================
st.divider()

if cur_price > 0 and r_in > 0:
    model_prices = [p_g, p_c, p_e]
    min_val = min(model_prices) 
    max_val = max(model_prices) 
    
    mos_conservative = (min_val - cur_price) / cur_price
    mos_aggressive = (max_val - cur_price) / cur_price
    
    if mos_conservative > 0:
        main_color = "status-under"
        rating_txt = "STRONG BUY (Safe)"
    elif mos_pct > 0.20: 
        main_color = "status-under"
        rating_txt = "STRONG BUY (High Upside)"
    elif mos_pct > 0:
        main_color = "text-orange"
        rating_txt = "MODERATE BUY"
    else:
        main_color = "status-over"
        rating_txt = "OVERVALUED"

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
{curr_symbol}{min_val:,.0f} - {curr_symbol}{max_val:,.0f}
</div>
<div style="font-size: 12px; opacity: 0.8;">Average: {curr_symbol}{avg_int:,.2f}</div>
</div>
<div style="text-align:center;">
<div class="val-label">RATING</div>
<div class="val-price {main_color}" style="font-size: 32px;">{rating_txt}</div>
<div style="{main_color}">Avg Upside: {mos_pct:+.1%}</div>
</div>
</div>
<div style="background: rgba(255,255,255,0.1); height: 8px; border-radius: 4px; position: relative; margin: 0 20px;">
<div style="position: absolute; left: 10%; right: 10%; top: 0; bottom: 0; background: #60a5fa; opacity: 0.3; border-radius: 4px;"></div>
<div style="position: absolute; left: 10%; top: 12px; font-size: 10px; color: #60a5fa;">Low<br>{mos_conservative:+.0%}</div>
<div style="position: absolute; right: 10%; top: 12px; font-size: 10px; text-align: right; color: #60a5fa;">High<br>{mos_aggressive:+.0%}</div>
</div>
<div style="text-align: center; font-size: 11px; margin-top: 25px; opacity: 0.6;">
Conservative Upside: <strong>{mos_conservative:+.1%}</strong> &nbsp; | &nbsp; Aggressive Upside: <strong>{mos_aggressive:+.1%}</strong>
</div>
</div>
"""
    st.markdown(html_code, unsafe_allow_html=True)

    pdf_bytes = create_pdf(ticker, pd.Timestamp.now().strftime('%Y-%m-%d'), cur_price, avg_int, mos_pct, wacc, safe_ltg, exit_mult, curr_symbol)
    pdf_spot.download_button(label="📄 Download PDF", data=pdf_bytes, file_name=f"{ticker}_Valuation.pdf", mime="application/pdf")

st.markdown("<br>", unsafe_allow_html=True)

c_g, c_c, c_e = st.columns(3)
def make_bridge(pv_fcf, pv_tv, ev, debt, cash, eq):
    return pd.DataFrame({
        "Component": ["PV of 5y Cash Flows", "PV of Terminal", "Enterprise Value", "Less: Net Debt", "Equity Value"],
        "Value": [pv_fcf, pv_tv, ev, debt-cash, eq]
    }).set_index("Component")

bridge_format = f"{curr_symbol}{{:,.2f}}M"

with c_g:
    st.markdown(f"""<div class="val-card border-purple"><div class="val-title">Perpetuity Growth</div><div class="val-sub">Stable {safe_ltg:.1%} long-term growth</div><div class="val-label">IMPLIED SHARE PRICE</div><div class="val-price text-purple">{curr_symbol}{p_g:,.2f}</div><div class="val-ev"><span>EV: </span><strong>{curr_symbol}{ev_g:,.2f}M</strong></div></div>""", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### Bridge (Gordon)", unsafe_allow_html=True)
    st.dataframe(make_bridge(sum_pv_final, pv_tv_g, ev_g, debt_in, cash_in, ev_g-(debt_in-cash_in)).style.format(bridge_format), use_container_width=True)

with c_c:
    st.markdown(f"""<div class="val-card border-orange"><div class="val-title">Conservative Case 🛡️</div><div class="val-sub">Higher Discount Rate (WACC + 1%)</div><div class="val-label">IMPLIED SHARE PRICE</div><div class="val-price text-orange">{curr_symbol}{p_c:,.2f}</div><div class="val-ev"><span>EV: </span><strong>{curr_symbol}{ev_c:,.2f}M</strong></div></div>""", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### Bridge (Conservative)", unsafe_allow_html=True)
    st.dataframe(make_bridge(sum_pv_final, pv_tv_c, ev_c, debt_in, cash_in, ev_c-(debt_in-cash_in)).style.format(bridge_format), use_container_width=True)

with c_e:
    st.markdown(f"""<div class="val-card border-green"><div class="val-title">Exit Multiple 💼</div><div class="val-sub">Based on {exit_mult}x EBITDA</div><div class="val-label">IMPLIED SHARE PRICE</div><div class="val-price text-green">{curr_symbol}{p_e:,.2f}</div><div class="val-ev"><span>EV: </span><strong>{curr_symbol}{ev_e:,.2f}M</strong></div></div>""", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### Bridge (Multiple)", unsafe_allow_html=True)
    st.dataframe(make_bridge(sum_pv_final, pv_tv_e, ev_e, debt_in, cash_in, ev_e-(debt_in-cash_in)).style.format(bridge_format), use_container_width=True)

# ==========================================
# 11. SENSITIVITY TABLE
# ==========================================
st.markdown("<br><hr><br>", unsafe_allow_html=True)
c_sens, c_mc = st.columns([1, 1])

with c_sens:
    st.subheader("Sensitivity Analysis 🎯")
    st.caption("Implied Share Price based on WACC vs. Terminal Growth")

    def quick_dcf_calc(w, t_g):
        # Use Global Ratios from Sidebar
        # sbc_r and nwc_r are defined in sidebar, check scope
        # NOTE: sensitivity uses the same globals defined in sidebar
        
        fcf_pv_sum = 0.0
        prev_rev = r_in
        last_fcf = 0.0
        last_ebitda = 0.0
        
        for y in range(1, 6):
            rev = prev_rev * (1 + g_rev)
            ebit = rev * margin_tgt
            nopat = ebit * (1 - tax_rate)
            da = rev * dep_r
            capex = rev * cap_r
            dnwc = (rev - prev_rev) * nwc_r
            sbc_proj = rev * sbc_r
            
            fcff = nopat + da - capex - dnwc + sbc_proj
            pv = fcff * ((1 + w)**-(y-0.5))
            fcf_pv_sum += pv
            prev_rev = rev
            if y == 5:
                last_fcf = fcff
                last_ebitda = ebit + da 

        tv_g = last_fcf * (1 + t_g) / (w - t_g)
        pv_tv_g = tv_g * ((1 + w)**-5)
        tv_e = last_ebitda * exit_mult
        pv_tv_e = tv_e * ((1 + w)**-5)
        
        eq_g = (fcf_pv_sum + pv_tv_g) - (debt_in - cash_in)
        eq_e = (fcf_pv_sum + pv_tv_e) - (debt_in - cash_in)
        
        return ((eq_g + eq_e) / 2) / shares_in if shares_in > 0 else 0

    wacc_range = [wacc - 0.01, wacc - 0.005, wacc, wacc + 0.005, wacc + 0.01]
    ltg_range = [ltg - 0.005, ltg - 0.0025, ltg, ltg + 0.0025, ltg + 0.005]

    sens_data = {}
    for t_g in ltg_range:
        col_data = []
        for w_r in wacc_range:
            val = quick_dcf_calc(w_r, t_g)
            col_data.append(val)
        sens_data[f"{t_g:.2%}"] = col_data

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

# ==========================================
# 12. MONTE CARLO SIMULATION (ENHANCED)
# ==========================================
with c_mc:
    st.subheader("Monte Carlo Simulation 🎲")
    st.caption(f"Running randomized scenarios to find probability.")
    
    sim_count = st.slider("Number of Simulations", 1000, 10000, 2000, step=1000)
    
    if st.button("Run Simulation", use_container_width=True):
        with st.spinner("Simulating..."):
            np.random.seed(42) 
            sim_results = []
            
            # FIX 9: Multivariate Normal Distribution (Correlation)
            means = [g_rev, margin_tgt, wacc]
            # Standard Deviations
            sig_g = g_rev * 0.2
            sig_m = margin_tgt * 0.15
            sig_w = wacc * 0.1
            
            # Correlation Coefficients
            rho_gm = -0.3 # Growth vs Margin (High growth = spend more = lower margin)
            rho_gw = 0.1  # Growth vs WACC (High growth = higher risk)
            rho_mw = 0.05 # Margin vs WACC
            
            # Covariance Matrix
            cov_matrix = [
                [sig_g**2,              rho_gm*sig_g*sig_m,    rho_gw*sig_g*sig_w],
                [rho_gm*sig_g*sig_m,    sig_m**2,              rho_mw*sig_m*sig_w],
                [rho_gw*sig_g*sig_w,    rho_mw*sig_m*sig_w,    sig_w**2]
            ]
            
            # Draw correlated samples
            draws = np.random.multivariate_normal(means, cov_matrix, sim_count)
            
            # Clipping to prevent unrealistic outliers
            draws[:, 1] = np.clip(draws[:, 1], 0.01, 0.60) # Margin [1% - 60%]
            
            for i in range(sim_count):
                g_sim = draws[i, 0]
                m_sim = draws[i, 1]
                w_sim = draws[i, 2]
                
                pv_sum = 0.0
                prev_rev_sim = r_in
                
                # Hard Clip Terminal Growth to be strictly less than WACC
                safe_ltg_sim = min(ltg, w_sim - 0.015)
                
                growth_decay_step_sim = 0.0
                if g_sim > safe_ltg_sim:
                    target_y5 = (g_sim + safe_ltg_sim) / 2
                    growth_decay_step_sim = (g_sim - target_y5) / 4
                
                fcf5_sim = 0.0
                ebitda5_sim = 0.0
                da5_sim = 0.0

                for y in range(1, 6):
                    current_g_sim = g_sim - (growth_decay_step_sim * (y - 1))
                    if current_g_sim < safe_ltg_sim: current_g_sim = safe_ltg_sim
                    
                    rev_sim = prev_rev_sim * (1 + current_g_sim)
                    ebit_sim = rev_sim * m_sim
                    nopat_sim = ebit_sim * (1 - tax_rate)
                    
                    # Use Global Ratios
                    da_sim = rev_sim * dep_r
                    capex_sim = rev_sim * cap_r
                    dnwc_sim = (rev_sim - prev_rev_sim) * nwc_r
                    sbc_sim = rev_sim * sbc_r
                    
                    fcff_sim = nopat_sim + da_sim - capex_sim - dnwc_sim + sbc_sim
                    
                    # Mid-year discount
                    pv_sim = fcff_sim * ((1 + w_sim)**-(y-0.5))
                    pv_sum += pv_sim
                    prev_rev_sim = rev_sim
                    
                    if y == 5:
                        fcf5_sim = fcff_sim
                        ebitda5_sim = ebit_sim + da_sim
                        da5_sim = da_sim
                
                # Terminal Values
                # Normalize Capex using slider ratio
                term_capex_sim = da5_sim * term_cap_ratio
                fcf5_norm_sim = (ebitda5_sim - da5_sim)*(1-tax_rate) + da5_sim - term_capex_sim
                
                tv_g_sim = fcf5_norm_sim * (1+safe_ltg_sim)/(w_sim-safe_ltg_sim)
                pv_tv_g_sim = tv_g_sim * ((1+w_sim)**-5)
                
                tv_e_sim = ebitda5_sim * exit_mult
                pv_tv_e_sim = tv_e_sim * ((1+w_sim)**-5)
                
                w_cons_sim = w_sim + 0.01
                safe_ltg_cons = min(safe_ltg_sim, w_cons_sim - 0.015)
                tv_c_sim = fcf5_norm_sim * (1+safe_ltg_cons)/(w_cons_sim-safe_ltg_cons)
                pv_tv_c_sim = tv_c_sim * ((1+w_sim)**-5)
                
                ev_g = pv_sum + pv_tv_g_sim
                ev_c = pv_sum + pv_tv_c_sim
                ev_e = pv_sum + pv_tv_e_sim
                
                share_g = (ev_g - (debt_in - cash_in)) / shares_in
                share_c = (ev_c - (debt_in - cash_in)) / shares_in
                share_e = (ev_e - (debt_in - cash_in)) / shares_in
                
                avg_share_price = (share_g + share_c + share_e) / 3
                sim_results.append(avg_share_price)
            
            # FIXED CHART: Use clean Numpy Bins
            sim_df = pd.DataFrame(sim_results, columns=["Price"])
            sim_df = sim_df[(sim_df['Price'] > 0) & (sim_df['Price'] < cur_price * 4)]
            
            counts, bins = np.histogram(sim_df['Price'], bins=30)
            bin_mids = [f"{curr_symbol}{(bins[i]+bins[i+1])/2:.0f}" for i in range(len(bins)-1)]
            
            hist_df = pd.DataFrame({"Frequency": counts}, index=bin_mids)
            st.bar_chart(hist_df, color="#60a5fa")
            
            p10 = np.percentile(sim_results, 10)
            p50 = np.percentile(sim_results, 50)
            p90 = np.percentile(sim_results, 90)
            
            st.markdown(f"""
            <div style="display:flex; justify-content: space-between; font-size: 12px; margin-top: 10px;">
                <div class="status-over">P10 (Bear): {curr_symbol}{p10:,.2f}</div>
                <div class="text-blue">P50 (Base): {curr_symbol}{p50:,.2f}</div>
                <div class="status-under">P90 (Bull): {curr_symbol}{p90:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
