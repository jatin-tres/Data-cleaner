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

# --- Helper Function for Debugging Conversion Failures (Still retained for safety) ---
def safe_to_numeric(series, column_name):
    """Converts series to numeric and returns indices where conversion failed."""
    
    # 1. Clean up currency formatting
    cleaned_series = series.astype(str).str.replace(r'[$,]', '', regex=True)
    
    # 2. Attempt conversion
    numeric_series = pd.to_numeric(cleaned_series, errors='coerce')
    
    # 3. Find indices that failed to convert (are NaN after coercion)
    failed_indices = cleaned_series[numeric_series.isna()].index.tolist()
    
    # Exclude indices where the original value was already empty/NaN
    failed_indices = [idx for idx in failed_indices if cleaned_series.loc[idx].strip() != '']
    
    if failed_indices:
        st.warning(
            f"⚠️ Data Warning in '{column_name}': Non-empty data failed conversion at rows: {failed_indices[:5]}... "
            f"Using 0.0 for these values."
        )
    
    return numeric_series.fillna(0) # Return the converted series (fill NaN with 0 for calculation safety)


# --- Helper Function to Load Data (QA Checkpoint 1: Data Integrity) ---
@st.cache_data
def load_data(uploaded_file):
    """Loads CSV data into a DataFrame using the file buffer and performs initial cleaning."""
    try:
        # --- ROBUST FILE READING FIX ---
        stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
        df = pd.read_csv(stringio)
        # --- END FIX ---
        
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
                df[col] = safe_to_numeric(df[col], col)
        
        # --- CRITICAL FIX FOR RUNNING BALANCE (Report 3) ---
        if 'Balance Impact (T)' in df.columns:
            # Re-cast as float64, using the cleaned series (which fills NaN/fails with 0)
            df['Balance Impact (T)'] = df['Balance Impact (T)'].astype(np.float64)

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
            
            # --- FINAL STABILITY FIX: Remove rows where Timestamp is unparseable ---
            df.dropna(subset=['Timestamp'], inplace=True)
            
            # Critical: Sort by time now to ensure running balance is correct before any logic runs
            df = df.sort_values(by='Timestamp', ascending=True).reset_index(drop=True)

        return df
    except Exception as e:
        st.error(f"FATAL: Error loading CSV file. Please ensure the file is a valid CSV and not corrupted. Error: {e}")
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

# --- RUNNING BALANCE CALCULATION (QA Checkpoint 2: Feature Stability) ---
try:
    if 'Timestamp' in df.columns and 'Balance Impact (T)' in df.columns:
        
        # Re-cast to numeric right before cumsum for maximum robustness 
        df['Balance Impact (T)'] = pd.to_numeric(df['Balance Impact (T)'], errors='coerce').fillna(0)

        # 1. Calculate Running Balance for each Token
        df['Running Balance (T)'] = df.groupby('Original Currency Symbol')['Balance Impact (T)'].cumsum()

        # 2. Create Status Column for Negative Balances
        df['Balance Status'] = df['Running Balance (T)'].apply(
            lambda x: "⚠️ NEGATIVE BALANCE" if x < 0 else "OK"
        )
    else:
        st.warning("Running Balance features disabled: Missing 'Timestamp' or 'Balance Impact (T)' column.")
        df['Running Balance (T)'] = np.nan
        df['Balance Status'] = "Feature Disabled"
except Exception as e:
    st.error(f"CRITICAL ERROR: Running Balance calculation failed. Error: {e}")
    df['Running Balance (T)'] = np.nan
    df['Balance Status'] = "Calculation Failed"


