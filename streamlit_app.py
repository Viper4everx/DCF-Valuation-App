import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import re

# ==========================================
# 1. CONFIGURATION & STYLING
# ==========================================
st.set_page_config(page_title="Valuation Dashboard", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
body { font-family: 'Inter', sans-serif; background: linear-gradient(135deg, #1e1e2f 0%, #2a2a3e 100%); color: #f0f2f6; }

/* Cards & Layout */
.glass-card { background: rgba(255,255,255,0.05); border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; }
.val-card { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 24px; border: 1px solid rgba(255,255,255,0.08); height: 100%; transition: transform 0.2s; }
.val-card:hover { transform: translateY(-3px); }

/* Typography */
.val-title { font-size: 18px; font-weight: 600; margin-bottom: 4px; color: #fff; }
.val-sub { font-size: 12px; opacity: 0.6; margin-bottom: 20px; }
.val-label { font-size: 11px; font-weight: 700; opacity: 0.5; letter-spacing: 1px; text-transform: uppercase; }
.val-price { font-size: 42px; font-weight: 700; margin: 4px 0 16px 0; color: #fff; }
.val-ev { font-size: 14px; opacity: 0.8; display: flex; justify-content: space-between; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 12px; }

/* Status Colors */
.status-under { color: #4ade80; font-weight: 700; } /* Green */
.status-over { color: #f87171; font-weight: 700; }  /* Red */
.text-purple { color: #a78bfa; }
.text-green { color: #34d399; }
.text-blue { color: #60a5fa; }
.border-purple { border-left: 5px solid #8b5cf6; }
.border-green { border-left: 5px solid #10b981; }

/* Streamlit Overrides */
div[data-testid="stExpander"] { background-color: rgba(255,255,255,0.02); border-radius: 12px; }
th { text-align: center !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="text-align:center; margin-bottom: 30px;">SEC 10-K ➜ DCF Model</h1>', unsafe_allow_html=True)

# ==========================================
# 2. HELPER FUNCTIONS (THE ENGINE)
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_market_data(ticker):
    """Fetches live price and shares outstanding."""
    if not ticker: return 0.0, 1.0
    try:
        t = yf.Ticker(ticker)
        # Use fast_info for speed, fallbacks for reliability
        price = t.fast_info.last_price or 0.0
        shares = (t.fast_info.shares / 1e9) or 1.0 # Billions
        return price, shares
    except:
        return 0.0, 1.0

@st.cache_data(show_spinner=False)
def fetch_sec_blob(url):
    """Fetches and cleans SEC HTML into a raw text blob."""
    try:
        # Auto-fix iXBRL Viewer links
        if "ix?doc=" in url:
            clean_path = url.split("doc=")[-1]
            url = "https://www.sec.gov" + clean_path if clean_path.startswith("/") else clean_path
        
        headers = {'User-Agent': 'AnalystTool contact@admin.com'} 
        html = requests.get(url, headers=headers).text
        
        # Nuclear Cleaning: Strip ALL tags to find raw text
        text = html.replace('>', '> ') 
        text = text.replace('&nbsp;', ' ').replace('&#160;', ' ')
        text = re.sub(r'\w+:[A-Za-z0-9\._]+', ' ', text) # Remove hidden XBRL tags
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=re.DOTALL) 
        text = re.sub(r'<[^>]+>', ' ', text) 
        text = re.sub(r'\s+', ' ', text) 
        return text
    except:
        return ""

def scrape_financials(blob, unit_div):
    """Scrapes financial metrics from the text blob."""
    data = {k: 0.0 for k in ['Revenue', 'EBIT', 'Depreciation', 'Capex', 'Debt', 'Cash']}
    debug_log = []

    def find_val(keywords, force_positive=False):
        for kw in keywords:
            # Find keyword locations
            matches = [m.start() for m in re.finditer(re.escape(kw), blob, re.IGNORECASE)]
            for pos in matches:
                # Scan 1000 chars after keyword
                snippet = blob[pos:pos+1000]
                # Regex: Finds "123,456" or "(123, 456)" (Requires comma to avoid years)
                nums = re.findall(r'\(?(\d{1,3}(?:,\s?\d{3})+)\)?', snippet)
                
                if nums:
                    if len(debug_log) < 5: debug_log.append(f"Match '{kw}': {nums[0]}")
                    
                for n in nums:
                    val_str = n.replace(',', '').replace(' ', '')
                    try:
                        val = float(val_str)
                        if f"({n})" in snippet: val = -val
                        if force_positive: val = abs(val)
                        return val / unit_div
                    except: continue
        return 0.0

    # Keywords Dictionary
    kw_map = {
        'Revenue': ['Total net revenue', 'Net revenue', 'Net sales', 'Total sales', 'Product sales', 'Total revenues', 'Revenues'],
        'EBIT': ['Operating income', 'Earnings from operations', 'Operating profit', 'Loss from operations'],
        'Depreciation': ['Depreciation and amortization', 'Depreciation expense'],
        'Capex': ['Additions to property', 'Capital expenditures', 'Purchases of property', 'Capital additions'],
        'Debt': ['Total debt', 'Long-term debt', 'Notes payable'],
        'Cash': ['Cash and cash equivalents', 'Total cash']
    }

    data['Revenue'] = find_val(kw_map['Revenue'])
    data['EBIT'] = find_val(kw_map['EBIT'])
    data['Depreciation'] = find_val(kw_map['Depreciation'])
    data['Capex'] = find_val(kw_map['Capex'], force_positive=True) # Always scrape as positive, subtract in logic
    data['Debt'] = find_val(kw_map['Debt'])
    data['Cash'] = find_val(kw_map['Cash'])
    
    return data, debug_log

# ==========================================
# 3. UI: SIDEBAR & INPUTS
# ==========================================
c_tick, c_url = st.columns([1, 4])
ticker = c_tick.text_input("Ticker", "MRK").upper()
raw_url = c_url.text_input("SEC 10-K URL", placeholder="Paste SEC link (iXBRL or HTML supported)")

# Sidebar
with st.sidebar:
    st.header("Assumptions")
    wacc = st.number_input("WACC %", 3.0, 15.0, 9.0, 0.1)/100
    
    st.divider()
    st.subheader("Scraper Settings")
    unit_type = st.selectbox("Filing Units", ["Millions (Standard)", "Thousands", "Billions"])
    if unit_type == "Millions (Standard)": divider = 1000
    elif unit_type == "Thousands": divider = 1000000
    else: divider = 1

    st.divider()
    st.subheader("Drivers")
    # We delay sliders slightly to use scraped data for defaults if available
    
# Logic: Fetch Data
if 'y0' not in st.session_state:
    st.session_state.y0 = {k:0.0 for k in ['Revenue','EBIT','Depreciation','Capex','Debt','Cash']}

if raw_url:
    with st.spinner("Scraping Financials..."):
        blob = fetch_sec_blob(raw_url)
        if blob:
            d, logs = scrape_financials(blob, divider)
            if any(v != 0 for v in d.values()): 
                st.session_state.y0 = d
                if d['Revenue'] == 0: st.warning("Revenue not found. Please check 'Filing Units' or enter manually.")
                else: st.toast("✅ Data Extracted Successfully!", icon="🔥")
            else:
                st.error("No data found. Try changing 'Filing Units'.")

# Logic: Fetch Price
cur_price, shares_def = get_market_data(ticker)

# UI: Year 0 Form
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

# Sidebar Drivers (Now that we have e_in/r_in for defaults)
with st.sidebar:
    g_rev = st.slider("Revenue Growth %", 0, 30, 5, 1)/100
    m_def = (e_in/r_in*100) if r_in > 0 else 20.0
    margin_tgt = st.slider("EBIT Margin %", 5, 60, int(m_def), 1)/100
    tax_rate = st.slider("Tax Rate %", 0, 40, 21, 1)/100
    ltg = st.slider("Terminal Growth %", 1, 5, 2, 1)/100
    exit_mult = st.slider("Exit Multiple", 5, 30, 12, 1)

# ==========================================
# 4. CALCULATION ENGINE
# ==========================================
years = range(1, 6)
data = []

# Safety: Clamp LTG to avoid WACC crash
safe_ltg = ltg if ltg < wacc else (wacc - 0.005)

if r_in > 0:
    # Year 0 Logic
    nopat0 = e_in * (1 - tax_rate)
    fcff0 = nopat0 + d_in - c_in
    data.append({'Year': 0, 'Revenue': r_in, 'EBIT': e_in, 'NOPAT': nopat0, 'D&A': d_in, 'Capex': c_in, 'FCFF': fcff0, 'PV': 0.0})

    # Projections
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
    # Empty State
    for y in range(0, 6): data.append({'Year':y,'Revenue':0.0,'EBIT':0.0,'NOPAT':0.0,'D&A':0.0,'Capex':0.0,'FCFF':0.0,'PV':0.0})

df = pd.DataFrame(data).set_index('Year')
sum_pv = df.loc[1:5, 'PV'].sum()

# Valuation Logic
p_g, p_e, avg_int, mos_pct, ev_g, ev_e = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

if r_in > 0:
    fcf5 = df.loc[5,'FCFF']
    ebitda5 = df.loc[5,'EBIT'] + df.loc[5,'D&A']
    
    # Gordon Growth
    tv_g = fcf5 * (1+safe_ltg)/(wacc-safe_ltg)
    pv_tv_g = tv_g * ((1+wacc)**-5)
    ev_g = sum_pv + pv_tv_g
    p_g = (ev_g - (debt_in - cash_in)) / shares_in
    
    # Exit Multiple
    tv_e = ebitda5 * exit_mult
    pv_tv_e = tv_e * ((1+wacc)**-5)
    ev_e = sum_pv + pv_tv_e
    p_e = (ev_e - (debt_in - cash_in)) / shares_in
    
    avg_int = (p_g + p_e) / 2
    if cur_price > 0: mos_pct = (avg_int - cur_price) / cur_price

# ==========================================
# 5. VISUALIZATION
# ==========================================
st.divider()

# A. Verdict Bar
if cur_price > 0 and r_in > 0:
    s_col = "status-under" if mos_pct >= 0 else "status-over"
    s_txt = "UNDERVALUED" if mos_pct >= 0 else "OVERVALUED"
    st.markdown(f"""
    <div class="glass-card" style="display:flex; justify-content: space-around; align-items: center;">
        <div style="text-align:center;"><div class="val-label">CURRENT PRICE</div><div class="val-price">${cur_price:.2f}</div></div>
        <div style="text-align:center;"><div class="val-label">INTRINSIC VALUE</div><div class="val-price text-blue">${avg_int:.2f}</div></div>
        <div style="text-align:center;"><div class="val-label">UPSIDE</div><div class="val-price {s_col}">{mos_pct:+.1%}</div><div class="{s_col}">{s_txt}</div></div>
    </div>
    """, unsafe_allow_html=True)

# B. Table (Millions)
st.subheader("Projected Free Cash Flow (Millions USD)")
df_disp = df * 1000 
df_disp.index = [f"Year {y}" for y in df_disp.index]
st.dataframe(df_disp.T.style.format("{:,.2f}"), use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True)

# C. Valuation Cards
c_g, c_e = st.columns(2)

def make_bridge(pv_fcf, pv_tv, ev, debt, cash, eq):
    return pd.DataFrame({
        "Component": ["PV of 5y Cash Flows", "PV of Terminal", "Enterprise Value", "Less: Net Debt", "Equity Value"],
        "Value": [pv_fcf, pv_tv, ev, debt-cash, eq]
    }).set_index("Component")

with c_g:
    st.markdown(f"""<div class="val-card border-purple"><div class="val-title">Perpetuity Growth 🌊</div><div class="val-sub">Based on {safe_ltg:.1%} long-term growth</div><div class="val-label">IMPLIED SHARE PRICE</div><div class="val-price text-purple">${p_g:.2f}</div><div class="val-ev"><span>Enterprise Value</span><strong>${ev_g:.2f}B</strong></div></div>""", unsafe_allow_html=True)
    st.markdown("##### Bridge (Gordon)")
    st.dataframe(make_bridge(sum_pv, pv_tv_g, ev_g, debt_in, cash_in, ev_g-(debt_in-cash_in)).style.format("${:,.2f}B"), use_container_width=True)

with c_e:
    st.markdown(f"""<div class="val-card border-green"><div class="val-title">Exit Multiple 💼</div><div class="val-sub">Based on {exit_mult}x EBITDA multiple</div><div class="val-label">IMPLIED SHARE PRICE</div><div class="val-price text-green">${p_e:.2f}</div><div class="val-ev"><span>Enterprise Value</span><strong>${ev_e:.2f}B</strong></div></div>""", unsafe_allow_html=True)
    st.markdown("##### Bridge (Multiple)")
    st.dataframe(make_bridge(sum_pv, pv_tv_e, ev_e, debt_in, cash_in, ev_e-(debt_in-cash_in)).style.format("${:,.2f}B"), use_container_width=True)
