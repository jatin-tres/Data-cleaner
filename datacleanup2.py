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
            df.dropna(subset=['Timestamp'], inplace=True)

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
# --- CORE DATA PROCESSING (Running Balance Calculation) ---
# =========================================================================

# Check both key columns for Running Balance
if 'Timestamp' in df.columns and 'Balance Impact (T)' in df.columns:
    # 1. Sort by Timestamp (ascending A to Z) as requested
    df = df.sort_values(by='Timestamp', ascending=True).reset_index(drop=True)

    # 2. Calculate Running Balance for each Token
    df['Running Balance (T)'] = df.groupby('Original Currency Symbol')['Balance Impact (T)'].cumsum()
else:
    st.error("Cannot calculate Running Balance. Missing 'Timestamp' or 'Balance Impact (T)' column. Check Tab 1 for loaded column names.")


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
    info_str = buffer.getvalue()
    st.code(info_str, language='text')

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
        
        st.dataframe(filtered_df, use_container_width=True)
        
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

        pivot_table['net_flow'] = pivot_table['inflow'] + pivot_table['outflow'] + pivot_table.get('fees', 0)
        
        pivot_table.columns = [col.replace('_', ' ').title() for col in pivot_table.columns]
        pivot_table.rename(columns={'Net Flow': 'Net Flow (Balance Impact)'}, inplace=True)
        
        pivot_table = pivot_table.sort_values(by='Net Flow (Balance Impact)', ascending=False)
        
        st.dataframe(pivot_table, use_container_width=True)
        
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

        st.altair_chart(chart, use_container_width=True)

    else:
        st.warning("Cannot generate Pivot Table. Check if 'Direction' and 'Balance Impact (T)' columns exist.")


# =========================================================================
# Tab 4: Report 3: Running Balance
# =========================================================================
with tab4:
    st.header("Report 3: Token Running Balance")
    st.markdown("Displays the **cumulative balance (net asset holdings)** for a selected token, sorted by **Timestamp**.")
    
    if 'Running Balance (T)' in df.columns:
        rb_currency_options = df['Original Currency Symbol'].unique()
        selected_rb_currency = st.selectbox(
            "**Select a Token to view its Running Balance:**",
            options=rb_currency_options,
            key='rb_currency_filter' 
        )

        rb_filtered_df = df[df['Original Currency Symbol'] == selected_rb_currency].copy()
        
        st.subheader(f"Running Balance for: $\\text{{{selected_rb_currency}}}$ ({len(rb_filtered_df):,} transactions)")
        
        display_cols = [
            'Timestamp', 
            'Original Currency Symbol', 
            'Direction', 
            'Event Label',
            'Balance Impact (T)', 
            'Running Balance (T)',
            'Total Fiat Amount ($)',
            'From Address Name', 
            'To Address Name'
        ]
        
        final_display_cols = [col for col in display_cols if col in rb_filtered_df.columns]
        
        st.dataframe(rb_filtered_df[final_display_cols], use_container_width=True)
        
        st.subheader("Running Balance Over Time")
        rb_chart = alt.Chart(rb_filtered_df).mark_line(point=True).encode(
            x=alt.X('Timestamp', title='Date/Time'),
            y=alt.Y('Running Balance (T)', title=f'Running Balance ({selected_rb_currency})'),
            tooltip=['Timestamp', alt.Tooltip('Running Balance (T)', format=",.4f")]
        ).properties(
            title=f"Cumulative Balance of {selected_rb_currency}"
        ).interactive()

        st.altair_chart(rb_chart, use_container_width=True)
    else:
        st.error("Running Balance calculation failed. Please ensure 'Timestamp' and 'Balance Impact (T)' columns are present and data is numeric.")


