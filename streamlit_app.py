import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import re
import numpy as np

# --------------------------------------------------
#  CONFIG & STYLING
# --------------------------------------------------
st.set_page_config(page_title="Analyst DCF", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
body{font-family:'Inter',sans-serif;background:linear-gradient(135deg,#1e1e2f 0%,#2a2a3e 100%);color:#f0f2f6;}
.glass-card{background:rgba(255,255,255,0.06);border-radius:16px;padding:24px;margin-bottom:24px;box-shadow:0 8px 32px rgba(0,0,0,.37);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.08);}
.metric-tile{background:rgba(255,255,255,.05);border-radius:12px;padding:16px;text-align:center;transition:transform .2s;}.metric-tile:hover{transform:translateY(-4px);}
.metric-value{font-size:24px;font-weight:700;margin:0;}.metric-label{font-size:13px;opacity:.7;margin:0;}
.under{color:#4ade80;}.over{color:#f87171;}.fair{color:#fbbf24;}
div[data-testid="stExpander"] div[role="button"] p {font-size: 1rem; font-weight: 600;}
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="text-align:center;">Analyst DCF Workbench 🛠️</h1>', unsafe_allow_html=True)

# --------------------------------------------------
#  HELPER: LIVE BETA CALCULATION
# --------------------------------------------------
@st.cache_data(ttl=3600)
def calculate_live_beta(ticker):
    # We calculate Beta manually: Covariance(Stock, Market) / Variance(Market)
    # Using 5 years of monthly data
    try:
        data = yf.download([ticker, '^GSPC'], period="5y", interval="1mo", progress=False)['Adj Close']
        # Drop NaN
        data = data.dropna()
        # Calculate Returns
        returns = data.pct_change().dropna()
        
        # Covariance Matrix
        # [0,0] = Var(Market), [0,1] = Cov(Market, Stock)
        # [1,0] = Cov(Stock, Market), [1,1] = Var(Stock)
        cov_matrix = np.cov(returns['^GSPC'], returns[ticker])
        
        var_market = cov_matrix[0, 0]
        cov_stock_market = cov_matrix[0, 1]
        
        raw_beta = cov_stock_market / var_market
        return raw_beta
    except:
        return 1.0 # Default if calculation fails (e.g. IPO < 5y)

# --------------------------------------------------
#  HELPER: 10-K SCRAPER
# --------------------------------------------------
def get_html(url):
    try:
        return requests.get(url, headers={'User-Agent':'Mozilla/5.0'}).text
    except:
        return ""

def scrape_val(phrase, txt):
    # Finds number after phrase. Handles (123) as negative.
    m = re.search(rf'{phrase}[^>]*>\s*\(?([-\d,]+)\)?', txt, re.I)
    if m:
        try:
            raw = m.group(1).replace(',', '')
            val = float(raw)
            # If original match had parentheses, make it negative
            if '(' in m.group(0) and ')' in m.group(0):
                val = -val
            return val / 1000000 # Convert to Millions (standardizing input unit)
        except:
            return None
    return None

# --------------------------------------------------
#  SIDEBAR: CONFIGURATION
# --------------------------------------------------
with st.sidebar:
    st.header("1. Market Data (Source)")
    ticker = st.text_input("Ticker", "AAPL").upper()
    
    # We ONLY use Yahoo for Price and Shares (Market Data)
    if ticker:
        tk = yf.Ticker(ticker)
        # fast_info is faster and often more reliable for current price than .info
        cur_price = tk.fast_info.last_price
        cur_shares = tk.fast_info.shares / 1e9 # Billions
        
        c1, c2 = st.columns(2)
        c1.metric("Price", f"${cur_price:.2f}")
        c2.metric("Shares (B)", f"{cur_shares:.2f}")
        
        with st.spinner("Calculating Beta from 5y history..."):
            calc_beta = calculate_live_beta(ticker)
        st.caption(f"Calculated 5y Monthly Beta: **{calc_beta:.2f}**")
    else:
        st.stop()

    st.divider()
    
    st.header("2. Financials (10-K)")
    sec_url = st.text_input("Paste SEC 10-K URL", placeholder="https://www.sec.gov/...")
    
    # Initialize variables with 0.0
    s_rev = s_ebit = s_dep = s_capex = s_debt = s_cash = 0.0
    
    if sec_url:
        with st.spinner("Parsing 10-K HTML..."):
            txt = get_html(sec_url)
            # Try to grab values (in Millions)
            # Revenue
            found_rev = scrape_val(r'Revenues?|NetSales|NetRevenues?|TotalRevenues?', txt)
            if found_rev: s_rev = found_rev / 1000 # Convert to Billions for input box
            
            # EBIT
            found_ebit = scrape_val(r'OperatingIncomeLoss|OperatingIncome|EBIT', txt)
            if found_ebit: s_ebit = found_ebit / 1000
            
            # D&A
            found_dep = scrape_val(r'DepreciationDepletionAndAmortization|Depreciation|Amortization', txt)
            if found_dep: s_dep = found_dep / 1000
            
            # Capex
            found_cap = scrape_val(r'CapitalExpenditures|PaymentsToAcquirePropertyPlantAndEquipment', txt)
            if found_cap: s_capex = abs(found_cap) / 1000
            
            # Debt (Long term + Short term)
            found_debt = scrape_val(r'LongTermDebt|NotesPayable', txt)
            if found_debt: s_debt = found_debt / 1000
            
            # Cash
            found_cash = scrape_val(r'CashAndCashEquivalents', txt)
            if found_cash: s_cash = found_cash / 1000

    st.info("Verify 10-K data below (Enter in **Billions**)")
    
    with st.form("financials_form"):
        f1, f2 = st.columns(2)
        rev_in = f1.number_input("Revenue (B)", value=float(s_rev), format="%.3f")
        ebit_in = f2.number_input("EBIT (B)", value=float(s_ebit), format="%.3f")
        
        f3, f4 = st.columns(2)
        dep_in = f3.number_input("D&A (B)", value=float(s_dep), format="%.3f")
        capex_in = f4.number_input("Capex (B)", value=float(s_capex), format="%.3f")
        
        f5, f6 = st.columns(2)
        debt_in = f5.number_input("Total Debt (B)", value=float(s_debt), format="%.3f")
        cash_in = f6.number_input("Cash (B)", value=float(s_cash), format="%.3f")
        
        submitted = st.form_submit_button("Update Model")

    st.divider()
    st.header("3. Assumptions")
    rf_in = st.number_input("Risk Free Rate %", 3.0, 6.0, 4.2, 0.1) / 100
    erp_in = st.number_input("Equity Risk Premium %", 3.0, 8.0, 5.5, 0.1) / 100
    beta_in = st.number_input("Beta (Input)", 0.5, 3.0, float(calc_beta), 0.05)
    
    with st.expander("Growth & Margins"):
        g_rev_in = st.slider("Rev Growth %", 0, 30, 5, 1)/100
        # Calculate margin from inputs for default
        def_margin = (ebit_in/rev_in*100) if rev_in > 0 else 20.0
        margin_in = st.slider("Target EBIT Margin %", 5, 60, int(def_margin), 1)/100
        ltg_in = st.slider("Terminal Growth %", 1, 5, 2, 1)/100
        exit_m_in = st.slider("Exit Multiple", 5, 30, 12, 1)

# --------------------------------------------------
#  CORE CALCULATION ENGINE
# --------------------------------------------------

# 1. WACC Calculation
market_cap = cur_price * cur_shares # Billions
net_debt = debt_in - cash_in
enterprise_val_estimate = market_cap + net_debt

# Weights
if enterprise_val_estimate <= 0: enterprise_val_estimate = market_cap # Safety
w_e = market_cap / enterprise_val_estimate
w_d = net_debt / enterprise_val_estimate if net_debt > 0 else 0

cost_equity = rf_in + beta_in * erp_in
cost_debt = 0.05 # Assumed pre-tax cost of debt (can be made an input)
tax_rate = 0.21

wacc = (w_e * cost_equity) + (w_d * cost_debt * (1 - tax_rate))
if wacc < 0.04: wacc = 0.04 # Floor

# 2. DCF Projection
years = range(1, 6)
proj_data = []

# Derived Ratios from Inputs
capex_percent = capex_in / rev_in if rev_in > 0 else 0.04
da_percent = dep_in / rev_in if rev_in > 0 else 0.03
nwc_percent = 0.02 # Assumption

curr_rev = rev_in

for y in years:
    next_rev = curr_rev * (1 + g_rev_in)
    next_ebit = next_rev * margin_in
    next_tax = next_ebit * tax_rate
    next_nopat = next_ebit - next_tax
    
    next_da = next_rev * da_percent
    next_capex = next_rev * capex_percent
    
    # Change in NWC
    dnwc = (next_rev - curr_rev) * nwc_percent
    
    fcff = next_nopat + next_da - next_capex - dnwc
    
    pv_factor = (1 / (1 + wacc)) ** y
    pv_fcff = fcff * pv_factor
    
    proj_data.append({
        "Year": y,
        "Revenue": next_rev,
        "EBIT": next_ebit,
        "NOPAT": next_nopat,
        "D&A": next_da,
        "Capex": next_capex,
        "FCFF": fcff,
        "PV": pv_fcff
    })
    curr_rev = next_rev

df = pd.DataFrame(proj_data).set_index("Year")
sum_pv_fcf = df["PV"].sum()

# 3. Terminal Value
final_fcf = df.loc[5, "FCFF"]
final_ebitda = df.loc[5, "EBIT"] + df.loc[5, "D&A"]

# Gordon
tv_gordon = final_fcf * (1 + ltg_in) / (wacc - ltg_in)
pv_tv_gordon = tv_gordon * ((1/(1+wacc))**5)

# Exit
tv_exit = final_ebitda * exit_m_in
pv_tv_exit = tv_exit * ((1/(1+wacc))**5)

# 4. Valuation Logic
def get_val(pv_tv):
    ev = sum_pv_fcf + pv_tv
    eq = ev - net_debt # Equity Value
    share_price = eq / cur_shares
    return share_price

target_gordon = get_val(pv_tv_gordon)
target_exit = get_val(pv_tv_exit)
target_avg = (target_gordon + target_exit) / 2

mos = (target_avg - cur_price) / cur_price

# Verdict Logic
if mos >= 0.15:   v_cls, v_txt = "under", "Undervalued"
elif mos <= -0.15: v_cls, v_txt = "over", "Overvalued"
else:              v_cls, v_txt = "fair", "Fairly Valued"

# --------------------------------------------------
#  DISPLAY
# --------------------------------------------------
# Metric Cards
st.markdown('<div class="glass-card">', unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
c1.markdown(f'<div class="metric-tile"><p class="metric-value">${target_avg:,.2f}</p><p class="metric-label">Intrinsic Value</p></div>', unsafe_allow_html=True)
c2.markdown(f'<div class="metric-tile"><p class="metric-value">${cur_price:,.2f}</p><p class="metric-label">Market Price</p></div>', unsafe_allow_html=True)
c3.markdown(f'<div class="metric-tile"><p class="metric-value {v_cls}">{mos:+.1%}</p><p class="metric-label">Margin of Safety</p></div>', unsafe_allow_html=True)
c4.markdown(f'<div class="metric-tile"><p class="metric-value">{wacc:.1%}</p><p class="metric-label">Calculated WACC</p></div>', unsafe_allow_html=True)
c5.markdown(f'<div class="metric-tile"><p class="metric-value">{beta_in:.2f}</p><p class="metric-label">Beta Used</p></div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# Calculation Detail
tab1, tab2 = st.tabs(["📊 Projections & Cash Flow", "🧮 WACC Calculation"])

with tab1:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("Projected Free Cash Flows (Billions)")
    st.dataframe(df.style.format("{:,.2f}"), use_container_width=True)
    
    st.divider()
    
    bc1, bc2 = st.columns(2)
    with bc1:
        st.markdown("##### Gordon Growth Method")
        st.write(f"Terminal Value: **${tv_gordon:,.2f}B**")
        st.write(f"PV of TV: **${pv_tv_gordon:,.2f}B**")
        st.caption(f"Implied Price: **${target_gordon:,.2f}**")
        
    with bc2:
        st.markdown("##### Exit Multiple Method")
        st.write(f"Terminal Value: **${tv_exit:,.2f}B**")
        st.write(f"PV of TV: **${pv_tv_exit:,.2f}B**")
        st.caption(f"Implied Price: **${target_exit:,.2f}**")
    st.markdown('</div>', unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("Cost of Capital Build-Up")
    wc1, wc2 = st.columns(2)
    
    with wc1:
        st.markdown("**Cost of Equity (CAPM)**")
        st.latex(r"K_e = R_f + \beta (R_m - R_f)")
        st.write(f"Risk Free ($R_f$): **{rf_in*100:.1f}%**")
        st.write(f"Equity Premium ($R_m - R_f$): **{erp_in*100:.1f}%**")
        st.write(f"Beta ($\beta$): **{beta_in:.2f}**")
        st.markdown(f"**$K_e$ = {cost_equity:.1%}**")
        
    with wc2:
        st.markdown("**WACC Weights**")
        st.write(f"Market Cap: **${market_cap:,.1f}B** ({w_e:.1%})")
        st.write(f"Net Debt: **${net_debt:,.1f}B** ({w_d:.1%})")
        st.write(f"Tax Rate: **{tax_rate:.0%}**")
        st.markdown(f"**WACC = {wacc:.2%}**")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f'<div class="glass-card"><h3>Verdict: <span class="{v_cls}">{v_txt}</span></h3></div>', unsafe_allow_html=True)
