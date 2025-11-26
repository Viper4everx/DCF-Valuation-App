import streamlit as st, pandas as pd, yfinance as yf, requests, re, math
st.set_page_config(page_title="DCF Model", layout="wide")
st.title("SEC 10-K ➜ Full DCF Output")

# ---------- helpers ----------
def get_txt(url):
    return requests.get(url, headers={'User-Agent':'Mozilla'}).text

def line(tag, txt):
    m = re.search(rf'{tag}[^>]*>\s*([-\d,]+)', txt)
    return int(m.group(1).replace(',',''))/1e6 if m else 0.0

@st.cache_data
def pull_financials(url):
    txt = get_txt(url)
    rev   = line(r'Revenues?', txt)
    ebit  = line(r'OperatingIncomeLoss|EBIT', txt)
    dep   = line(r'Depreciation|DepreciationDepletionAndAmortization', txt)
    capex = line(r'CapitalExpenditures', txt)
    return rev, ebit, dep, capex

# ---------- sidebar inputs ----------
with st.sidebar:
    url = st.text_input("SEC 10-K URL:", placeholder="https://www.sec.gov/Archives/edgar/data/...")
    ticker_sym = st.text_input("Yahoo ticker:", "AAPL").upper()

if not (url and ticker_sym):
    st.stop()

rev0, ebit0, dep0, capex0 = pull_financials(url)
info = yf.Ticker(ticker_sym).info

# ---------- market / WACC ----------
beta = info.get('beta', 1.1)
rf   = 0.042
mkt  = 0.10
re   = rf + beta*(mkt-rf)
rd   = 0.045
tax  = 0.21
debt = info.get('totalDebt', 0)/1e9
cash = info.get('totalCash', 0)/1e9
shares = info.get('sharesOutstanding', 1e9)/1e9
net_debt = debt - cash
mcap = info.get('marketCap', 1e12)/1e9
total_v = mcap + net_debt
wacc = (re*(mcap/total_v)) + (rd*(1-tax)*(net_debt/total_v))

# ---------- projection drivers ----------
st.sidebar.subheader("Drivers")
g_rev  = st.sidebar.slider("Revenue growth %", 0, 15, 6)/100
margin = st.sidebar.slider("EBIT margin %", 5, 35, 20)/100
capex_r= st.sidebar.slider("Capex % revenue", 2, 10, 4)/100
nwc_r  = st.sidebar.slider("ΔNWC % revenue change", 0, 5, 2)/100
exit_m = st.sidebar.slider("EBITDA exit multiple", 6, 18, 10)
ltg    = st.sidebar.slider("Long-term growth (Gordon) %", 0, 4, 2)/100

# ---------- build 5-yr forecast ----------
years = list(range(1,6))
proj = []
rev_prev = rev0
for y in years:
    rev  = rev_prev*(1+g_rev)
    ebit = rev*margin
    tax_paid = ebit*tax
    nopat = ebit - tax_paid
    d_a  = dep0*(1+g_rev)**y   # inflate D&A
    capex= rev*capex_r
    dnwc = (rev - rev_prev)*nwc_r
    fcf  = nopat + d_a - capex - dnwc
    proj.append({'Year':y, 'Revenue':rev, 'EBIT':ebit, 'Taxes':tax_paid,
                 'NOPAT':nopat, 'D&A':d_a, 'Capex':capex, 'ΔNWC':dnwc, 'FCFF':fcf})
    rev_prev = rev
df = pd.DataFrame(proj).set_index('Year')

# ---------- discount factors ----------
df['Discount Factor'] = [(1/(1+wacc))**y for y in years]
df['PV of FCFF'] = df['FCFF'] * df['Discount Factor']

# ---------- terminal values ----------
fcf5 = df.loc[5,'FCFF']
ebitda5 = df.loc[5,'EBIT'] + df.loc[5,'D&A']
tv_gordon = fcf5*(1+ltg)/(wacc-ltg)
tv_exit   = ebitda5*exit_m
pv_tv_gordon = tv_gordon/(1+wacc)**5
pv_tv_exit   = tv_exit/(1+wacc)**5
pv_5y_fcf = df['PV of FCFF'].sum()

# ---------- pages ----------
page = st.radio("View", ["Gordon Growth", "EBITDA Exit"], horizontal=True)

if page=="Gordon Growth":
    ev = pv_5y_fcf + pv_tv_gordon
    implied_price = (ev + cash - debt)/shares
    st.header("Perpetuity Growth Valuation")
    c1,c2=st.columns(2)
    c1.metric("Implied Share Price", f"${implied_price:.2f}")
    c1.metric("Enterprise Value", f"${ev:,.0f}M")
    st.subheader("Projected Free Cash Flow ($ M)")
    show = df[['Revenue','EBIT','Taxes','NOPAT','D&A','Capex','ΔNWC','FCFF','Discount Factor','PV of FCFF']]
    st.dataframe(show.T.style.format("{:,.1f}").set_properties(**{'text-align':'right'}))
    st.subheader("Valuation Bridge (Gordon)")
    bridge = pd.DataFrame({'Component':['PV of 5-yr FCFF','PV of Terminal Value','Enterprise Value','Less: Net Debt','Equity Value','÷ Shares Outstanding'],
                           '$ M':[pv_5y_fcf, pv_tv_gordon, ev, net_debt, ev-net_debt, shares],
                           'Per-Share':[None,None,None,None,None,implied_price]})
    st.dataframe(bridge.style.format({"$ M":"{:,.0f}","Per-Share":"${:.2f}"}))

else:  # EBITDA EXIT
    ev = pv_5y_fcf + pv_tv_exit
    implied_price = (ev + cash - debt)/shares
    st.header("EBITDA Exit Multiple Valuation")
    c1,c2=st.columns(2)
    c1.metric("Implied Share Price", f"${implied_price:.2f}")
    c1.metric("Enterprise Value", f"${ev:,.0f}M")
    st.subheader("Projected Free Cash Flow ($ M)")
    show = df[['Revenue','EBIT','Taxes','NOPAT','D&A','Capex','ΔNWC','FCFF','Discount Factor','PV of FCFF']]
    st.dataframe(show.T.style.format("{:,.1f}").set_properties(**{'text-align':'right'}))
    st.subheader("Valuation Bridge (EBITDA Exit)")
    bridge = pd.DataFrame({'Component':['PV of 5-yr FCFF','PV of Terminal Value','Enterprise Value','Less: Net Debt','Equity Value','÷ Shares Outstanding'],
                           '$ M':[pv_5y_fcf, pv_tv_exit, ev, net_debt, ev-net_debt, shares],
                           'Per-Share':[None,None,None,None,None,implied_price]})
    st.dataframe(bridge.style.format({"$ M":"{:,.0f}","Per-Share":"${:.2f}"}))

# ---------- current price comparison ----------
current = info.get('currentPrice', 0)
mos = (implied_price - current)/current
verdict = "🔴 Over-valued" if mos < -0.10 else "🟢 Under-valued" if mos > 0.25 else "🟡 Fair-valued"
st.divider()
st.markdown(f"**Current market price:** ${current:.2f}  **Margin of safety:** {mos:+.1%}  {verdict}")
