import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import re
from io import StringIO

# --------------------------------------------------
#  CONFIG & CSS
# --------------------------------------------------
st.set_page_config(page_title="Valuation Dashboard", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
body{font-family:'Inter',sans-serif;background:linear-gradient(135deg,#1e1e2f 0%,#2a2a3e 100%);color:#f0f2f6;}
.glass-card { background: rgba(255,255,255,0.05); border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; }
.val-card { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 24px; border: 1px solid rgba(255,255,255,0.08); height: 100%; transition: transform 0.2s; }
.val-card:hover { transform: translateY(-3px); }
.border-purple { border-left: 5px solid #8b5cf6; } .text-purple { color: #a78bfa; }
.border-green { border-left: 5px solid #10b981; } .text-green { color: #34d399; }
.val-title { font-size: 18px; font-weight: 600; margin-bottom: 4px; color: #fff; }
.val-sub { font-size: 12px; opacity: 0.6; margin-bottom: 20px; }
.val-label { font-size: 11px; font-weight: 700; opacity: 0.5; letter-spacing: 1px; text-transform: uppercase; }
.val-price { font-size: 42px; font-weight: 700; margin: 4px 0 16px 0; color: #fff; }
.val-ev { font-size: 14px; opacity: 0.8; display: flex; justify-content: space-between; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 12px; }
div[data-testid="stExpander"] { background-color: rgba(255,255,255,0.02); border-radius: 12px; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="text-align:center; margin-bottom: 30px;">SEC 10-K ➜ DCF Model</h1>', unsafe_allow_html=True)

# --------------------------------------------------
#  LOGIC: ROBUST PARSER + URL FIXER
# --------------------------------------------------
@st.cache_data(show_spinner=False)
def fetch_text(url):
    try:
        headers = {'User-Agent': 'AnalystTool contact@admin.com'} 
        return requests.get(url, headers=headers).text
    except:
        return ""

def fix_ixbrl_url(url):
    """
    Converts 'https://www.sec.gov/ix?doc=/Archives/...' 
    to 'https://www.sec.gov/Archives/...'
    """
    if "ix?doc=" in url:
        # Split by 'doc=' and take the second part
        # usually /Archives/edgar/data/...
        clean_path = url.split("doc=")[-1]
        # Ensure it starts with the domain
        if clean_path.startswith("/"):
            return "https://www.sec.gov" + clean_path
        return clean_path
    return url

def clean_value(val):
    if isinstance(val, (int, float)):
        if 1990 < val < 2030: return None
        return float(val)
    val = str(val).strip()
    is_neg = '(' in val and ')' in val
    clean = re.sub(r'[^\d\.]', '', val)
    if not clean: return None
    try:
        num = float(clean)
        if 1990 < num < 2030 and num.is_integer(): return None
        return -num if is_neg else num
    except: return None

def extract_year_0(html_text):
    # Initialize defaults so we NEVER return an empty dict (Prevents KeyError)
    data = {k: 0.0 for k in ['Revenue', 'EBIT', 'Depreciation', 'Capex', 'Debt', 'Cash']}
    
    try:
        # REMOVED flavor='lxml' to fix missing dependency error
        dfs = pd.read_html(StringIO(html_text))
    except Exception as e:
        # Fail silently but return the empty data structure
        return data

    patterns = {
        'Revenue': r'Total\s+Net\s+Sales|Net\s+Sales|Total\s+Revenues|Revenue',
        'EBIT': r'Operating\s+Income|Operating\s+Profit|Loss\s+from\s+operations|Income\s+from\s+operations',
        'Depreciation': r'Depreciation\s+and\s+amortization|Depreciation\s+expense',
        'Capex': r'Capital\s+expenditures|Additions\s+to\s+property|Purchase\s+of\s+property',
        'Debt': r'Total\s+Debt|Long-term\s+debt|Notes\s+payable',
        'Cash': r'Cash\s+and\s+cash\s+equivalents|Total\s+cash'
    }
    
    for df in dfs:
        if df.shape[1] < 2: continue
        for idx, row in df.iterrows():
            row_label = str(row[0])
            for key, pattern in patterns.items():
                if data[key] == 0.0:
                    if re.search(pattern, row_label, re.IGNORECASE):
                        for col_val in row[1:]:
                            val = clean_value(col_val)
                            if val is not None:
                                data[key] = val / 1000
                                if key == 'Capex': data[key] = abs(data[key])
                                break 
    return data

# --------------------------------------------------
#  UI: INPUTS
# --------------------------------------------------
c_tick, c_url = st.columns([1, 4])
ticker = c_tick.text_input("Ticker", "").upper()
raw_url = c_url.text_input("SEC 10-K URL", placeholder="Paste SEC link to auto-fill Year 0")

if 'y0' not in st.session_state:
    st.session_state.y0 = {k:0.0 for k in ['Revenue','EBIT','Depreciation','Capex','Debt','Cash']}

if raw_url:
    # AUTO-FIX URL before fetching
    final_url = fix_ixbrl_url(raw_url)
    
    if final_url != raw_url:
        st.caption(f"ℹ️ Converted iXBRL Viewer link to raw HTML: {final_url}")

    with st.spinner("Parsing Tables..."):
        txt = fetch_text(final_url)
        if txt:
            d = extract_year_0(txt)
            # Safe check: only update if we actually found something
            if d['Revenue'] != 0: 
                st.session_state.y0 = d
                st.toast("✅ Data Extracted from Tables!", icon="📊")
            else:
                st.warning("Tables parsed, but no matching Revenue row found. Try entering manually.")
        else:
            st.error("Could not fetch URL. Ensure it is a public SEC link.")

# Live Price
cur_price, shares_def = 0.0, 1.0
if ticker:
    try:
        t = yf.Ticker(ticker)
        cur_price = t.fast_info.last_price or 0.0
        shares_def = (t.fast_info.shares / 1e9) or 1.0
    except: pass

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
        submitted = st.form_submit_button("Update Model")

# --------------------------------------------------
#  UI: SIDEBAR ASSUMPTIONS
# --------------------------------------------------
with st.sidebar:
    st.header("Assumptions")
    wacc = st.number_input("WACC %", 3.0, 15.0, 9.0, 0.1)/100
    st.divider()
    st.subheader("Drivers")
    g_rev = st.slider("Revenue Growth %", 0, 30, 5, 1)/100
    m_def = (e_in/r_in*100) if r_in > 0 else 20.0
    margin_tgt = st.slider("EBIT Margin %", 5, 60, int(m_def), 1)/100
    ltg = st.slider("Terminal Growth %", 1, 5, 2, 1)/100
    exit_mult = st.slider("Exit Multiple", 5, 30, 12, 1)

# --------------------------------------------------
#  CALCULATIONS
# --------------------------------------------------
years = range(1, 6)
data = []

if r_in > 0:
    # 1. ADD YEAR 0
    tax_r = 0.21
    nopat0 = e_in * (1 - tax_r)
    fcff0 = nopat0 + d_in - c_in
    data.append({
        'Year': 0, 'Revenue': r_in, 'EBIT': e_in, 'NOPAT': nopat0, 
        'D&A': d_in, 'Capex': c_in, 'FCFF': fcff0, 'PV': 0.0 
    })

    # 2. CALCULATE YEARS 1-5
    cap_r = c_in/r_in
    dep_r = d_in/r_in
    nwc_r = 0.02
    prev_rev = r_in

    for y in years:
        rev = prev_rev * (1 + g_rev)
        ebit = rev * margin_tgt
        nopat = ebit * (1 - tax_r)
        da = rev * dep_r
        capex = rev * cap_r
        dnwc = (rev - prev_rev) * nwc_r
        fcff = nopat + da - capex - dnwc
        pv = fcff * ((1 + wacc)**-y)
        data.append({'Year':y,'Revenue':rev,'EBIT':ebit,'NOPAT':nopat,'D&A':da,'Capex':capex,'FCFF':fcff,'PV':pv})
        prev_rev = rev
else:
    # Empty State (0-5)
    for y in range(0, 6):
        data.append({'Year':y,'Revenue':0.0,'EBIT':0.0,'NOPAT':0.0,'D&A':0.0,'Capex':0.0,'FCFF':0.0,'PV':0.0})

df = pd.DataFrame(data).set_index('Year')
sum_pv = df.loc[1:5, 'PV'].sum() # Sum future years only

# Valuation Logic
if r_in > 0:
    fcf5 = df.loc[5,'FCFF']
    ebitda5 = df.loc[5,'EBIT'] + df.loc[5,'D&A']
    
    # Gordon
    tv_g = fcf5 * (1+ltg)/(wacc-ltg)
    pv_tv_g = tv_g * ((1+wacc)**-5)
    ev_g = sum_pv + pv_tv_g
    eq_g = ev_g - (debt_in - cash_in)
    p_g = eq_g / shares_in
    
    # Exit
    tv_e = ebitda5 * exit_mult
    pv_tv_e = tv_e * ((1+wacc)**-5)
    ev_e = sum_pv + pv_tv_e
    eq_e = ev_e - (debt_in - cash_in)
    p_e = eq_e / shares_in
else:
    p_g = p_e = ev_g = ev_e = pv_tv_g = pv_tv_e = 0.0

# --------------------------------------------------
#  VISUALIZATION
# --------------------------------------------------
st.divider()

# TABLE
st.subheader("Projected Free Cash Flow (Billions)")
st.dataframe(df.T.style.format("{:,.2f}"), use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True)

# CARDS
col_g, col_e = st.columns(2)

with col_g:
    st.markdown(f"""<div class="val-card border-purple"><div class="val-title">Perpetuity Growth 🌊</div><div class="val-sub">Valuation based on long-term growth (g)</div><div class="val-label">IMPLIED SHARE PRICE</div><div class="val-price text-purple">${p_g:.2f}</div><div class="val-ev"><span>Enterprise Value</span><strong>${ev_g:.2f}B</strong></div></div>""", unsafe_allow_html=True)
    bridge_g = pd.DataFrame({"Component": ["PV of 5y Cash Flows", "PV of Terminal Value", "Enterprise Value", "Less: Net Debt", "Equity Value"], "Value": [sum_pv, pv_tv_g, ev_g, debt_in-cash_in, ev_g-(debt_in-cash_in)]}).set_index("Component")
    st.markdown("##### Bridge (Gordon)")
    st.dataframe(bridge_g.style.format("${:,.2f}B"), use_container_width=True)

with col_e:
    st.markdown(f"""<div class="val-card border-green"><div class="val-title">Exit Multiple 💼</div><div class="val-sub">Valuation based on EBITDA multiple</div><div class="val-label">IMPLIED SHARE PRICE</div><div class="val-price text-green">${p_e:.2f}</div><div class="val-ev"><span>Enterprise Value</span><strong>${ev_e:.2f}B</strong></div></div>""", unsafe_allow_html=True)
    bridge_e = pd.DataFrame({"Component": ["PV of 5y Cash Flows", "PV of Terminal Value", "Enterprise Value", "Less: Net Debt", "Equity Value"], "Value": [sum_pv, pv_tv_e, ev_e, debt_in-cash_in, ev_e-(debt_in-cash_in)]}).set_index("Component")
    st.markdown("##### Bridge (Multiple)")
    st.dataframe(bridge_e.style.format("${:,.2f}B"), use_container_width=True)
