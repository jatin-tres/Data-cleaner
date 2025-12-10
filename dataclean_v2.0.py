import streamlit as st
import pandas as pd
import numpy as np
import io
import sys

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
    # Ensures the sidebar with the uploader is open on start
    initial_sidebar_state="expanded" 
)

# --- Helper Function to Load Data ---
@st.cache_data
def load_data(uploaded_file):
    """Loads CSV data into a DataFrame and performs initial cleaning."""
    try:
        df = pd.read_csv(uploaded_file)
        
        # Standardize column names by stripping whitespace
        df.columns = df.columns.str.strip()
        
        # --- Data Cleaning and Type Conversion ---
        numeric_cols = [
            'Transfer Unit Fiat Price ($)', 
            'Balance Impact (T)', 
            'Total Fiat Amount ($)',
        ]
        
        for col in numeric_cols:
            if col in df.columns:
                # 1. Clean up currency formatting
                cleaned_data = df[col].astype(str).str.replace(r'[$,]', '', regex=True)
                
                # 2. Force conversion to float, coercing errors to NaN
                df[col] = pd.to_numeric(cleaned_data, errors='coerce')
        
        # --- CRITICAL FIX FOR RUNNING BALANCE (Report 3) ---
        if 'Balance Impact (T)' in df.columns:
            # Explicitly fill NaN with 0 and convert to float64 to ensure cumsum works
            df['Balance Impact (T)'] = df['Balance Impact (T)'].fillna(0).astype(np.float64)

        # Fill NaN in 'Original Currency Symbol'
        if 'Original Currency Symbol' in df.columns:
            df['Original Currency Symbol'] = df['Original Currency Symbol'].fillna('UNKNOWN')
            
        # Ensure Transaction Hash is treated as a clean string for grouping
        if 'Transaction Hash' in df.columns:
             df['Transaction Hash'] = df['Transaction Hash'].astype(str).str.strip().fillna('')


        # Add a Transaction Type column for the pivot table logic (Report 2)
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
            
        # Ensure Timestamp is datetime for sorting and plotting
        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')

        return df
    except Exception as e:
        st.error(f"Error loading or processing file: {e}")
        st.error("Please check that your column headers (like 'Balance Impact (T)', 'Total Fiat Amount ($)', etc.) match exactly.")
        return pd.DataFrame() 


# -------------------------------------------------------------------------
# --- Streamlit App Layout ---
# -------------------------------------------------------------------------

st.title("📊 Transaction Ledger Analysis Dashboard")
st.markdown("Navigate through the tabs below to view different reports generated from your ledger data.")

# --- Sidebar for File Upload and Global Filter ---
with st.sidebar:
    st.header("⬆️ Upload Transaction Data")
    st.info("⚠️ **Please upload your CSV file here** to begin generating reports.")
    uploaded_file = st.file_uploader(
        "**Choose a CSV file**", 
        type=['csv']
    )
    st.markdown("---")


if uploaded_file is None:
    st.info("Please upload a CSV file in the sidebar to begin generating reports.")
    st.stop()

df = load_data(uploaded_file)

if df.empty:
    st.stop() 

# =========================================================================
# --- CORE DATA PROCESSING (Running Balance and Grouping Calculations) ---
# =========================================================================

# Check both key columns for Running Balance
if 'Timestamp' in df.columns and 'Balance Impact (T)' in df.columns:
    # 1. Sort by Timestamp (ascending A to Z) as requested
    df = df.sort_values(by='Timestamp', ascending=True).reset_index(drop=True)

    # 2. Calculate Running Balance for each Token
    df['Running Balance (T)'] = df.groupby('Original Currency Symbol')['Balance Impact (T)'].cumsum()

    # 3. Create Status Column for Negative Balances
    df['Balance Status'] = df['Running Balance (T)'].apply(
        lambda x: "⚠️ NEGATIVE BALANCE" if x < 0 else "OK"
    )

else:
    st.error("Cannot calculate Running Balance. Missing 'Timestamp' or 'Balance Impact (T)' column. Check Tab 1 for loaded column names.")


# --- TRANSACTION GROUPING LOGIC (NEW FEATURE) ---
if 'Transaction Hash' in df.columns:
    try:
        # 1. Calculate the count of each transaction hash
        hash_counts = df['Transaction Hash'].value_counts()
        
        # 2. Identify hashes that are part of a group (count > 1)
        group_hashes = hash_counts[hash_counts > 1].index
        
        # 3. Create a mapping for Group IDs (assign 1, 2, 3... to multi-part hashes)
        group_id_map = {hash_val: i + 1 for i, hash_val in enumerate(group_hashes)}
        
        # 4. Initialize new columns
        df['Group Comment'] = "NOT a group transaction"
    
        # 5. Apply the Group ID mapping (this will assign NaNs to non-group hashes)
        df['Group ID'] = df['Transaction Hash'].map(group_id_map)
        
        # 6. Apply the Group Comment
        df.loc[df['Group ID'].notna(), 'Group Comment'] = "Group Transaction"
        
        # 7. Final Safe Type Casting (The definitive fix for display errors)
        # Convert to integer type that can hold NaNs, fill NaNs with 0, then cast to string
        # This prevents errors from trying to cast empty strings or NaN directly to int/float for display.
        df['Group ID'] = df['Group ID'].fillna(0).astype(int).astype(str).replace('0', '')
        
    except Exception as e:
        st.error(f"Error during Transaction Grouping logic: {e}")
        st.error("Please check the consistency and data types of your 'Transaction Hash' column.")
        df['Group ID'] = ''
        df['Group Comment'] = 'Grouping Failed'

else:
    st.error("Cannot perform Transaction Grouping. Missing 'Transaction Hash' column.")


# --- Main Report Tabs ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔍 Data Overview", 
    "💸 Report 1: Currency Filter", 
    "⚖️ Report 2: Net Flow & Fees", 
    "💰 Report 3: Running Balance",
    "📈 Suggested Analytics"
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
         with col2:
            st.metric("Start Date", "N/A")
         with col3:
            st.metric("End Date", "N/A")

    # --- DEBUGGING FEATURE: Check loaded columns ---
    st.subheader("All Loaded Column Headers")
    st.code(list(df.columns))
    st.markdown("---")
    
    st.subheader("First 5 Rows of Data")
    st.dataframe(df.head(), use_container_width=True)
    
    st.subheader("Column Information")
    buffer = io.StringIO()
    df.info(buf=buffer)
