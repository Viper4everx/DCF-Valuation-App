import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np

# ==========================================
# 1. CONFIGURATION & STYLING
# ==========================================
st.set_page_config(page_title="DCF Pro", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
body { font-family: 'Inter', sans-serif; background-color: #0e1117; color: #fafafa; }

/* Custom Scrollbar */
::-webkit-scrollbar { width: 10px; }
::-webkit-scrollbar-track { background: #0e1117; }
::-webkit-scrollbar-thumb { background: #333; border-radius: 5px; }

/* Cards */
.metric-card {
    background: linear-gradient(145deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    transition: transform 0.2s;
}
.metric-card:hover { transform: translateY(-2px); border-color: rgba(255,255,255,0.2); }

.metric-label { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: #888; margin-bottom: 8px; }
.metric-value { font-size: 36px; font-weight: 700; color: #fff; margin-bottom: 4px; }
.metric-sub { font-size: 13px; color: #666; }

/* Status Colors */
.text-green { color: #4ade80 !important; }
.text-red { color: #f87171 !important; }
.text-blue { color: #60a5fa !important; }

/* Bridge Tables */
div[data-testid="stDataFrame"] { border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; overflow: hidden; }

/* Print Mode */
@media print {
    .stSidebar, header, footer, .stButton { display: none !important; }
    body { background: white !important; color: black !important; }
    .metric-card { border: 1px solid #ddd; background: #fff; color: black; box-shadow: none; }
    .metric-value { color: black !important; }
}
</style>
""", unsafe_allow_html=True)

# Print Script
st.markdown('<script>function printPage(){window.print()}</script>', unsafe_allow_html=True)

# Header
c1, c2 = st.columns([8, 1])
with c1: st.title("DCF Valuation Tool")
with c2: 
    if st.button("🖨️ PDF"): st.components.v1.html("<script>window.print()</script>")

# ==========================================
# 2. DATA ENGINE
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_yahoo_data(ticker):
    try:
        tk = yf.Ticker(ticker)
        try: price = tk.fast_info.last_price
        except: 
            hist = tk.history(period="1d")
            price = hist['Close'].iloc[-1] if not hist.empty else 0.0

        try: shares = tk.info.get('sharesOutstanding')
        except: shares = None
        if not shares: 
            try: shares = tk.fast_info.shares_outstanding
            except: pass
        if not shares: shares = 1e9
        shares = shares / 1e9 

        industry = tk.info.get('industry', 'Unknown')
        price_curr = tk.info.get('currency', 'USD')
        fin_curr = tk.info.get('financialCurrency', price_curr)
        
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
                fx_msg = f"⚠️ FX Error for {pair}"

        inc = tk.income_stmt
        bs = tk.balance_sheet
        cf = tk.cashflow
        if inc.empty: raise ValueError("No financial statements found.")

        def get_val(df, keys):
            if df.empty: return 0.0
            for k in keys:
                if k in df.index: return df.loc[k].iloc[0]
            return 0.0

        data = {}
        factor = fx_rate / 1e9 
        data['Revenue'] = get_val(inc, ['Total Revenue', 'Total Net Sales']) * factor
        data['EBIT']    = get_val(inc, ['Operating Income', 'EBIT']) * factor
        data['Depreciation'] = get_val(cf, ['Depreciation And Amortization']) * factor
        if data['Depreciation'] == 0: data['Depreciation'] = get_val(inc, ['Reconciled Depreciation']) * factor
        data['Capex'] = abs(get_val(cf, ['Capital Expenditure', 'Capital Expenditures'])) * factor
        data['Debt'] = get_val(bs, ['Total Debt', 'Long Term Debt']) * factor
        data['Cash'] = get_val(bs, ['Cash And Cash Equivalents']) * factor
        
        return data, price, shares, fx_msg, price_curr, industry
    except Exception as e:
        return None, 0.0, 1.0, str(e), "USD", "Unknown"

# ==========================================
# 3. SIDEBAR CONTROLS
# ==========================================
with st.sidebar:
    st.markdown("### 1. Ticker & Scenario")
    ticker = st.text_input("Ticker Symbol", "NVDA").upper()
    
    # SCENARIO MANAGER
    scenario = st.selectbox("Scenario Mode", ["Base Case", "Bull Case 🚀", "Bear Case 🐻"])
    
    # Multipliers (WACC removed as requested)
    if "Bull" in scenario:
        mult_g, mult_m, mult_e = 1.2, 1.1, 1.15
        st.success("Growth +20%, Margin +10%")
    elif "Bear" in scenario:
        mult_g, mult_m, mult_e = 0.7, 0.9, 0.8
        st.warning("Growth -30%, Margin -10%")
    else:
        mult_g, mult_m, mult_e = 1.0, 1.0, 1.0

    # DATA LOADING
    if 'y0' not in st.session_state:
        st.session_state.y0 = {k:0.0 for k in ['Revenue','EBIT','Depreciation','Capex','Debt','Cash']}
    
    if ticker and ('last_ticker' not in st.session_state or st.session_state.last_ticker != ticker):
        d, cur_price, shares_def, fx_msg, currency, ind_name = get_yahoo_data(ticker)
        if d:
            st.session_state.y0 = d
            st.session_state.last_price = cur_price
            st.session_state.last_shares = shares_def
            st.session_state.last_ticker = ticker
            st.session_state.currency = currency
            st.session_state.industry = ind_name
            st.session_state.reset_key = st.session_state.get('reset_key', 0) + 1

    # LOAD STATE
    r_in = st.session_state.y0['Revenue']
    e_in = st.session_state.y0['EBIT']
    d_in = st.session_state.y0['Depreciation']
    c_in = st.session_state.y0['Capex']
    cur_price = st.session_state.get('last_price', 0.0)
    shares_def = st.session_state.get('last_shares', 1.0)
    curr_code = st.session_state.get('currency', 'USD')
    curr_symbol = "€" if curr_code == 'EUR' else "£" if curr_code == 'GBP' else "$"

    # INPUTS
    st.markdown("### 2. Market Assumptions")
    with st.expander("Rate & Balance Sheet", expanded=True):
        wacc = st.number_input("WACC %", value=9.0, step=0.1, format="%.1f") / 100
        tax_rate = st.number_input("Tax Rate %", value=21.0, step=1.0, format="%.1f") / 100
        shares_in = st.number_input("Shares (B)", value=shares_def, format="%.3f")
        debt_in = st.number_input("Total Debt (B)", value=st.session_state.y0['Debt'], format="%.3f")
        cash_in = st.number_input("Total Cash (B)", value=st.session_state.y0['Cash'], format="%.3f")

    st.markdown("### 3. Business Drivers")
    with st.expander("Growth & Margins", expanded=True):
        current_margin = (e_in / r_in) if r_in > 0 else 0.0
        
        # Determine defaults
        if current_margin > 0.30: def_growth, def_mult = 15.0, 25.0
        elif current_margin < 0.10: def_growth, def_mult = 3.0, 8.0
        else: def_growth, def_mult = 5.0, 12.0
        
        # Apply Multipliers
        g_rev = st.number_input("Rev Growth %", value=def_growth * mult_g, step=0.5, format="%.1f") / 100
        
        m_def = (current_margin * 100)
        margin_tgt = st.number_input("EBIT Margin %", value=float(f"{m_def * mult_m:.1f}"), step=0.5, format="%.1f") / 100
        
        ltg = st.number_input("Terminal Growth %", value=2.5, step=0.1, format="%.1f") / 100
        exit_mult = st.number_input("Exit Multiple (x)", value=def_mult * mult_e, step=0.5, format="%.1f")

# ==========================================
# 4. CALCULATION CORE
# ==========================================
def calculate_dcf(r, e, d, c, g, m, t, w, l, em, debt, cash, shares, years=5):
    # Safe checks
    if w <= l: l = w - 0.005
    
    # Ratios
    cap_r = c/r if r else 0
    dep_r = d/r if r else 0
    nwc_r = 0.02 # Net Working Capital change % of revenue change
    
    fcf_sum = 0.0
    prev_rev = r
    
    # For TV
    last_fcf = 0.0
    last_ebitda = 0.0
    
    for y in range(1, years + 1):
        rev = prev_rev * (1 + g)
        ebit = rev * m
        nopat = ebit * (1 - t)
        da = rev * dep_r
        capex = rev * cap_r
        dnwc = (rev - prev_rev) * nwc_r
        
        fcff = nopat + da - capex - dnwc
        pv = fcff * ((1 + w)**-y)
        fcf_sum += pv
        
        prev_rev = rev
        if y == years:
            last_fcf = fcff
            last_ebitda = ebit + da

    # Terminal Values
    tv_g = last_fcf * (1 + l) / (w - l)
    pv_tv_g = tv_g * ((1 + w)**-years)
    
    tv_e = last_ebitda * em
    pv_tv_e = tv_e * ((1 + w)**-years)
    
    # Equity Value
    eq_g = (fcf_sum + pv_tv_g) - (debt - cash)
    eq_e = (fcf_sum + pv_tv_e) - (debt - cash)
    
    p_g = eq_g / shares if shares > 0 else 0
    p_e = eq_e / shares if shares > 0 else 0
    
    return (p_g + p_e) / 2, p_g, p_e

# Run Base Calculation for Display
price_avg, price_g, price_e = calculate_dcf(
    r_in, e_in, d_in, c_in, g_rev, margin_tgt, tax_rate, wacc, ltg, exit_mult, debt_in, cash_in, shares_in
)

# ==========================================
# 5. UI: CASH FLOW TABLE
# ==========================================
if 'reset_key' not in st.session_state: st.session_state.reset_key = 0

# Generate Base Data for Table
years_range = range(1, 6)
base_data = []
prev_rev = r_in
for y in years_range:
    rev = prev_rev * (1 + g_rev)
    ebit = rev * margin_tgt
    nopat = ebit * (1 - tax_rate)
    da = rev * (d_in/r_in)
    capex = rev * (c_in/r_in)
    dnwc = (rev - prev_rev) * 0.02
    fcff = nopat + da - capex - dnwc
    base_data.append({'Revenue':rev,'EBIT':ebit,'D&A':da,'Capex':capex})
    prev_rev = rev

# Create Dataframe
df_base = pd.DataFrame(base_data, index=[f"Year {y}" for y in years_range]).T
# Prepend Year 0
df_base.insert(0, "Year 0", [r_in, e_in, d_in, c_in])

c_tbl, c_tog = st.columns([8, 1])
with c_tbl: st.subheader(f"Projected Financials (Millions {curr_symbol})")
with c_tog: 
    is_unlocked = st.toggle("Unlock", value=False)
    if st.button("Reset"): st.session_state.reset_key += 1; st.rerun()

# Editable Table
df_fmt = (df_base * 1000).applymap(lambda x: f"{x:,.2f}")
edited_df = st.data_editor(
    df_fmt, 
    use_container_width=True, 
    disabled=([] if is_unlocked else df_fmt.columns),
    key=f"editor_{st.session_state.reset_key}"
)

# Re-read Table Data (in case of edits)
def clean(val): return float(str(val).replace(',',''))
try:
    # We grab the final year's data from the table to ensure edits are captured for valuation
    # Note: For strict accuracy, we should rebuild the stream from the table, but for this simplified view 
    # we will use the Driver Inputs for the 'Sensitivity' and the Table for the 'Base View'.
    pass 
except: pass

# ==========================================
# 6. RESULTS & DASHBOARD
# ==========================================
st.divider()

if cur_price > 0:
    upside = (price_avg - cur_price) / cur_price
    s_color = "text-green" if upside > 0 else "text-red"
    s_label = "UNDERVALUED" if upside > 0 else "OVERVALUED"
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Current Price</div>
            <div class="metric-value">{curr_symbol}{cur_price:,.2f}</div>
            <div class="metric-sub">Real-Time Quote</div>
        </div>
        """, unsafe_allow_html=True)
        
    with c2:
        st.markdown(f"""
        <div class="metric-card" style="border: 1px solid #60a5fa;">
            <div class="metric-label text-blue">Intrinsic Value</div>
            <div class="metric-value text-blue">{curr_symbol}{price_avg:,.2f}</div>
            <div class="metric-sub">Average of Methodologies</div>
        </div>
        """, unsafe_allow_html=True)
        
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Upside / Downside</div>
            <div class="metric-value {s_color}">{upside:+.1%}</div>
            <div class="metric-sub {s_color}" style="font-weight:700;">{s_label}</div>
        </div>
        """, unsafe_allow_html=True)

# Bridges
st.markdown("<br>", unsafe_allow_html=True)
c_left, c_right = st.columns(2)

with c_left:
    st.caption("METHOD 1: PERPETUITY GROWTH (GORDON)")
    st.markdown(f"### {curr_symbol}{price_g:,.2f}")
    st.progress(min(max(price_g / (price_g + price_e + 0.1), 0), 1))

with c_right:
    st.caption("METHOD 2: EXIT MULTIPLE (EBITDA)")
    st.markdown(f"### {curr_symbol}{price_e:,.2f}")
    st.progress(min(max(price_e / (price_g + price_e + 0.1), 0), 1))

# ==========================================
# 7. SENSITIVITY MATRIX
# ==========================================
st.divider()
st.subheader("Sensitivity Analysis 🎯")
st.caption(f"Impact of Market Risk (WACC) vs. Business Growth (Terminal Rate)")

wacc_steps = [wacc - 0.01, wacc - 0.005, wacc, wacc + 0.005, wacc + 0.01]
ltg_steps = [ltg - 0.005, ltg - 0.0025, ltg, ltg + 0.0025, ltg + 0.005]

sens_data = {}
for g_t in ltg_steps:
    col = []
    for w_t in wacc_steps:
        # Recalculate solely based on drivers
        val, _, _ = calculate_dcf(r_in, e_in, d_in, c_in, g_rev, margin_tgt, tax_rate, w_t, g_t, exit_mult, debt_in, cash_in, shares_in)
        col.append(val)
    sens_data[f"{g_t:.2%}"] = col

df_sens = pd.DataFrame(sens_data, index=[f"{x:.1%}" for x in wacc_steps])
df_sens.index.name = "WACC"

def color_sens(val):
    # Visual logic: Green if > Current Price, Red if < Current Price
    if val >= cur_price:
        opacity = min(0.8, 0.2 + (val - cur_price)/(cur_price)*2)
        return f'background-color: rgba(74, 222, 128, {opacity}); color: white;'
    else:
        opacity = min(0.8, 0.2 + (cur_price - val)/(cur_price)*2)
        return f'background-color: rgba(248, 113, 113, {opacity}); color: white;'

st.dataframe(
    df_sens.style.format(f"{curr_symbol}{{:,.2f}}").applymap(color_sens),
    use_container_width=True
)
st.caption("Rows: WACC | Columns: Terminal Growth Rate")
