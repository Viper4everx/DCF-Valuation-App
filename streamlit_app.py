import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import re

# --------------------------------------------------
#  CONFIG & STYLING
# --------------------------------------------------
st.set_page_config(page_title="Manual DCF", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
body{font-family:'Inter',sans-serif;background:linear-gradient(135deg,#1e1e2f 0%,#2a2a3e 100%);color:#f0f2f6;}
.glass-card{background:rgba(255,255,255,0.06);border-radius:16px;padding:24px;margin-bottom:24px;box-shadow:0 8px 32px rgba(0,0,0,.37);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.08);}
.metric-tile{background:rgba(255,255,255,.05);border-radius:12px;padding:16px;text-align:center;transition:transform .2s;}.metric-tile:hover{transform:translateY(-4px);}
.metric-value{font-size:24px;font-weight:700;margin:0;}.metric-label{font-size:13px;opacity:.7;margin:0;}
.under{color:#4ade80;}.over{color:#f87171;}.fair{color:#fbbf24;}
div[data-testid="stExpander"] {background-color: rgba(255,255,255,0.02); border-radius: 12px;}
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="text-align:center; margin-bottom: 30px;">Analyst DCF (Manual WACC) 🛠️</h1>', unsafe_allow_html=True)

# --------------------------------------------------
#  HELPER: 10-K SCRAPER (Cached)
# --------------------------------------------------
@st.cache_data(show_spinner=False)
def get_html(url):
    try:
        # User-Agent is required for SEC.gov or they block the request
        return requests.get(url, headers={'User-Agent':'Mozilla/5.0 (Analyst Tool)'}).text
    except:
        return ""

def scrape_val(phrase, txt):
    # Regex looks for the phrase followed by a number (handling brackets for negatives)
    # This assumes the 10-K is in MILLIONS (Standard).
    # It returns the raw number found. Conversion to Billions happens later.
    if not txt: return None
    m = re.search(rf'{phrase}[^>]*>\s*\(?([-\d,]+)\)?', txt, re.I)
    if m:
        try:
            raw = m.group(1).replace(',', '')
            val = float(raw)
            # Handle negative parenthesis notation: (123) -> -123
            if '(' in m.group(0) and ')' in m.group(0): val = -val
            return val 
        except:
            return None
    return None

# --------------------------------------------------
#  SECTION 1: INPUTS (TOP OF PAGE)
# --------------------------------------------------
col_tick, col_url = st.columns([1, 4])

with col_tick:
    ticker = st.text_input("Ticker Symbol", "AAPL").upper()

with col_url:
    sec_url = st.text_input("Paste SEC 10-K URL (Optional)", placeholder="https://www.sec.gov/Archives/edgar/...")

# 1. Fetch Live Price (Reference Only)
cur_price = 0.0
def_shares = 1.0
if ticker:
    try:
        tk = yf.Ticker(ticker)
        # Fast access to price
        cur_price = tk.fast_info.last_price if tk.fast_info.last_price else 0.0
        # Default shares in Billions
        def_shares = tk.fast_info.shares / 1e9 if tk.fast_info.shares else 1.0
    except:
        pass

# 2. Scrape Logic (Runs only if URL changes)
# Initialize defaults
s_rev = s_ebit = s_dep = s_capex = s_debt = s_cash = 0.0

if sec_url:
    with st.spinner("Scraping 10-K Data..."):
        txt = get_html(sec_url)
        if txt:
            # We assume 10-K numbers are in Millions. We divide by 1000 to get Billions.
            f_rev   = scrape_val(r'Revenues?|NetSales|NetRevenues?|TotalRevenues?', txt)
            f_ebit  = scrape_val(r'OperatingIncomeLoss|OperatingIncome|EBIT', txt)
            f_dep   = scrape_val(r'DepreciationDepletionAndAmortization|Depreciation|Amortization', txt)
            f_cap   = scrape_val(r'CapitalExpenditures|PaymentsToAcquirePropertyPlantAndEquipment', txt)
            f_debt  = scrape_val(r'LongTermDebt|NotesPayable', txt)
            f_cash  = scrape_val(r'CashAndCashEquivalents', txt)

            # Apply conversion: Millions -> Billions
            if f_rev: s_rev = f_rev / 1000
            if f_ebit: s_ebit = f_ebit / 1000
            if f_dep: s_dep = f_dep / 1000
            if f_cap: s_capex = abs(f_cap) / 1000
            if f_debt: s_debt = f_debt / 1000
            if f_cash: s_cash = f_cash / 1000

# --------------------------------------------------
#  SECTION 2: FINANCIAL DATA FORM
# --------------------------------------------------
with st.expander("Step 2: Verify & Edit Financial Data (Billions)", expanded=True):
    with st.form("financials_form"):
        c1, c2, c3, c4 = st.columns(4)
        rev_in = c1.number_input("Revenue", value=float(s_rev), format="%.3f")
        ebit_in = c2.number_input("EBIT", value=float(s_ebit), format="%.3f")
        dep_in = c3.number_input("D&A", value=float(s_dep), format="%.3f")
        capex_in = c4.number_input("Capex", value=float(s_capex), format="%.3f")
        
        c5, c6, c7 = st.columns(3)
        debt_in = c5.number_input("Total Debt", value=float(s_debt), format="%.3f")
        cash_in = c6.number_input("Total Cash", value=float(s_cash), format="%.3f")
        shares_in = c7.number_input("Shares (Billions)", value=float(def_shares), format="%.3f")
        
        submitted = st.form_submit_button("Run Valuation Model")

# --------------------------------------------------
#  SECTION 3: SIDEBAR (ASSUMPTIONS)
# --------------------------------------------------
with st.sidebar:
    st.header("Assumptions")
    st.markdown("---")
    wacc_in = st.number_input("WACC % (Discount Rate)", 3.0, 20.0, 9.0, 0.1) / 100
    st.markdown("---")
    
    st.subheader("Growth Drivers")
    g_rev_in = st.slider("Rev Growth %", 0, 30, 5, 1)/100
    
    # Smart Default for Margin
    def_margin = (ebit_in/rev_in*100) if rev_in > 0 else 20.0
    margin_in = st.slider("Target EBIT Margin %", 5, 60, int(def_margin), 1)/100
    
    ltg_in = st.slider("Terminal Growth %", 1, 5, 2, 1)/100
    exit_m_in = st.slider("Exit Multiple", 5, 30, 12, 1)

    # SAFETY CHECK: WACC must be > Long Term Growth for Gordon Growth formula
    if wacc_in <= ltg_in:
        st.error("Error: WACC must be higher than Terminal Growth %")
        st.stop()

# --------------------------------------------------
#  CALCULATIONS
# --------------------------------------------------
# Stop if the user hasn't input anything meaningful yet
if rev_in == 0 and ebit_in == 0 and not submitted:
    st.info("👆 Please enter financial data or paste a URL to generate the model.")
    st.stop()

# 1. Setup
tax_rate = 0.21
net_debt = debt_in - cash_in
years = range(1, 6)
proj_data = []

# Derived Ratios (Safeguarded against div/0)
capex_percent = capex_in / rev_in if rev_in > 0 else 0.04
da_percent = dep_in / rev_in if rev_in > 0 else 0.03
nwc_percent = 0.02

curr_rev = rev_in

# 2. Projection Loop
for y in years:
    next_rev = curr_rev * (1 + g_rev_in)
    next_ebit = next_rev * margin_in
    next_tax = next_ebit * tax_rate
    next_nopat = next_ebit - next_tax
    next_da = next_rev * da_percent
    next_capex = next_rev * capex_percent
    dnwc = (next_rev - curr_rev) * nwc_percent
    
    fcff = next_nopat + next_da - next_capex - dnwc
    
    # Discounting
    pv_factor = (1 / (1 + wacc_in)) ** y
    pv_fcff = fcff * pv_factor
    
    proj_data.append({
        "Year": y, "Revenue": next_rev, "EBIT": next_ebit, "NOPAT": next_nopat,
        "D&A": next_da, "Capex": next_capex, "FCFF": fcff, "PV": pv_fcff
    })
    curr_rev = next_rev

df = pd.DataFrame(proj_data).set_index("Year")
sum_pv_fcf = df["PV"].sum()

# 3. Terminal Value
final_fcf = df.loc[5, "FCFF"]
final_ebitda = df.loc[5, "EBIT"] + df.loc[5, "D&A"]

# Gordon Growth Formula
tv_gordon = final_fcf * (1 + ltg_in) / (wacc_in - ltg_in)
pv_tv_gordon = tv_gordon * ((1/(1+wacc_in))**5)

# Exit Multiple Formula
tv_exit = final_ebitda * exit_m_in
pv_tv_exit = tv_exit * ((1/(1+wacc_in))**5)

# 4. Valuation Logic
def get_val(pv_tv):
    ev = sum_pv_fcf + pv_tv
    eq = ev - net_debt # Equity Value
    share_price = eq / shares_in if shares_in > 0 else 0
    return share_price

target_gordon = get_val(pv_tv_gordon)
target_exit = get_val(pv_tv_exit)
target_avg = (target_gordon + target_exit) / 2

mos = (target_avg - cur_price) / cur_price if cur_price > 0 else 0

# Verdict Logic
if mos >= 0.15:   v_cls, v_txt = "under", "Undervalued"
elif mos <= -0.15: v_cls, v_txt = "over", "Overvalued"
else:              v_cls, v_txt = "fair", "Fairly Valued"

# --------------------------------------------------
#  DISPLAY RESULTS
# --------------------------------------------------
st.divider()

# Metric Cards
st.markdown('<div class="glass-card">', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
c1.markdown(f'<div class="metric-tile"><p class="metric-value">${target_avg:,.2f}</p><p class="metric-label">Intrinsic Value</p></div>', unsafe_allow_html=True)
c2.markdown(f'<div class="metric-tile"><p class="metric-value">${cur_price:,.2f}</p><p class="metric-label">Market Price</p></div>', unsafe_allow_html=True)
c3.markdown(f'<div class="metric-tile"><p class="metric-value {v_cls}">{mos:+.1%}</p><p class="metric-label">Margin of Safety</p></div>', unsafe_allow_html=True)
c4.markdown(f'<div class="metric-tile"><p class="metric-value" style="color:#fbbf24">{wacc_in:.1%}</p><p class="metric-label">Manual WACC</p></div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# Tabs
tab1, tab2 = st.tabs(["📊 Projections", "📑 Valuation Bridge"])

with tab1:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("Projected Free Cash Flows (Billions)")
    st.dataframe(df.style.format("{:,.2f}"), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    bc1, bc2 = st.columns(2)
    
    def bridge(tv_val, pv_tv, imp_price, method):
        st.markdown(f"#### {method}")
        st.write(pd.DataFrame({
            "Metric": ["PV of 5y FCF", "PV of Terminal", "Enterprise Value", "Less: Net Debt", "Equity Value", "Implied Price"],
            "Value": [sum_pv_fcf, pv_tv, sum_pv_fcf+pv_tv, net_debt, (sum_pv_fcf+pv_tv)-net_debt, imp_price]
        }).style.format({"Value":"{:,.2f}"}))

    with bc1: bridge(tv_gordon, pv_tv_gordon, target_gordon, "Gordon Growth")
    with bc2: bridge(tv_exit, pv_tv_exit, target_exit, "Exit Multiple")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f'<div class="glass-card"><h3>Verdict: <span class="{v_cls}">{v_txt}</span></h3></div>', unsafe_allow_html=True)
