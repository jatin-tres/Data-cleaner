import streamlit as st
import pandas as pd
import numpy as np
import io
import sys
import datetime

# --- CHECK FOR ALTAIR ---
try:
    import altair as alt
except ImportError:
    st.error("Missing dependency: The 'altair' library is required for charting.")
    st.error("Please run: pip install altair")
    sys.exit()

# --- Configuration ---
st.set_page_config(
    layout="wide", 
    page_title="Professional Ledger Analyzer 📊", 
    initial_sidebar_state="expanded" 
)

# --- Helper Function to Load Data ---
@st.cache_data
def load_data(uploaded_file):
    """Loads CSV data into a DataFrame and performs initial cleaning."""
    try:
        df = pd.read_csv(uploaded_file)
        
        # Standardize column names
        df.columns = df.columns.str.strip()
        
        # --- Data Cleaning and Type Conversion ---
        numeric_cols = [
            'Transfer Unit Fiat Price ($)', 
            'Balance Impact (T)', 
            'Total Fiat Amount ($)',
        ]
        
        for col in numeric_cols:
            if col in df.columns:
                cleaned_data = df[col].astype(str).str.replace(r'[$,]', '', regex=True)
                df[col] = pd.to_numeric(cleaned_data, errors='coerce')
        
        if 'Balance Impact (T)' in df.columns:
            df['Balance Impact (T)'] = df['Balance Impact (T)'].fillna(0).astype(np.float64)

        if 'Original Currency Symbol' in df.columns:
            df['Original Currency Symbol'] = df['Original Currency Symbol'].fillna('UNKNOWN')

        # Add Transaction Type column
        if 'Direction' in df.columns and 'Event Label' in df.columns:
            def categorize_transaction(row):
                if row['Direction'] == 'inflow':
                    return 'inflow'
                elif row['Direction'] == 'outflow':
                    if any(fee_keyword in str(row['Event Label']).lower() for fee_keyword in ['fee', 'gas', 'transaction cost']):
                        return 'fees'
                    else:
                        return 'outflow'
                else:
                    return 'other'
            
            df['Transaction Type'] = df.apply(categorize_transaction, axis=1)
            
        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')

        return df
    except Exception as e:
        st.error(f"Error loading or processing file: {e}")
        return pd.DataFrame() 


# -------------------------------------------------------------------------
# --- Streamlit App Layout ---
# -------------------------------------------------------------------------

st.title("📊 Transaction Ledger Analysis Dashboard")
st.markdown("Navigate through the tabs below to view different reports generated from your ledger data.")

with st.sidebar:
    st.header("⬆️ Upload Transaction Data")
    st.info("⚠️ **Please upload your CSV file here** to begin generating reports.")
    uploaded_file = st.file_uploader("**Choose a CSV file**", type=['csv'])
    st.markdown("---")

if uploaded_file is None:
    st.info("Please upload a CSV file in the sidebar to begin generating reports.")
    st.stop()

df = load_data(uploaded_file)

if df.empty:
    st.stop() 

# =========================================================================
# --- CORE DATA PROCESSING (Running Balance Calculation) ---
# =========================================================================

if 'Timestamp' in df.columns and 'Balance Impact (T)' in df.columns:
    df = df.sort_values(by='Timestamp', ascending=True).reset_index(drop=True)
    df['Running Balance (T)'] = df.groupby('Original Currency Symbol')['Balance Impact (T)'].cumsum()
    df['Balance Status'] = df['Running Balance (T)'].apply(lambda x: "⚠️ NEGATIVE BALANCE" if x < 0 else "OK")
else:
    st.error("Cannot calculate Running Balance. Missing 'Timestamp' or 'Balance Impact (T)' column.")


# --- Main Report Tabs ---
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔍 Data Overview", 
    "💸 Report 1: Currency Filter", 
    "⚖️ Report 2: Net Flow & Fees", 
    "💰 Report 3: Running Balance",
    "📈 Suggested Analytics",
    "📅 Report: Date-Specific Flow" 
])

# =========================================================================
# Tab 1: Data Overview
# =========================================================================
with tab1:
    st.header("Dataset Summary")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Transactions", f"{len(df):,}")
    if 'Timestamp' in df.columns and not df['Timestamp'].empty:
        with col2:
            st.metric("Start Date", df['Timestamp'].min().strftime('%Y-%m-%d'))
        with col3:
            st.metric("End Date", df['Timestamp'].max().strftime('%Y-%m-%d'))
    else:
         with col2: st.metric("Start Date", "N/A")
         with col3: st.metric("End Date", "N/A")

    st.subheader("All Loaded Column Headers")
    st.code(list(df.columns))
    st.markdown("---")
    st.subheader("First 5 Rows of Data")
    st.dataframe(df.head(), use_container_width=True)

# =========================================================================
# Tab 2: Report 1: Transactions by 'Original Currency Symbol'
# =========================================================================
with tab2:
    st.header("Report 1: Filtered Transactions by Currency Symbol")
    currency_options = df['Original Currency Symbol'].unique()
    selected_currency = st.selectbox("**Select an 'Original Currency Symbol' to filter:**", options=currency_options, index=0, key='currency_filter')
    
    if selected_currency:
        filtered_df = df[df['Original Currency Symbol'] == selected_currency].copy()
        st.subheader(f"All {len(filtered_df):,} transactions for: $\\text{{{selected_currency}}}$")
        st.dataframe(filtered_df, use_container_width=True)
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(label=f"⬇️ Download {selected_currency} Transactions CSV", data=csv, file_name=f'Report_1_{selected_currency}.csv', mime='text/csv')

# =========================================================================
# Tab 3: Report 2: Net Flow & Fees
# =========================================================================
with tab3:
    st.header("Report 2: Net Flow & Fees by Token (Pivot Table)")
    if 'Transaction Type' in df.columns and 'Balance Impact (T)' in df.columns:
        pivot_table = df.pivot
