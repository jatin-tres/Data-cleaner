import streamlit as st
import pandas as pd
import numpy as np
import io
import sys

# --- CHECK FOR ALTAIR (The likely cause of the current error) ---
try:
    import altair as alt
except ImportError:
    st.error("Missing dependency: The 'altair' library is required for charting.")
    st.error("Please run: pip install altair")
    sys.exit() # Exit the script if the dependency is missing

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
                # Robustly convert to numeric, cleaning up common financial formatting ($ ,)
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(r'[$,]', '', regex=True), 
                    errors='coerce' # Set non-numeric values to NaN
                )
        
        # Fill NaN in 'Original Currency Symbol'
        if 'Original Currency Symbol' in df.columns:
            df['Original Currency Symbol'] = df['Original Currency Symbol'].fillna('UNKNOWN')

        # Add a Transaction Type column for the pivot table logic (Report 2)
        if 'Direction' in df.columns and 'Event Label' in df.columns:
            def categorize_transaction(row):
                if row['Direction'] == 'inflow':
                    return 'inflow'
                elif row['Direction'] == 'outflow':
                    # Heuristics to identify fees (common in ledgers)
                    if any(fee_keyword in str(row['Event Label']).lower() for fee_keyword in ['fee', 'gas', 'transaction cost']):
                        return 'fees'
                    else:
                        return 'outflow'
                else:
                    return 'other'
            
            df['Transaction Type'] = df.apply(categorize_transaction, axis=1)
            
        # Ensure Timestamp is datetime for monthly report (Report 4)
        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
            df.dropna(subset=['Timestamp'], inplace=True)

        return df
    except Exception as e:
        st.error(f"Error loading or processing file: {e}")
        st.error("Please check that your column headers (like 'Balance Impact (T)', 'Total Fiat Amount ($)', etc.) match exactly.")
        return pd.DataFrame() # Return empty DataFrame on failure


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
    st.stop() # Stop execution if no file is uploaded

df = load_data(uploaded_file)

if df.empty:
    # Error message handled inside load_data
    st.stop() 

# --- Main Report Tabs ---
tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 Data Overview", 
    "💸 Report 1: Currency Filter", 
    "⚖️ Report 2: Net Flow & Fees", 
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
    
    st.subheader("First 5 Rows of Data")
    st.dataframe(df.head(), use_container_width=True)
    
    st.subheader("Column Information")
    # Using io.StringIO to capture df.info() output
    buffer = io.StringIO()
    df.info(buf=buffer)
    info_str = buffer.getvalue()
    st.code(info_str, language='text')

# =========================================================================
# Tab 2: Report 1: Transactions by 'Original Currency Symbol'
# =========================================================================
with tab2:
    st.header("Report 1: Filtered Transactions by Currency Symbol")
    st.markdown("View all transaction details for a specific asset using **Column T** data.")
    
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
        
        st.dataframe(filtered_df, use_container_width=True)
        
        # Download option
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label=f"⬇️ Download {selected_currency} Transactions CSV",
            data=csv,
            file_name=f'{selected_currency}_transactions.csv',
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

        # Calculate Net Flow
        pivot_table['net_flow'] = pivot_table['inflow'] + pivot_table['outflow'] + pivot_table.get('fees', 0)
        
        # Clean up column names
        pivot_table.columns = [col.replace('_', ' ').title() for col in pivot_table.columns]
        pivot_table.rename(columns={'Net Flow': 'Net Flow (Balance Impact)'}, inplace=True)
        
        pivot_table = pivot_table.sort_values(by='Net Flow (Balance Impact)', ascending=False)
        
        st.dataframe(pivot_table, use_container_width=True)
        
        st.markdown(
            """
            * **Inflow/Outflow/Fees**: Sum of Balance Impact (T) for each category.
            * **Net Flow (Balance Impact)**: Total change in balance for that token ($\text{Inflow} + \text{Outflow} + \text{Fees}$).
            """
        )

        st.subheader("Net Flow Visualization")
        chart_df = pivot_table.reset_index()[['Original Currency Symbol', 'Net Flow (Balance Impact)']]
        
        chart = alt.Chart(chart_df).mark_bar().encode(
            x=alt.X('Original Currency Symbol', sort='-y', axis=None), 
            y=alt.Y('Net Flow (Balance Impact)', title="Net Balance Impact (T)"),
            color=alt.condition(
                alt.datum['Net Flow (Balance Impact)'] > 0,
                alt.value("green"),  # Positive flow is green
                alt.value("red")     # Negative flow is red
            ),
            tooltip=['Original Currency Symbol', alt.Tooltip('Net Flow (Balance Impact)', format=",.4f")]
        ).properties(
            title="Token Net Flow (Sorted)"
        ).interactive()

        st.altair_chart(chart, use_container_width=True)

    else:
        st.warning("Cannot generate Pivot Table. Check if 'Direction' and 'Balance Impact (T)' columns exist.")


# =========================================================================
#
