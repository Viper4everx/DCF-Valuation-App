import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import re

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
.status-under { color: #4ade80; font-weight: 700; }
.status-over { color: #f87171; font-weight: 700; }
.val-title { font-size: 18px; font-weight: 600; margin-bottom: 4px; color: #fff; }
.val-label { font-size: 11px; font-weight: 700; opacity: 0.5; letter-spacing: 1px; text-transform: uppercase; }
.val-price { font-size: 42px; font-weight: 700; margin: 4px 0 16px 0; color: #fff; }
div[data-testid="stExpander"] { background-color: rgba(255,255,255,0.02); border-radius: 12px; }
th { text-align: center !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="text-align:center; margin-bottom: 30px;">SEC 10-K ➜ DCF Model</h1>', unsafe_allow_html=True)

# --------------------------------------------------
#  LOGIC: "WIDE-NET" SCRAPER (V4)
# --------------------------------------------------
@st.cache_data(show_spinner=False)
def fetch_text_blob(url):
    try:
        if "ix?doc=" in url:
            clean_path = url.split("doc=")[-1]
            url = "https://www.sec.gov" + clean_path if clean_path.startswith("/") else clean_path
        
        headers = {'User-Agent': 'AnalystTool contact@admin.com'} 
        html = requests.get(url, headers=headers).text
        
        # Clean HTML to Text
        text = html.replace('>', '> ') 
        text = text.replace('&nbsp;', ' ').replace('&#160;', ' ')
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=re.DOTALL) 
        text = re.sub(r'<[^>]+>', ' ', text) 
        text = re.sub(r'\s+', ' ', text) 
        return text
    except:
        return ""

def extract_from_blob(blob):
    data = {k: 0.0 for k in ['Revenue', 'EBIT', 'Depreciation', 'Capex', 'Debt', 'Cash']}
    debug_log = []

    def find_near(keywords, metric_name):
        for kw in keywords:
            matches = [m.start() for m in re.finditer(re.escape(kw), blob, re.IGNORECASE)]
            
            for pos in matches:
                # Increased lookahead to 1000 chars to skip over text descriptions
                snippet = blob[pos:pos+1000]
                
                # Updated Regex: Allows space after comma (e.g. "10, 000")
                # Must have at least one comma to filter out years (2024)
                nums = re.findall(r'\(?(\d{1,3}(?:,\s?\d{3})+)\)?', snippet)
                
                if len(debug_log) < 10:
                    debug_log.append(f"Checked '{kw}': Found {nums[:3]}...")

                for n in nums:
                    val_str = n.replace(',', '').replace(' ', '') # Remove comma and space
                    try:
                        val = float(val_str)
                        if f"({n})" in snippet: val = -val # Handle negatives
                        return val / 1000 # Millions -> Billions
                    except: continue
        return 0.0

    # EXPANDED KEYWORDS (For Merck/Pharma/Tech)
    data['Revenue'] = find_near(['Total sales', 'Product sales', 'Net sales', 'Total net revenues', 'Net revenues', 'Revenue'], 'Revenue')
    data['EBIT']    = find_near(['Operating income', 'Earnings from operations', 'Operating profit', 'Loss from operations'], 'EBIT')
    data['Depreciation'] = find_near(['Depreciation and amortization', 'Depreciation expense'], 'D&A')
    data['Capex']   = abs(find_near(['Additions to property', 'Capital expenditures', 'Purchases of property', 'Capital additions'], 'Capex'))
    data['Debt']    = find_near(['Total debt', 'Long-term debt', 'Notes payable'], 'Debt')
    data['Cash']    = find_near(['Cash and cash equivalents', 'Total cash'], 'Cash')
    
    return data, debug_log

# --------------------------------------------------
#  UI: INPUTS
# --------------------------------------------------
c_tick, c_url = st.columns([1, 4])
ticker = c_tick.text_input("Ticker", "MRK").upper()
raw_url = c_url.text_input("SEC 10-K URL", placeholder="Paste SEC link (iXBRL or HTML supported)")

if 'y0' not in st.session_state:
    st.session_state.y0 = {k:0.0 for k in ['Revenue','EBIT','Depreciation','Capex','Debt','Cash']}

if raw_url:
    with st.spinner("Scraping (Wide-Net Mode)..."):
        blob_text = fetch_text_blob(raw_url)
        if blob_text:
            d, logs = extract_from_blob(blob_text)
            
            if d['Revenue'] != 0: 
                st.session_state.y0 = d
                st.toast("✅ Data Found!", icon="🔥")
            else:
                st.error("Scraper scanned text but didn't find Revenue. Check the debug log below.")
                with st.expander("🕵️ Debugger"):
                    st.write("Keywords matched but rejected (or no numbers found):")
                    for l in logs: st.code(l)
                    st.write("Raw Text Start:")
                    st.write(blob_text[:1000])

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
#  UI: SIDEBAR
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
    # Year 0
    tax_r = 0.21
    nopat0 = e_in * (1 - tax_r)
    fcff0 = nopat0 + d_in - c_in
    data.append({'Year': 0, 'Revenue': r_in, 'EBIT': e_in, 'NOPAT': nopat0, 'D&A': d_in, 'Capex': c_in, 'FCFF': fcff0, 'PV': 0.0})

    # Years 1-5
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
    for y in range(0, 6): data.append({'Year':y,'Revenue':0.0,'EBIT':0.0,'NOPAT':0.0,'D&A':0.0,'Capex':0.0,'FCFF':0.0,'PV':0.0})

df = pd.DataFrame(data).set_index('Year')
sum_pv = df.loc[1:5, 'PV'].sum()

# Valuation
if r_in > 0:
    fcf5 = df.loc[5,'FCFF']
    ebitda5 = df.loc[5,'EBIT'] + df.loc[5,'D&A']
    
    tv_g = fcf5 * (1+ltg)/(wacc-ltg)
    pv_tv_g = tv_g * ((1+wacc)**-5)
    ev_g = sum_pv + pv_tv_g
    eq_g = ev_g - (debt_in - cash_in)
    p_g = eq_g / shares_in
    
    tv_e = ebitda5 * exit_mult
    pv_tv_e = tv_e * ((1+wacc)**-5)
    ev_e = sum_pv + pv_tv_e
    eq_e = ev_e - (debt_in - cash_in)
    p_e = eq_e / shares_in
    
    avg_intrinsic = (p_g + p_e) / 2
    mos_pct = (avg_intrinsic - cur_price) / cur_price if cur_price > 0 else 0.0
else:
    p_g = p_e = ev_g = ev_e = pv_tv_g = pv_tv_e = avg_intrinsic = mos_pct = 0.0

# --------------------------------------------------
#  VISUALIZATION
# --------------------------------------------------
st.divider()

if cur_price > 0 and r_in > 0:
    status_color = "status-under" if mos_pct >= 0 else "status-over"
    status_text = "UNDERVALUED" if mos_pct >= 0 else "OVERVALUED"
    st.markdown(f"""
    <div class="glass-card" style="display:flex; justify-content: space-around; align-items: center;">
        <div style="text-align:center;"><div class="val-label">CURRENT PRICE</div><div class="val-price">${cur_price:.2f}</div></div>
        <div style="text-align:center;"><div class="val-label">AVG INTRINSIC VALUE</div><div class="val-price text-blue">${avg_intrinsic:.2f}</div></div>
        <div style="text-align:center;"><div class="val-label">UPSIDE / DOWNSIDE</div><div class="val-price {status_color}">{mos_pct:+.1%}</div><div class="{status_color}">{status_text}</div></div>
    </div>
    """, unsafe_allow_html=True)

st.subheader("Projected Free Cash Flow (Millions USD)")
df_display = df * 1000 
df_display.index = [f"Year {y}" for y in df_display.index]
st.dataframe(df_display.T.style.format("{:,.2f}"), use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True)

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
