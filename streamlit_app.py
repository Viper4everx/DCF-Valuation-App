import streamlit as st, pandas as pd, yfinance as yf, requests, re
st.set_page_config(page_title="DCF Model", layout="wide")

st.title("SEC 10-K ➜ Full DCF")

# ---------- helpers ----------
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

with st.sidebar:
    url = st.text_input("SEC 10-K URL:", placeholder="https://www.sec.gov/Archives/edgar/data/...")
    ticker_sym = st.text_input("Yahoo ticker:", "AAPL").upper()
if not (url and ticker_sym):
    st.stop()

rev0, ebit0, dep0, capex0 = pull_financials(url, ticker_sym)
info = yf.Ticker(ticker_sym).info
beta = info.get('beta', 1.1); rf = 0.042; mkt = 0.10
re = rf + beta*(mkt-rf); rd = 0.045; tax = 0.21
debt = info.get('totalDebt', 0)/1e9; cash = info.get('totalCash', 0)/1e9
shares = info.get('sharesOutstanding', 1e9)/1e9; net_debt = debt - cash
mcap = info.get('marketCap', 1e12)/1e9; total_v = mcap + net_debt
wacc = (re*(mcap/total_v)) + (rd*(1-tax)*(net_debt/total_v))

with st.sidebar.expander("Drivers", expanded=True):
    g_rev  = st.slider("Revenue growth %", 0, 15, 6)/100
    margin = st.slider("EBIT margin %", 5, 35, 20)/100
    capex_r= st.slider("Capex % revenue", 2, 10, 4)/100
    nwc_r  = st.slider("ΔNWC % revenue change", 0, 5, 2)/100
    exit_m = st.slider("EBITDA exit multiple", 6, 18, 10)
    ltg    = st.slider("Long-term growth (Gordon) %", 0, 4, 2)/100

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

# ---------- top line ----------
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Fair price", f"{price_avg:.0f}")
col2.metric("Current price", f"{current:.0f}")
col3.metric("MoS", f"{mos:+.1%}")
col4.metric("WACC", f"{wacc:.1%}")
col5.metric("Beta", f"{beta:.2f}")

tab1, tab2 = st.tabs(["📈 Gordon Growth", "📊 EBITDA Exit"])

def bridge_table(ev_tv):
    eq = ev_tv + cash - debt; price = eq/shares
    br = pd.DataFrame({'Component':['PV of 5-yr FCFF', 'PV of Terminal Value', 'Enterprise Value', 'Less: Net Debt', 'Equity Value', '÷ Shares Outstanding'],
                       'Value':[pv_5y_fcf, ev_tv - pv_5y_fcf, ev_tv, net_debt, eq, shares],
                       'Per-Share':[None, None, None, None, None, price]})
    return br.style.format({"Value":"{:,.0f}", "Per-Share":"{:,.0f}"})

def cashflow_table():
    return df[['Revenue','EBIT','Taxes','NOPAT','D&A','Capex','ΔNWC','FCFF','Discount Factor','PV of FCFF']].T.style.format("{:,.0f}")

with tab1:
    st.header("Perpetuity Growth Valuation")
    c1, c2 = st.columns(2)
    c1.metric("Implied share price", f"{price_gordon:.0f}")
    c1.metric("Enterprise Value", f"{ev_gordon:.0f}")
    st.subheader("Projected Free Cash Flow")
    st.dataframe(cashflow_table())
    st.subheader("Valuation Bridge (Gordon)")
    st.dataframe(bridge_table(ev_gordon))

with tab2:
    st.header("EBITDA Exit Multiple Valuation")
    c1, c2 = st.columns(2)
    c1.metric("Implied share price", f"{price_exit:.0f}")
    c1.metric("Enterprise Value", f"{ev_exit:.0f}")
    st.subheader("Projected Free Cash Flow")
    st.dataframe(cashflow_table())
    st.subheader("Valuation Bridge (EBITDA Exit)")
    st.dataframe(bridge_table(ev_exit))

verdict = "🔴 Over-valued" if mos < -0.10 else "🟢 Under-valued" if mos > 0.25 else "🟡 Fair-valued"
st.markdown(f"**Current market price:** {current:.0f}  **Margin of safety:** {mos:+.1%}  {verdict}")
