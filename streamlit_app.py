import streamlit as st, pandas as pd, yfinance as yf, requests, re
st.set_page_config(page_title="DCF Model", layout="wide", initial_sidebar_state="collapsed")

# --------------------------------------------------
#  CSS  –  dark glass-morphic theme
# --------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

body {
  font-family: 'Inter', sans-serif;
  background: linear-gradient(135deg, #1e1e2f 0%, #2a2a3e 100%);
  color: #f0f2f6;
}

.glass-card {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.37);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.metric-tile {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  padding: 16px;
  text-align: center;
  transition: transform 0.2s;
}
.metric-tile:hover {
  transform: translateY(-4px);
}
.metric-value {
  font-size: 28px;
  font-weight: 700;
  margin: 0;
}
.metric-label {
  font-size: 14px;
  opacity: 0.7;
  margin: 0;
}

.under {color:#4ade80;}
.over  {color:#f87171;}
.fair  {color:#fbbf24;}

.stTabs [data-baseweb="tab-list"] {
  background: rgba(255,255,255,0.05);
  border-radius: 12px;
  padding: 4px;
  gap: 4px;
}
.stTabs [data-baseweb="tab"] {
  background: transparent;
  border-radius: 8px;
  color: #fff;
  padding: 8px 16px;
  transition: background 0.2s;
}
.stTabs [aria-selected="true"] {
  background: rgba(255,255,255,0.15);
  font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------
#  header
# --------------------------------------------------
st.markdown('<h1 style="text-align:center;margin-bottom:0;">SEC 10-K ➜ DCF</h1>', unsafe_allow_html=True)
st.markdown('<p style="text-align:center;opacity:0.7;margin-top:-10px;">Dark-mode valuation engine</p>', unsafe_allow_html=True)

# --------------------------------------------------
#  sidebar (collapsible)  –  same sliders
# --------------------------------------------------
with st.sidebar:
    url = st.text_input("SEC 10-K URL:", placeholder="https://www.sec.gov/Archives/edgar/data/...")
    ticker_sym = st.text_input("Yahoo ticker:", "AAPL").upper()

    if url and ticker_sym:
        with st.expander("Projection drivers", expanded=True):
            g_rev  = st.slider("Revenue growth %", 0, 15, 6, 1)/100
            margin = st.slider("EBIT margin %", 5, 35, 20, 1)/100
            capex_r= st.slider("Capex % revenue", 2, 10, 4, 1)/100
            nwc_r  = st.slider("ΔNWC % revenue change", 0, 5, 2, 1)/100
            exit_m = st.slider("EBITDA exit multiple", 6, 18, 10, 1)
            ltg    = st.slider("Long-term growth (Gordon) %", 0, 4, 2, 1)/100

if not (url and ticker_sym):
    st.stop()

# --------------------------------------------------
#  data pull & math (unchanged vs previous file)
# --------------------------------------------------
def get_txt(url):
    return requests.get(url, headers={'User-Agent':'Mozilla'}).text

def grab(phrase, txt, default=0.0):
    m = re.search(rf'{phrase}[^>]*>\s*([-\d,]+)', txt, re.I)
    return int(m.group(1).replace(',',''))/1e6 if m else default

@st.cache_data
def pull_financials(url, ticker):
    txt = get_txt(url)
    rev   = grab(r'Revenues?|NetSales|NetRevenues?|TotalRevenues?', txt)
    ebit  = grab(r'OperatingIncomeLoss|OperatingIncome|EBIT', txt)
    dep   = grab(r'DepreciationDepletionAndAmortization|Depreciation|Amortization', txt)
    capex = grab(r'CapitalExpenditures|PaymentsToAcquirePropertyPlantAndEquipment', txt)
    if rev == 0 or ebit == 0:
        rev   = grab(r'us-gaap:NetSales|us-gaap:Revenues|us-gaap:SalesRevenueNet|SalesRevenueNet', txt)
        gross = grab(r'GrossProfit|GrossMargin', txt)
        op_exp= grab(r'OperatingExpenses|SellingGeneralAndAdministrativeExpense', txt)
        ebit  = gross - op_exp if gross and op_exp else 0
    if dep == 0:   dep   = grab(r'DepreciationExpense|AmortizationOfIntangibles', txt)
    if capex == 0: capex = grab(r'PaymentsForCapital Expenditures|PurchaseOfPpe', txt)
    if rev == 0 or ebit == 0:
        info = yf.Ticker(ticker).get_info()
        rev   = info.get('totalRevenue', 0)/1e9
        ebit  = info.get('operatingIncome', 0)/1e9
        dep   = info.get('depreciation', 0)/1e9
        capex = info.get('capitalExpenditures', 0)/1e9
    return rev, ebit, dep, capex

rev0, ebit0, dep0, capex0 = pull_financials(url, ticker_sym)
info = yf.Ticker(ticker_sym).info

beta = info.get('beta', 1.1); rf = 0.042; mkt = 0.10
re = rf + beta*(mkt-rf); rd = 0.045; tax = 0.21
debt = info.get('totalDebt', 0)/1e9; cash = info.get('totalCash', 0)/1e9
shares = info.get('sharesOutstanding', 1e9)/1e9; net_debt = debt - cash
mcap = info.get('marketCap', 1e12)/1e9; total_v = mcap + net_debt
wacc = (re*(mcap/total_v)) + (rd*(1-tax)*(net_debt/total_v))

years = list(range(1,6)); proj = []; rev_prev = rev0
for y in years:
    rev  = rev_prev*(1+g_rev); ebit = rev*margin; tax_paid = ebit*tax; nopat = ebit - tax_paid
    d_a  = dep0*(1+g_rev)**y; capex= rev*capex_r; dnwc = (rev - rev_prev)*nwc_r
    fcf  = nopat + d_a - capex - dnwc
    proj.append({'Year':y, 'Revenue':rev, 'EBIT':ebit, 'Taxes':tax_paid,
                 'NOPAT':nopat, 'D&A':d_a, 'Capex':capex, 'ΔNWC':dnwc, 'FCFF':fcf})
    rev_prev = rev
df = pd.DataFrame(proj).set_index('Year')
df['Discount Factor'] = [(1/(1+wacc))**y for y in years]
df['PV of FCFF'] = df['FCFF'] * df['Discount Factor']
fcf5 = df.loc[5,'FCFF']; ebitda5 = df.loc[5,'EBIT'] + df.loc[5,'D&A']
tv_gordon = fcf5*(1+ltg)/(wacc-ltg); tv_exit = ebitda5*exit_m
pv_tv_gordon = tv_gordon/(1+wacc)**5; pv_tv_exit = tv_exit/(1+wacc)**5; pv_5y_fcf = df['PV of FCFF'].sum()

ev_gordon = pv_5y_fcf + pv_tv_gordon; ev_exit = pv_5y_fcf + pv_tv_exit; ev_avg = (ev_gordon + ev_exit)/2
price_gordon = (ev_gordon + cash - debt)/shares; price_exit = (ev_exit + cash - debt)/shares; price_avg = (ev_avg + cash - debt)/shares
current = info.get('currentPrice', 0); mos = (price_avg - current)/current

# --------------------------------------------------
#  RESCALE ÷ 1 000  →  4-5 digit display
# --------------------------------------------------
price_gordon_k = price_gordon * 1000; price_exit_k = price_exit * 1000; price_avg_k = price_avg * 1000
current_k = current * 1000; ev_gordon_k = ev_gordon * 1000; ev_exit_k = ev_exit * 1000
pv_5y_fcf_k = pv_5y_fcf * 1000; pv_tv_gordon_k = pv_tv_gordon * 1000; pv_tv_exit_k = pv_tv_exit * 1000
net_debt_k = net_debt * 1000; cash_k = cash * 1000; debt_k = debt * 1000; shares_k = shares * 1000
df_k = df * 1000

# --------------------------------------------------
#  GLASS-MORPHIC METRIC BAR
# --------------------------------------------------
st.markdown('<div class="glass-card">', unsafe_allow_html=True)
cols = st.columns(5)
cols[0].markdown(f'<div class="metric-tile"><p class="metric-value">{price_avg_k:.0f}</p><p class="metric-label">Fair price</p></div>', unsafe_allow_html=True)
cols[1].markdown(f'<div class="metric-tile"><p class="metric-value">{current_k:.0f}</p><p class="metric-label">Current price</p></div>', unsafe_allow_html=True)
cols[2].markdown(f'<div class="metric-tile"><p class="metric-value {verdict[2:5]}">{mos:+.1%}</p><p class="metric-label">MoS</p></div>', unsafe_allow_html=True)
cols[3].markdown(f'<div class="metric-tile"><p class="metric-value">{wacc:.1%}</p><p class="metric-label">WACC</p></div>', unsafe_allow_html=True)
cols[4].markdown(f'<div class="metric-tile"><p class="metric-value">{beta:.2f}</p><p class="metric-label">Beta</p></div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# --------------------------------------------------
#  TABS WITH TABLES
# --------------------------------------------------
tab1, tab2 = st.tabs(["📈 Gordon Growth", "📊 EBITDA Exit"])

def bridge_table(ev_tv_k):
    eq_k = ev_tv_k + cash_k - debt_k; price_k = eq_k / shares_k
    br = pd.DataFrame({'Component':['PV of 5-yr FCFF','PV of Terminal Value','Enterprise Value','Less: Net Debt','Equity Value','÷ Shares Outstanding'],
                       'Value':[pv_5y_fcf_k, ev_tv_k - pv_5y_fcf_k, ev_tv_k, net_debt_k, eq_k, shares_k],
                       'Per-Share':[None,None,None,None,None,price_k]})
    return br.style.format({"Value":"{:,.0f}","Per-Share":"{:,.0f}"})

def cashflow_table():
    return df_k[['Revenue','EBIT','Taxes','NOPAT','D&A','Capex','ΔNWC','FCFF','Discount Factor','PV of FCFF']].T.style.format("{:,.0f}")

with tab1:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.header("Perpetuity Growth Valuation")
    c1, c2 = st.columns(2)
    c1.metric("Implied share price", f"{price_gordon_k:.0f}")
    c1.metric("Enterprise Value", f"{ev_gordon_k:,.0f}")
    st.subheader("Projected Free Cash Flow")
    st.dataframe(cashflow_table(), use_container_width=True)
    st.subheader("Valuation Bridge (Gordon)")
    st.dataframe(bridge_table(ev_gordon_k), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.header("EBITDA Exit Multiple Valuation")
    c1, c2 = st.columns(2)
    c1.metric("Implied share price", f"{price_exit_k:.0f}")
    c1.metric("Enterprise Value", f"{ev_exit_k:,.0f}")
    st.subheader("Projected Free Cash Flow")
    st.dataframe(cashflow_table(), use_container_width=True)
    st.subheader("Valuation Bridge (EBITDA Exit)")
    st.dataframe(bridge_table(ev_exit_k), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --------------------------------------------------
#  FOOTER VERDICT
# --------------------------------------------------
st.markdown(f'<div class="glass-card"><h3>Verdict: <span class="{verdict[2:5]}">{verdict}</span></h3></div>', unsafe_allow_html=True)