# --- TRANSACTION GROUPING LOGIC (QA Checkpoint 3: Feature Stability) ---
if 'Transaction Hash' in df.columns:
    try:
        # 1. Calculate the count of each transaction hash
        hash_counts = df['Transaction Hash'].value_counts()
        
        # 2. Identify hashes that are part of a group (count > 1)
        group_hashes = hash_counts[hash_counts > 1].index
        
        if len(group_hashes) > 0:
            # 3. Create a mapping for Group IDs (assign 1, 2, 3... to multi-part hashes)
            group_id_map = {hash_val: i + 1 for i, hash_val in enumerate(group_hashes)}
            
            # 4. Initialize new columns
            df['Group Comment'] = "NOT a group transaction"
        
            # 5. Apply the Group ID mapping (this will assign NaNs to non-group hashes)
            df['Group ID'] = df['Transaction Hash'].map(group_id_map)
            
            # 6. Apply the Group Comment
            df.loc[df['Group ID'].notna(), 'Group Comment'] = "Group Transaction"
            
            # 7. Final Safe Type Casting
            df['Group ID'] = df['Group ID'].fillna(0).astype(int).astype(str).replace('0', '')
            
        else:
            df['Group ID'] = ''
            df['Group Comment'] = 'NOT a group transaction'
            st.info("Transaction Grouping is available, but no multi-part transactions were found (all hashes occurred only once).")
        
    except Exception as e:
        st.error(f"CRITICAL ERROR: Transaction Grouping failed. Error: {e}")
        df['Group ID'] = 'Failed'
        df['Group Comment'] = 'Grouping Failed'

else:
    st.warning("Transaction Grouping features disabled: Missing 'Transaction Hash' column.")
    df['Group ID'] = 'Disabled'
    df['Group Comment'] = 'Feature Disabled'


# --- Main Report Tabs ---
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔍 Data Overview", 
    "💸 Report 1: Currency Filter", 
    "⚖️ Report 2: Net Flow & Fees", 
    "💰 Report 3: Running Balance",
    "🔗 Report 4: Transaction Grouping",
    "📈 Suggested Analytics"
])

# =========================================================================
# Tab 1: Data Overview (QA Checkpoint 4: Column Verification)
# =========================================================================
with tab1:
    st.header("Dataset Summary")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Transactions", f"{len(df):,}")
    
    if 'Timestamp' in df.columns and not df['Timestamp'].empty:
        with col2:
            try:
                st.metric("Start Date", df['Timestamp'].min().strftime('%Y-%m-%d'))
            except ValueError:
                 st.metric("Start Date", "N/A (Invalid Dates)")
        with col3:
            try:
                st.metric("End Date", df['Timestamp'].max().strftime('%Y-%m-%d'))
            except ValueError:
                 st.metric("End Date", "N/A (Invalid Dates)")
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
    st.dataframe(df.head(), width='stretch')
    
    st.subheader("Column Information")
    buffer = io.StringIO()
    df.info(buf=buffer)
    info_str = buffer.getvalue()
    st.code(info_str, language='text')
    
    st.markdown("---")
    st.markdown("If any reports are blank, please ensure the headers above match the required headers exactly:")
    st.code("['Timestamp', 'Balance Impact (T)', 'Transaction Hash', 'Total Fiat Amount ($)', 'Original Currency Symbol']")


# =========================================================================
# Tab 2: Report 1: Transactions by 'Original Currency Symbol'
# =========================================================================
with tab2:
    st.header("Report 1: Filtered Transactions by Currency Symbol")
    st.markdown("View all transaction details for a specific asset (Token Filter).")
    
    currency_options = df['Original Currency Symbol'].unique()
    
    selected_currency = st.selectbox(
        "**Select an 'Original Currency Symbol' to filter:**",
        options=currency_options,
        index=0,
        key='currency_filter' 
    )
    
    if selected_currency:
        filtered_df = df[df['Original Currency Symbol'] == selected_currency].copy()
        
        st.subheader(f"All {len(filtered_df):,} transactions for: $\\text{{{selected_currency}}}$")
        
        # Display columns (EXCLUDING Group ID/Comment/Running Balance)
        display_cols = [
            'Timestamp', 
            'Original Currency Symbol', 
            'Direction', 
            'Event Label',
            'Balance Impact (T)', 
            'Transaction Hash', 
            'Total Fiat Amount ($)',
            'From Address Name', 
            'To Address Name'
        ]
        final_display_cols = [col for col in display_cols if col in filtered_df.columns]
        st.dataframe(filtered_df[final_display_cols], width='stretch')
        
        # DOWNLOAD BUTTON (Report 1)
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label=f"⬇️ Download {selected_currency} Transactions CSV",
            data=csv,
            file_name=f'Report_1_Filtered_Transactions_{selected_currency}.csv',
            mime='text/csv',
        )

