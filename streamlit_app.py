import streamlit as st, pandas as pd, yfinance as yf, requests, re
st.set_page_config(page_title="Quick DCF", layout="centered")
st.title("SEC 10-K → DCF in 5 s")

def get_txt(url):
    return requests.get(url, headers={'User-Agent':'Mozilla'}).text

def line(tag, txt):
    m = re.search(rf'{tag}[^>]*>\s*([-\d,]+)', txt)
    return int(m.group(1).replace(',',''))/1e6 if m else 0

url = st.text_input("Paste SEC 10-K URL:", placeholder="https://www.sec.gov/Archives/edgar/data/...")
if url:
    txt = get_txt(url)
    rev   = line(r'Revenues?', txt)
    ebitda= line(r'EBITDA|OperatingIncomeLoss', txt)
    capex = line(r'CapitalExpenditures', txt)
    fcf   = ebitda - 0.21*ebitda - capex
    # SAFE ticker extract
    ticker_match = re.search(r'entityName[^<]+<[^>]+>([^<]+)', txt)
    ticker = ticker_match.group(1)[:4].upper() if ticker_match else "STCK"
    st.success(f"Loaded {ticker}: Rev ${rev:,.0f}M, EBITDA ${ebitda:,.0f}M")
    g = st.slider("Growth %", 0, 15, 5)/100
    m = st.slider("Terminal EBITDA multiple", 6, 18, 10)
    d = st.slider("Discount %", 6, 12, 9)/100
    proj = [fcf*(1+g)**y for y in range(1,6)]
    tv = ebitda*(1+g)**5 * m
    ev = sum(p/(1+d)**y for y,p in enumerate(proj,1)) + tv/(1+d)**5
    info = yf.Ticker(ticker).info
    cash, debt, shares = info.get('totalCash',0)/1e9, info.get('totalDebt',0)/1e9, info.get('sharesOutstanding',1e9)/1e9
    eq = ev/1e9 + cash - debt
    fair = eq/shares
    price = info.get('currentPrice', 150)
    mos = (fair-price)/price
    col1, col2 = st.columns(2)
    col1.metric("EV", f"${ev/1e9:.1f}B"); col1.metric("+Cash", f"${cash:.1f}B"); col1.metric("-Debt", f"${debt:.1f}B"); col1.metric("=Equity", f"${eq:.1f}B"); col1.metric("Fair", f"${fair:.1f}")
    col2.metric("Price", f"${price:.1f}"); col2.metric("MoS", f"{mos:.1%}", delta=f"{mos:.1%}", delta_color="inverse"); col2.write("🔴 Over" if mos<-0.1 else "🟢 Under" if mos>0.25 else "🟡 Fair")
