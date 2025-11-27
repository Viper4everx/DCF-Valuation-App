import streamlit as st
import pandas as pd
import yfinance as yf
import re

# ==========================================
# 1. CONFIGURATION & STYLING
# ==========================================
st.set_page_config(page_title="Valuation Dashboard", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
body { font-family: 'Inter', sans-serif; background: linear-gradient(135deg, #1e1e2f 0%, #2a2a3e 100%); color: #f0f2f6; }

/* Cards */
.glass-card { background: rgba(255,255,255,0.05); border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; }
.val-card { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 24px; border: 1px solid rgba(255,255,255,0.08); height: 100%; transition: transform 0.2s; }
.val-card:hover { transform: translateY(-3px); }

/* Status & Text Colors */
.status-under { color: #4ade80; font-weight: 700; }
.status-over { color: #f87171; font-weight: 700; }
.text-purple { color: #a78bfa; }
.text-green { color: #34d399; }
.text-blue { color: #60a5fa; }
.border-purple { border-left: 5px solid #8b5cf6; }
.border-green { border-left: 5px solid #10b981; }

/* Typography */
.val-label { font-size: 11px; font-weight: 700; opacity: 0.5; letter-spacing: 1px; text-transform: uppercase; }
.val-price { font-size: 42px; font-weight: 700; margin: 4px 0 16px 0; color: #fff; }
.val-title { font-size: 18px; font-weight: 600; margin-bottom: 4px; color: #fff; }
.val-sub { font-size: 12px; opacity: 0.6; margin-bottom: 20px; }
.val-ev { font-size: 14px; opacity: 0.8; display: flex; justify-content: space-between; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 12px; }

/* STATIC TABLE STYLING */
.custom-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; }
.custom-table th { text-align: center; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.2); color: rgba(255,255,255,0.8); font-weight: 600; }
.custom-table td { text-align: right; padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); font-family: 'Inter', monospace; }
.custom-table tr:hover { background: rgba(255,255,255,0.02); }
.custom-table td:first-child { text-align: left; font-weight: 600; color: rgba(255,255,255,0.9); }

/* Overrides */
div[data-testid="stExpander"] { background-color: rgba(255,255,255,0.02); border-radius: 12px; }
th { text-align: center !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="text-align:center; margin-bottom: 30px;">Yahoo Finance ➜ DCF Model</h1>', unsafe_allow_html=True)

# ==========================================
# 2. DATA ENGINE (Smart FX + Industry)
# ==========================================
@st.cache_data(show_spinner=False)
def get_yahoo_data(ticker):
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        
        # 1. Market & Meta Data
        price = 0.0
        try: price = tk.fast_info.last_price
        except: 
            hist = tk.history(period="1d")
            if not hist.empty: price = hist['Close'].iloc[-1]

        shares = 0.0
        try: shares = tk.info.get('sharesOutstanding')
        except: pass
        if not shares: shares = tk.fast_info.shares_outstanding
        if not shares: shares = 1000000000
        shares = shares / 1e9 

        industry = info.get('industry', 'Unknown')
        
        # 2. Currency Logic (Auto-Convert to Price Currency)
        price_curr = info.get('currency', 'USD')
        fin_curr = info.get('financialCurrency', price_curr)
        
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
                fx_msg = f"⚠️ FX Error: Data remains in {fin_curr}."

        # 3. Financial Statements
        inc = tk.income_stmt
        bs = tk.balance_sheet
        cf = tk.cashflow
        
        if inc.empty: raise ValueError("Empty financials")

        def get_val(df, keys):
            if df.empty: return 0.0
            for k in keys:
                if k in df.index: return df.loc[k].iloc[0]
            return 0.0

        data = {}
        factor = fx_rate / 1e9
        
        data['Revenue'] = get_val(inc, ['Total Revenue', 'Total Net Sales', 'Total Interest Income']) * factor
        data['EBIT']    = get_val(inc, ['Operating Income', 'EBIT', 'Operating Profit']) * factor
        
        data['Depreciation'] = get_val(cf, ['Depreciation And Amortization']) * factor
        if data['Depreciation'] == 0:
             data['Depreciation'] = get_val(inc, ['Reconciled Depreciation']) * factor

        data['Capex'] = abs(get_val(cf, ['Capital Expenditure', 'Capital Expenditures'])) * factor
        data['Debt'] = get_val(bs, ['Total Debt', 'Long Term Debt And Capital Lease Obligation']) * factor
        data['Cash'] = get_val(bs, ['Cash And Cash Equivalents', 'Cash, Cash Equivalents And Short Term Investments']) * factor
        
        return data, price, shares, fx_msg, price_curr, industry
    except Exception as e:
        return None, 0.0, 1.0, str(e), "USD", "Unknown"

# ==========================================
# 3. HELPER: CSV PARSER
# ==========================================
@st.cache_data
def parse_industry_csv(file):
    try:
        df = pd.read_csv(file)
        # Normalize column names to find 'Industry' and 'Multiple'
        df.columns = [c.lower().strip() for c in df.columns]
        
        # Find the right columns
        ind_col = next((c for c in df.columns if 'industry' in c or 'sector' in c), None)
        mult_col = next((c for c in df.columns if 'multiple' in c or 'exit' in c or 'ebitda' in c), None)
        
        if ind_col and mult_col:
            # Convert to dictionary {Industry: Multiple}
            return dict(zip(df[ind_col], df[mult_col]))
        return None
    except:
        return None

# ==========================================
# 4. UI: INPUTS & SIDEBAR
# ==========================================
c_tick, c_space = st.columns([1, 4])
ticker = c_tick.text_input("Ticker", "NVDA").upper()

# Initialize Session
if 'y0' not in st.session_state:
    st.session_state.y0 = {k:0.0 for k in ['Revenue','EBIT','Depreciation','Capex','Debt','Cash']}

curr_symbol = "$"
fx_info = ""
industry_name = "Unknown"

# Auto-Fetch Logic
if ticker:
    with st.spinner(f"Fetching data for {ticker}..."):
        if 'last_ticker' not in st.session_state or st.session_state.last_ticker != ticker:
            d, cur_price, shares_def, fx_msg, currency, ind_name = get_yahoo_data(ticker)
            if d:
                st.session_state.y0 = d
                st.session_state.last_price = cur_price
                st.session_state.last_shares = shares_def
                st.session_state.last_ticker = ticker
                st.session_state.fx_msg = fx_msg
                st.session_state.currency = currency
                st.session_state.industry = ind_name
            else:
                st.error(f"Ticker error: {fx_msg}")
                cur_price, shares_def = 0.0, 1.0
                st.session_state.fx_msg = ""
                st.session_state.currency = "USD"
                st.session_state.industry = "Unknown"
        else:
            cur_price = st.session_state.last_price
            shares_def = st.session_state.last_shares
            fx_info = st.session_state.get('fx_msg', "")
            curr_code = st.session_state.get('currency', 'USD')
            industry_name = st.session_state.get('industry', 'Unknown')
            
            curr_symbol = "€" if curr_code == 'EUR' else "£" if curr_code == 'GBP' else "¥" if curr_code in ['CNY','JPY'] else "$"

    if st.session_state.get('fx_msg'):
        st.info(f"💱 {st.session_state.fx_msg}")

# Year 0 Form
st.markdown("### Year 0: Base Financials (Billions)")
with st.expander("Expand to edit Year 0 Data", expanded=True):
    with st.form("y0_form"):
        c1, c2, c3, c4 = st.columns(4)
        r_in = c1.number_input("Revenue", value=st.session_state.y0['Revenue'], format="%.3f")
        e_in = c2.number_input("EBIT", value=st.session_state.y0['EBIT'], format="%.3f")
        d_in = c3.number_input("D&A", value=st.session_state.y0['Depreciation'], format="%.3f")
        c_in = c4.number_input("Capex", value=st.session_state.y0['Capex'], format="%.3f")
        c5, c6, c7 = st.columns(3)
        debt_in = c5.number_input("Total Debt", value=st.session_state.y0['Debt'], format="%.3f")
        cash_in = c6.number_input("Total Cash", value=st.session_state.y0['Cash'], format="%.3f")
        shares_in = c7.number_input("Shares (B)", value=shares_def, format="%.3f")
        st.form_submit_button("Update Model")

# ==========================================
# 5. SIDEBAR: FILE UPLOAD & LOGIC
# ==========================================
with st.sidebar:
    st.header("Settings")
    
    # --- FILE UPLOADER FOR MULTIPLES ---
    uploaded_file = st.file_uploader("Upload Exit Multiples (CSV)", type=["csv"])
    industry_map = {}
    
    if uploaded_file is not None:
        industry_map = parse_industry_csv(uploaded_file)
        if industry_map:
            st.success(f"Loaded {len(industry_map)} Industry Multiples!")
        else:
            st.warning("Could not parse CSV. Ensure columns 'Industry' and 'Multiple' exist.")
    
    wacc = st.number_input("WACC %", value=9.0, step=0.1, format="%.1f", key=f"wacc_{ticker}") / 100
    
    st.divider()
    st.subheader("Drivers")
    st.caption(f"Detected Industry: {industry_name}")
    
    # --- SMART DEFAULTS LOGIC ---
    current_margin = (e_in / r_in) if r_in > 0 else 0.0
    
    # 1. Try Uploaded CSV Match First
    # Use loose matching (e.g. "Semiconductors" in "Semiconductors & Equipment")
    found_mult = None
    if industry_map and industry_name != "Unknown":
        for ind_key, mult_val in industry_map.items():
            if str(ind_key).lower() in industry_name.lower() or industry_name.lower() in str(ind_key).lower():
                found_mult = float(mult_val)
                break
    
    if found_mult:
        def_mult = found_mult
        # Heuristic: High multiple industries usually grow faster
        def_growth = 15.0 if def_mult > 20 else 5.0
    else:
        # 2. Fallback to Margin Logic
        if current_margin > 0.30: def_growth, def_mult = 15.0, 25.0
        elif current_margin < 0.10: def_growth, def_mult = 3.0, 8.0
        else: def_growth, def_mult = 5.0, 12.0
    
    g_rev = st.number_input("Revenue Growth %", value=def_growth, step=0.5, format="%.1f", key=f"g_{ticker}") / 100
    m_def = (current_margin * 100)
    margin_tgt = st.number_input("EBIT Margin %", value=float(f"{m_def:.1f}"), step=0.5, format="%.1f", key=f"m_{ticker}") / 100
    tax_rate = st.number_input("Tax Rate %", value=21.0, step=1.0, format="%.1f", key=f"t_{ticker}") / 100
    ltg = st.number_input("Terminal Growth %", value=2.5, step=0.1, format="%.1f", key=f"l_{ticker}") / 100
    exit_mult = st.number_input("Exit Multiple (x)", value=def_mult, step=0.5, format="%.1f", key=f"e_{ticker}")

# Calculations
years = range(1, 6)
data = []
safe_ltg = ltg if ltg < wacc else (wacc - 0.005)

if r_in > 0:
    nopat0 = e_in * (1 - tax_rate)
    fcff0 = nopat0 + d_in - c_in
    data.append({'Year': 0, 'Revenue': r_in, 'EBIT': e_in, 'NOPAT': nopat0, 'D&A': d_in, 'Capex': c_in, 'FCFF': fcff0, 'PV': 0.0})

    cap_r, dep_r, nwc_r = c_in/r_in, d_in/r_in, 0.02
    prev_rev = r_in

    for y in years:
        rev = prev_rev * (1 + g_rev)
        ebit = rev * margin_tgt
        nopat = ebit * (1 - tax_rate)
        da, capex = rev * dep_r, rev * cap_r
        dnwc = (rev - prev_rev) * nwc_r
        fcff = nopat + da - capex - dnwc
        pv = fcff * ((1 + wacc)**-y)
        data.append({'Year':y,'Revenue':rev,'EBIT':ebit,'NOPAT':nopat,'D&A':da,'Capex':capex,'FCFF':fcff,'PV':pv})
        prev_rev = rev
else:
    for y in range(0, 6): data.append({'Year':y,'Revenue':0.0,'EBIT':0.0,'NOPAT':0.0,'D&A':0.0,'Capex':0.0,'FCFF':0.0,'PV':0.0})

df = pd.DataFrame(data).set_index('Year')
sum_pv = df.loc[1:5, 'PV'].sum()

# Valuation
p_g, p_e, avg_int, mos_pct, ev_g, ev_e = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
if r_in > 0:
    fcf5 = df.loc[5,'FCFF']
    ebitda5 = df.loc[5,'EBIT'] + df.loc[5,'D&A']
    
    tv_g = fcf5 * (1+safe_ltg)/(wacc-safe_ltg)
    pv_tv_g = tv_g * ((1+wacc)**-5)
    ev_g = sum_pv + pv_tv_g
    p_g = (ev_g - (debt_in - cash_in)) / shares_in
    
    tv_e = ebitda5 * exit_mult
    pv_tv_e = tv_e * ((1+wacc)**-5)
    ev_e = sum_pv + pv_tv_e
    p_e = (ev_e - (debt_in - cash_in)) / shares_in
    
    avg_int = (p_g + p_e) / 2
    if cur_price > 0: mos_pct = (avg_int - cur_price) / cur_price

# ==========================================
# 6. VISUALIZATION
# ==========================================
st.divider()

if cur_price > 0 and r_in > 0:
    s_col = "status-under" if mos_pct >= 0 else "status-over"
    s_txt = "UNDERVALUED" if mos_pct >= 0 else "OVERVALUED"
    st.markdown(f"""
    <div class="glass-card" style="display:flex; justify-content: space-around; align-items: center;">
        <div style="text-align:center;"><div class="val-label">CURRENT PRICE</div><div class="val-price">{curr_symbol}{cur_price:.2f}</div></div>
        <div style="text-align:center;"><div class="val-label">INTRINSIC VALUE</div><div class="val-price text-blue">{curr_symbol}{avg_int:.2f}</div></div>
        <div style="text-align:center;"><div class="val-label">UPSIDE</div><div class="val-price {s_col}">{mos_pct:+.1%}</div><div class="{s_col}">{s_txt}</div></div>
    </div>
    """, unsafe_allow_html=True)

st.subheader(f"Projected Free Cash Flow (Millions {curr_symbol})")
df_display = (df * 1000).T
df_display.columns = [f"Year {y}" for y in df_display.columns]
html_table = df_display.to_html(classes="custom-table", float_format="{:,.2f}".format, border=0)
st.markdown(html_table, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

c_g, c_e = st.columns(2)
def make_bridge(pv_fcf, pv_tv, ev, debt, cash, eq):
    return pd.DataFrame({
        "Component": ["PV of 5y Cash Flows", "PV of Terminal", "Enterprise Value", "Less: Net Debt", "Equity Value"],
        "Value": [pv_fcf, pv_tv, ev, debt-cash, eq]
    }).set_index("Component")

bridge_config = {"Value": st.column_config.NumberColumn(format=f"{curr_symbol}%.2fB")}

with c_g:
    st.markdown(f"""<div class="val-card border-purple"><div class="val-title">Perpetuity Growth 🌊</div><div class="val-sub">Based on {safe_ltg:.1%} long-term growth</div><div class="val-label">IMPLIED SHARE PRICE</div><div class="val-price text-purple">{curr_symbol}{p_g:.2f}</div><div class="val-ev"><span>Enterprise Value</span><strong>{curr_symbol}{ev_g:.2f}B</strong></div></div>""", unsafe_allow_html=True)
    st.markdown("##### Bridge (Gordon)")
    st.dataframe(make_bridge(sum_pv, pv_tv_g, ev_g, debt_in, cash_in, ev_g-(debt_in-cash_in)), use_container_width=True, column_config=bridge_config)

with c_e:
    st.markdown(f"""<div class="val-card border-green"><div class="val-title">Exit Multiple 💼</div><div class="val-sub">Based on {exit_mult}x EBITDA multiple</div><div class="val-label">IMPLIED SHARE PRICE</div><div class="val-price text-green">{curr_symbol}{p_e:.2f}</div><div class="val-ev"><span>Enterprise Value</span><strong>{curr_symbol}{ev_e:.2f}B</strong></div></div>""", unsafe_allow_html=True)
    st.markdown("##### Bridge (Multiple)")
    st.dataframe(make_bridge(sum_pv, pv_tv_e, ev_e, debt_in, cash_in, ev_e-(debt_in-cash_in)), use_container_width=True, column_config=bridge_config)