# =========================================================================
# Tab 3: Report 2: Net Flow, Outflow, and Fees Pivot Table
# =========================================================================
with tab3:
    st.header("Report 2: Net Flow & Fees by Token (Pivot Table)")
    st.markdown("Shows the aggregated **inflow, outflow, and fees** for each token based on the **Balance Impact (T)** column.")

    if 'Transaction Type' in df.columns and 'Balance Impact (T)' in df.columns:
        pivot_table = df.pivot_table(
            values='Balance Impact (T)',
            index='Original Currency Symbol',
            columns='Transaction Type',
            aggfunc='sum',
            fill_value=0 
        )

        pivot_table['net_flow'] = pivot_table['inflow'] + pivot_table['outflow'] + pivot_table.get('fees', 0)
        
        pivot_table.columns = [col.replace('_', ' ').title() for col in pivot_table.columns]
        pivot_table.rename(columns={'Net Flow': 'Net Flow (Balance Impact)'}, inplace=True)
        
        pivot_table = pivot_table.sort_values(by='Net Flow (Balance Impact)', ascending=False)
        
        st.dataframe(pivot_table, width='stretch')

        # DOWNLOAD BUTTON (Report 2)
        csv_pivot = pivot_table.to_csv().encode('utf-8')
        st.download_button(
            label="⬇️ Download Net Flow & Fees Pivot Table CSV",
            data=csv_pivot,
            file_name='Report_2_Net_Flow_Fees_Pivot.csv',
            mime='text/csv',
        )
        
        st.subheader("Net Flow Visualization")
        chart_df = pivot_table.reset_index()[['Original Currency Symbol', 'Net Flow (Balance Impact)']]
        
        chart = alt.Chart(chart_df).mark_bar().encode(
            x=alt.X('Original Currency Symbol', sort='-y', axis=None), 
            y=alt.Y('Net Flow (Balance Impact)', title="Net Balance Impact (T)"),
            color=alt.condition(
                alt.datum['Net Flow (Balance Impact)'] > 0,
                alt.value("green"),
                alt.value("red")
            ),
            tooltip=['Original Currency Symbol', alt.Tooltip('Net Flow (Balance Impact)', format=",.4f")]
        ).properties(
            title="Token Net Flow (Sorted)"
        ).interactive()

        st.altair_chart(chart, width='stretch')

    else:
        st.warning("Cannot generate Pivot Table. Check if 'Direction' and 'Balance Impact (T)' columns exist.")


# =========================================================================
# Tab 4: Report 3: Running Balance (EXCLUDING Grouping)
# =========================================================================
with tab4:
    st.header("Report 3: Token Running Balance")
    st.markdown("Displays the **cumulative balance (net asset holdings)** for a selected token, sorted by **Timestamp**. Includes a **`Balance Status`** warning.")
    
    if 'Running Balance (T)' in df.columns and df['Running Balance (T)'].notna().any():
        rb_currency_options = df['Original Currency Symbol'].unique()
        selected_rb_currency = st.selectbox(
            "**Select a Token to view its Running Balance:**",
            options=rb_currency_options,
            key='rb_currency_filter' 
        )

        rb_filtered_df = df[df['Original Currency Symbol'] == selected_rb_currency].copy()
        
        st.subheader(f"Running Balance for: $\\text{{{selected_rb_currency}}}$ ({len(rb_filtered_df):,} transactions)")
        
        # Display columns (EXCLUDING Group ID/Comment)
        display_cols = [
            'Timestamp', 
            'Original Currency Symbol', 
            'Direction', 
            'Event Label',
            'Balance Impact (T)', 
            'Running Balance (T)',
            'Balance Status', 
            'Transaction Hash',
            'Total Fiat Amount ($)',
            'From Address Name', 
            'To Address Name'
        ]
        
        final_display_cols = [col for col in display_cols if col in rb_filtered_df.columns]
        st.dataframe(rb_filtered_df[final_display_cols], width='stretch')

        # DOWNLOAD BUTTON (Report 3)
        csv_rb = rb_filtered_df[final_display_cols].to_csv(index=False).encode('utf-8')
        st.download_button(
            label=f"⬇️ Download Running Balance for {selected_rb_currency} CSV",
            data=csv_rb,
            file_name=f'Report_3_Running_Balance_{selected_rb_currency}.csv',
            mime='text/csv',
        )
        
        st.subheader("Running Balance Over Time")
        
        # Ensure data types are correct for Altair before charting
        rb_chart_df = rb_filtered_df.copy
