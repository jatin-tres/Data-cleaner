import streamlit as st
import pandas as pd
import numpy as np

# --- Configuration ---
st.set_page_config(layout="wide", page_title="Transaction Ledger Analyzer")

# --- Helper Function to Load Data ---
@st.cache_data
def load_data(uploaded_file):
    """Loads CSV data into a DataFrame."""
    try:
        df = pd.read_csv(uploaded_file)
        
        # Standardize column names by stripping whitespace
        df.columns = df.columns.str.strip()
        
        # --- Data Cleaning and Type Conversion ---
        
        # Convert relevant columns to numeric, coercing errors to NaN
        numeric_cols = [
            'Transfer Unit Fiat Price ($)', 
            'Balance Impact (T)', 
            'Total Fiat Amount ($)',
        ]
        for col in numeric_cols:
            if col in df.columns:
                # Remove commas and convert to float (or use astype)
                # Using to_numeric for robustness
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce')
        
        # Fill NaN in 'Original Currency Symbol' for better grouping
        if 'Original Currency Symbol' in df.columns:
            df['Original Currency Symbol'] = df['Original Currency Symbol'].fillna('UNKNOWN')

        # Add a Transaction Type column for the pivot table logic
        if 'Direction' in df.columns and 'Event Label' in df.columns:
            def categorize_transaction(row):
                if row['Direction'] == 'inflow':
                    return 'inflow'
                elif row['Direction'] == 'outflow':
                    # Assuming 'Fees' are often labeled with a specific Event Label, 
                    # or you can use a more specific logic for your data.
                    # This is a common pattern in ledgers.
                    if 'fee' in str(row['Event Label']).lower():
                        return 'fees'
                    else:
                        return 'outflow'
                else:
                    return 'other'
            
            df['Transaction Type'] = df.apply(categorize_transaction, axis=1)

        return df
    except Exception as e:
        st.error(f"Error loading or processing file: {e}")
        return pd.DataFrame() # Return empty DataFrame on failure


# --- Streamlit App Layout ---

st.title("💰 Transaction Ledger Report Generator")

# --- File Uploader ---
uploaded_file = st.sidebar.file_uploader(
    "Upload your raw transactions CSV file", 
    type=['csv']
)

if uploaded_file is None:
    st.info("Please upload a CSV file in the sidebar to begin generating reports.")
else:
    df = load_data(uploaded_file)
    
    if df.empty:
        st.stop() # Stop execution if data loading failed

    st.header("Uploaded Data Overview")
    st.write(df.head())
    st.success(f"Data loaded successfully! Total records: {len(df)}")
    st.markdown("---")


    # =========================================================================
    # Report 1: Transactions by 'Original Currency Symbol'
    # =========================================================================
    st.header("1. Filtered Transactions by Currency Symbol")
    
    # Get unique currency symbols for the select box
    currency_options = df['Original Currency Symbol'].unique()
    
    selected_currency = st.selectbox(
        "Select an 'Original Currency Symbol' to filter transactions:",
        options=currency_options
    )
    
    # Filter the DataFrame
    filtered_df = df[df['Original Currency Symbol'] == selected_currency].copy()
    
    st.subheader(f"All transactions for: ${selected_currency}$")
    st.write(f"Total transactions found: {len(filtered_df)}")
    
    # Display the filtered data with all columns
    st.dataframe(filtered_df, use_container_width=True)
    st.markdown("---")


    # =========================================================================
    # Report 2: Net Inflow, Outflow, and Fees Pivot Table (by Currency)
    # =========================================================================
    st.header("2. Net Flow & Fees Pivot Table by Token")
    
    # Aggregate 'Balance Impact (T)' by 'Original Currency Symbol' and 'Transaction Type'
    if 'Transaction Type' in df.columns and 'Balance Impact (T)' in df.columns:
        pivot_table = df.pivot_table(
            values='Balance Impact (T)',
            index='Original Currency Symbol',
            columns='Transaction Type',
            aggfunc='sum',
            fill_value=0 # Fill NaN with 0 for cleaner reporting
        )

        # Calculate Net Flow
        pivot_table['net_flow'] = pivot_table['inflow'] + pivot_table['outflow'] + pivot_table.get('fees', 0)
        
        # Rename columns for better display
        pivot_table.columns = ['Fees' if col == 'fees' else col.title() for col in pivot_table.columns]
        pivot_table.rename(columns={'Net_Flow': 'Net Flow (Balance Impact)'}, inplace=True)

        st.dataframe(pivot_table.sort_values(by='Net Flow (Balance Impact)', ascending=False), use_container_width=True)
        
        st.markdown(
            """
            *Interpretation:*
            * **Inflow**: The sum of 'Balance Impact (T)' for all 'inflow' transactions.
            * **Outflow**: The sum of 'Balance Impact (T)' for all 'outflow' transactions (this will be negative).
            * **Fees**: The sum of 'Balance Impact (T)' for all fee-related transactions (this will be negative).
            * **Net Flow (Balance Impact)**: The total change in balance for that token ($\text{Inflow} + \text{Outflow} + \text{Fees}$).
            """
        )
    else:
        st.warning("Cannot generate Pivot Table. Check if 'Direction' and 'Balance Impact (T)' columns exist and are correctly named.")
    st.markdown("---")


    # =========================================================================
    # Suggested Reports
    # =========================================================================
    st.header("✨ Suggested Reports")

    # --- Suggestion 1: Top 10 Largest Transactions (by Fiat Amount)
