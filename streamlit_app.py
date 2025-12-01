import streamlit as st
import pandas as pd
import yfinance as yf
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# ==========================================
# 1. CONFIGURATION & STYLING
# ==========================================
st.set_page_config(page_title="DCF Valuation Tool", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
body { font-family: 'Inter', sans-serif; background: linear-gradient(135deg, #1e1e2f 0%, #2a2a3e 100%); color: #f0f2f6; }

/* Cards */
.glass-card { background: rgba(255,255,255,0.05); border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; }
.val-card { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 24px; border: 1px solid rgba(255,255,255,0.08); height: 100%; transition: transform 0.2s; }
.val-card:hover { transform: translateY(-3px); }

/* Typography */
.val-label { font-size: 11px; font-weight: 700; opacity: 0.5; letter-spacing: 1px; text-transform: uppercase; }
.val-price { font-size: 42px; font-weight: 700; margin: 4px 0 16px 0; color: #fff; }
.val-title { font-size: 18px; font-weight: 600; margin-bottom: 4px; color: #fff; }
.val-sub { font-size: 12px; opacity: 0.6; margin-bottom: 20px; }
.status-under { color: #4ade80; font-weight: 700; }
.status-over { color: #f87171; font-weight: 700; }
.text-blue { color: #60a5fa; }
.text-purple { color: #a78bfa; }
.text-green { color: #34d399; }
.border-purple { border-left: 5px solid #8b5cf6; }
.border-green { border-left: 5px solid #10b981; }

/* Overrides */
div[data-testid="stExpander"] { background-color: rgba(255,255,255,0.02); border-radius: 12px; }
div[data-testid="stButton"] button { min-width: 100px !important; }
th { text-align: center !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="text-align:center; margin-bottom: 30px;">DCF Valuation Tool</h1>', unsafe_allow_html=True)

# ==========================================
# 2. PDF GENERATION ENGINE
# ==========================================
def create_pdf(ticker, date, price, int_val, upside, wacc, ltg, exit_m, c_curr):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Header
    c.setFont("Helvetica-Bold", 24)
    c.drawString(50, height - 50, f"Valuation Report: {ticker}")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 80, f"Date: {date}")
    c.line(50, height - 100, width - 50, height - 100)

    # Results
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 140, "Valuation Results")
    c.setFont("Helvetica", 14)
    c.drawString(50, height - 170, f"Current Price: {c_curr}{price:,.2f}")
    c.drawString(50, height - 190, f"Intrinsic Value: {c_curr}{int_val:,.2f}")
    
    status = "UNDERVALUED" if upside >= 0 else "OVERVALUED"
    c.drawString(50, height - 210, f"Upside: {upside:+.1%} ({status})")

    # Assumptions
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 260, "Key Assumptions")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 290, f"WACC: {wacc:.1%}")
    c.drawString(50, height - 310, f"Terminal Growth: {ltg:.1%}")
    c.drawString(50, height - 330, f"Exit Multiple: {exit_m}x")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def fmt_comma(val):
    """Formats number to string with commas, NO decimals: 130497 -> '130,497'"""
    if pd.isna(val): return "0"
    return f"{val:,.0f}"

def clean_currency(val, symbol="$"):
    """Cleans string to float: '130,497' -> 130497.0"""
    if isinstance(val, (int, float)): return float(val)
    if pd.isna(val) or val == "": return 0.0
    clean = str(val).replace(',', '').replace(symbol, '').replace('€', '').replace('£', '').replace('¥', '').strip()
    try: return float(clean)
    except: return 0.0

# ==========================================
# 4. DATA ENGINE (MILLIONS 1e6)
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_yahoo_data(ticker):
    try:
        tk = yf.Ticker(ticker)
        
        try: info = tk.info
        except: info = {}
        if info is None: info = {}

        # 1. Market Data
        try: price = tk.fast_info.last_price
        except: 
            hist = tk.history(period="1d")
            price = hist['Close'].iloc[-1] if not hist.empty else 0.0

        shares = info.get('sharesOutstanding')
        if not shares: 
            try: shares = tk.fast_info.shares_outstanding
            except: pass
        if not shares: shares = 1e9
        shares = shares / 1e6 # Millions

        industry = info.get('industry', 'Unknown')
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
                fx_msg = f"⚠️ FX Error: Could not fetch rate for {pair}."

        # 3. Financial Statements
        inc = tk.income_stmt
        bs = tk.balance_sheet
        cf = tk.cashflow
        
        if inc.empty: raise ValueError("No financial statements found.")

        def get_val(df, keys):
            if df.empty: return 0.0
            for k in keys:
                if k in df.index: return df.loc[k].iloc[0]
            return 0.0

        data = {}
        factor = fx_rate / 1e6 # Millions
        
        data['Revenue'] = get_val(inc, ['Total Revenue', 'Total Net Sales']) * factor
        data['EBIT']    = get_val(inc, ['Operating Income', 'EBIT']) * factor
        data['Depreciation'] = get_val(cf, ['Depreciation And Amortization']) * factor
        if data['Depreciation'] == 0:
             data['Depreciation'] = get_val(inc, ['Reconciled Depreciation']) * factor
        data['Capex'] = abs(get_val(cf, ['Capital Expenditure', 'Capital Expenditures'])) * factor
        data['Debt'] = get_val(bs, ['Total Debt', 'Long Term Debt']) * factor
        data['Cash'] = get_val(bs, ['Cash And Cash Equivalents']) * factor
        
        return data, price, shares, fx_msg, price_curr, industry
        
    except Exception as e:
        return None, 0.0, 1.0, str(e), "USD", "Unknown"

# ==========================================
# 5. UI: INPUTS & SETUP
# ==========================================
c_tick, c_space, c_pdf = st.columns([1, 4, 1], vertical_alignment="bottom")

with c_tick:
    ticker = st.text_input("Ticker", "NVDA").upper()

pdf_spot = c_pdf.empty()

if 'y0' not in st.session_state:
    st.session_state.y0 = {k:0.0 for k in ['Revenue','EBIT','Depreciation','Capex','Debt','Cash']}

if 'reset_key' not in st.session_state:
    st.session_state.reset_key = 0

curr_symbol = "$"
industry_name = "Unknown"

if ticker:
    with st.spinner(f"Analysing {ticker}..."):
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
                st.session_state.reset_key += 1
            else:
                st.error(f"Error: {fx_msg}")
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

# YEAR 0 FORM (TEXT INPUTS -> NO DECIMALS)
st.markdown("### Year 0: Base Financials (Millions)")
with st.expander("Expand to edit Year 0 Data", expanded=True):
    with st.form("y0_form"):
        c1, c2, c3, c4 = st.columns(4)
        r_in_str = c1.text_input("Revenue", value=fmt_comma(st.session_state.y0['Revenue']))
        e_in_str = c2.text_input("EBIT", value=fmt_comma(st.session_state.y0['EBIT']))
        d_in_str = c3.text_input("D&A", value=fmt_comma(st.session_state.y0['Depreciation']))
        c_in_str = c4.text_input("Capex", value=fmt_comma(st.session_state.y0['Capex']))
        
        c5, c6, c7 = st.columns(3)
        debt_in_str = c5.text_input("Total Debt", value=fmt_comma(st.session_state.y0['Debt']))
        cash_in_str = c6.text_input("Total Cash", value=fmt_comma(st.session_state.y0['Cash']))
        shares_in_str = c7.text_input("Shares (Millions)", value=fmt_comma(shares_def))
        
        r_in = clean_currency(r_in_str, curr_symbol)
        e_in = clean_currency(e_in_str, curr_symbol)
        d_in = clean_currency(d_in_str, curr_symbol)
        c_in = clean_currency(c_in_str, curr_symbol)
        debt_in = clean_currency(debt_in_str, curr_symbol)
        cash_in = clean_currency(cash_in_str, curr_symbol)
        shares_in = clean_currency(shares_in_str, curr_symbol)
        if shares_in == 0: shares_in = 1.0
        
        st.form_submit_button("Update Model")

# ==========================================
# 6. SCENARIO & DRIVERS (SIDEBAR)
# ==========================================
with st.sidebar:
    st.header("Configuration")
    scenario = st.selectbox("Scenario Mode", ["Base Case", "Bull Case 🚀", "Bear Case 🐻"])
    
    if "Bull" in scenario:
        mult_g, mult_m, mult_e = 1.2, 1.1, 1.15
        st.success("Growth +20%, Margin +10%")
    elif "Bear" in scenario:
        mult_g, mult_m, mult_e = 0.7, 0.8, 0.8
        st.warning("Growth -30%, Margin -20%")
    else:
        mult_g, mult_m, mult_e = 1.0, 1.0, 1.0

    st.divider()
    st.header("Assumptions")
    wacc = st.number_input("WACC %", value=9.0, step=0.1, format="%.1f", key=f"w_{ticker}") / 100
    
    st.divider()
    st.subheader("Drivers")
    st.caption(f"Detected Industry: {industry_name}")
    
    current_margin = (e_in / r_in) if r_in > 0 else 0.0
    if current_margin > 0.30: def_growth, def_mult = 15.0, 25.0
    elif current_margin < 0.10: def_growth, def_mult = 3.0, 8.0
    else: def_growth, def_mult = 5.0, 12.0
    
    g_rev = st.number_input("Revenue Growth %", value=def_growth * mult_g, step=0.5, format="%.1f", key=f"g_{ticker}") / 100
    m_def = (current_margin * 100)
    margin_tgt = st.