# =========================================================================
# Tab 5: Suggested Reports
# =========================================================================
with tab5:
    st.header("Suggested Analytics & Advanced Reports")

    with st.expander("Report 4: Top 10 Largest Transactions (by Fiat Amount)", expanded=True):
        st.markdown("Identifies the highest value transactions (inflow/outflow) based on **Total Fiat Amount ($)**.")
        if 'Total Fiat Amount ($)' in df.columns:
            top_transactions = df.iloc[(-df['Total Fiat Amount ($)'].abs()).argsort()[:10]].copy()
            
            top_transactions['Total Fiat Amount ($)'] = top_transactions['Total Fiat Amount ($)'].apply(
                lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A"
            )
            
            st.dataframe(
                top_transactions[[
                    'Timestamp', 
                    'Original Currency Symbol', 
                    'Direction', 
                    'Total Fiat Amount ($)',
                    'Event Label',
                    'From Address Name', 
                    'To Address Name'
                ]],
                use_container_width=True
            )
        else:
            st.warning("Cannot generate Top Transactions report. 'Total Fiat Amount ($)' column is missing.")

    st.markdown("---")

    with st.expander("Report 5: Monthly Transaction Volume", expanded=True):
        st.markdown("Visualizes transaction count and total fiat value over time.")
        
        if 'Timestamp' in df.columns and 'Total Fiat Amount ($)' in df.columns:
            try:
                monthly_data = df.set_index('Timestamp').resample('M').agg(
                    transaction_count=('Timestamp', 'size'),
                    total_fiat_value=('Total Fiat Amount ($)', 'sum')
                ).reset_index()
                
                monthly_data['Month'] = monthly_data['Timestamp'].dt.to_period('M').astype(str)

                st.dataframe(
                    monthly_data[['Month', 'transaction_count', 'total_fiat_value']].rename(
                        columns={
                            'transaction_count': 'Transaction Count',
                            'total_fiat_value': 'Total Fiat Value ($)'
                        }
                    ), 
                    use_container_width=True
                )
                
                base = alt.Chart(monthly_data).encode(x=alt.X('Month:O', title='Month'))
                
                line_count = base.mark_line(color='steelblue').encode(
                    y=alt.Y('transaction_count', title='Transaction Count', axis=alt.Axis(titleColor='steelblue')),
                    tooltip=['Month:O', 'transaction_count']
                )
                
                bar_value = base.mark_bar(opacity=0.5).encode(
                    y=alt.Y('total_fiat_value', title='Total Fiat Value ($)', axis=alt.Axis(titleColor='orange')),
                    color=alt.value("orange"),
                    tooltip=['Month:O', alt.Tooltip('total_fiat_value', format="$,.2f")]
                )
                
                st.altair_chart(line_count + bar_value, use_container_width=True)

            except Exception as e:
                st.warning(f"Error generating Monthly Volume: {e}")
        else:
            st.warning("Cannot generate Monthly Volume report. 'Timestamp' or 'Total Fiat Amount ($)' columns are missing.")
            
    st.markdown("---")

    with st.expander("Report 6: Top 10 Counterparties (By Count)"):
        st.markdown("Identifies the most frequent counterparties involved in your transactions, based on relevant address columns.")
        
        counterparty_col = next((col for col in df.columns if '3rd Party' in col or 'To Address' in col or 'From Address' in col), None)

        if counterparty_col:
            top_counterparties = df[counterparty_col].value_counts().head(10).reset_index()
            top_counterparties.columns = [counterparty_col, 'Transaction Count']
            st.dataframe(top_counterparties, use_container_width=True)
            
            chart_cp = alt.Chart(top_counterparties).mark_bar().encode(
                x=alt.X('Transaction Count'),
                y=alt.Y(counterparty_col, sort='-x', title='Counterparty Address/Name'),
                tooltip=[counterparty_col, 'Transaction Count']
            ).properties(
                title="Top 10 Counterparties by Transaction Count"
            )
            st.altair_chart(chart_cp, use_container_width=True)
        else:
            st.warning("Cannot generate Counterparties report. A '3rd Party' or 'Address' column is missing or not identifiable.")

# -------------------------------------------------------------------------
# --- How to Run Section (in sidebar) ---
# -------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    ### ⚙️ How to Run This App

    1.  **Install Libraries (Crucial Step!):**
        ```bash
        pip install streamlit pandas numpy altair
        ```
    2.  **Save the code** above as a file named `app.py`.
    3.  **Run the command** in your terminal:
        ```bash
        streamlit run app.py
        ```
    """
)
