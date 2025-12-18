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
        
        # Safe handling of Balance Impact
        if 'Balance Impact (T)' in df.columns:
            df['Balance Impact (T)'] = df['Balance Impact (T)'].fillna(0).astype(np.float64)

        # CRITICAL FIX: Ensure Currency Symbol is always String (Text) to prevent sorting crashes
        if 'Original Currency Symbol' in df.columns:
            df['Original Currency Symbol'] = df['Original Currency Symbol'].fillna('UNKNOWN').astype(str)

        # Add Transaction Type column
        if 'Direction' in df.columns and 'Event Label' in df.columns:
            def categorize_transaction(row):
                # Safe check for direction
                direction = str(row['Direction']).lower()
                event = str(row['Event Label']).lower()
                
                if direction == 'inflow':
                    return 'inflow'
                elif direction == 'outflow':
                    if any(fee_keyword in event for fee_keyword in ['fee', 'gas', 'transaction cost']):
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
    
    if 'Original Currency Symbol' in df.columns:
        currency_options = sorted(df['Original Currency Symbol'].unique())
        selected_currency = st.selectbox("**Select an 'Original Currency Symbol' to filter:**", options=currency_options, index=0, key='currency_filter')
        
        if selected_currency:
            filtered_df = df[df['Original Currency Symbol'] == selected_currency].copy()
            st.subheader(f"All {len(filtered_df):,} transactions for: $\\text{{{selected_currency}}}$")
            st.dataframe(filtered_df, use_container_width=True)
            csv = filtered_df.to_csv(index=False).encode('utf-8')
            st.download_button(label=f"⬇️ Download {selected_currency} Transactions CSV", data=csv, file_name=f'Report_1_{selected_currency}.csv', mime='text/csv')
    else:
        st.warning("Column 'Original Currency Symbol' not found.")

# =========================================================================
# Tab 3: Report 2: Net Flow & Fees
# =========================================================================
with tab3:
    st.header("Report 2: Net Flow & Fees by Token (Pivot Table)")
    if 'Transaction Type' in df.columns and 'Balance Impact (T)' in df.columns:
        pivot_table = df.pivot_table(values='Balance Impact (T)', index='Original Currency Symbol', columns='Transaction Type', aggfunc='sum', fill_value=0)
        
        # Ensure columns exist to avoid KeyErrors
        for needed_col in ['inflow', 'outflow', 'fees', 'other']:
            if needed_col not in pivot_table.columns:
                pivot_table[needed_col] = 0.0

        pivot_table['net_flow'] = (pivot_table['inflow'] + pivot_table['outflow'] + pivot_table['fees'] + pivot_table['other'])
        pivot_table.columns = [str(col).replace('_', ' ').title() for col in pivot_table.columns]
        pivot_table.rename(columns={'Net Flow': 'Net Flow (Balance Impact)'}, inplace=True)
        pivot_table = pivot_table.sort_values(by='Net Flow (Balance Impact)', ascending=False)
        st.dataframe(pivot_table, use_container_width=True)
        
        csv_pivot = pivot_table.to_csv().encode('utf-8')
        st.download_button(label="⬇️ Download Net Flow & Fees Pivot Table CSV", data=csv_pivot, file_name='Report_2_Net_Flow_Fees_Pivot.csv', mime='text/csv')
        
        chart_df = pivot_table.reset_index()[['Original Currency Symbol', 'Net Flow (Balance Impact)']]
        chart = alt.Chart(chart_df).mark_bar().encode(
            x=alt.X('Original Currency Symbol', sort='-y', axis=None), 
            y=alt.Y('Net Flow (Balance Impact)', title="Net Balance Impact (T)"),
            color=alt.condition(alt.datum['Net Flow (Balance Impact)'] > 0, alt.value("green"), alt.value("red")),
            tooltip=['Original Currency Symbol', alt.Tooltip('Net Flow (Balance Impact)', format=",.4f")]
        ).properties(title="Token Net Flow (Sorted)").interactive()
        st.altair_chart(chart, use_container_width=True)
    else:
        st.warning("Cannot generate Pivot Table.")

# =========================================================================
# Tab 4: Report 3: Running Balance
# =========================================================================
with tab4:
    st.header("Report 3: Token Running Balance")
    if 'Running Balance (T)' in df.columns and 'Timestamp' in df.columns:
        # Sort options safely
        rb_currency_options = sorted(df['Original Currency Symbol'].unique())
        selected_rb_currency = st.selectbox("**Select a Token to view its Running Balance:**", options=rb_currency_options, key='rb_currency_filter')
        rb_filtered_df = df[df['Original Currency Symbol'] == selected_rb_currency].copy()
        st.subheader(f"Running Balance for: $\\text{{{selected_rb_currency}}}$")
        
        display_cols = ['Timestamp', 'Original Currency Symbol', 'Direction', 'Event Label', 'Transaction Hash', 'Balance Impact (T)', 'Running Balance (T)', 'Balance Status', 'Total Fiat Amount ($)', 'From Address Name', 'To Address Name']
        final_display_cols = [col for col in display_cols if col in rb_filtered_df.columns]
        st.dataframe(rb_filtered_df[final_display_cols], use_container_width=True)

        csv_rb = rb_filtered_df[final_display_cols].to_csv(index=False).encode('utf-8')
        st.download_button(label=f"⬇️ Download Running Balance CSV", data=csv_rb, file_name=f'Report_3_Running_Balance_{selected_rb_currency}.csv', mime='text/csv')
        
        rb_chart_df = rb_filtered_df.copy()
        rb_chart_df.dropna(subset=['Timestamp', 'Running Balance (T)'], inplace=True)
        rb_chart = alt.Chart(rb_chart_df).mark_line(point=True).encode(
            x=alt.X('Timestamp', title='Date/Time'),
            y=alt.Y('Running Balance (T)', title=f'Running Balance ({selected_rb_currency})'),
            tooltip=['Timestamp', alt.Tooltip('Running Balance (T)', format=",.4f")]
        ).properties(title=f"Cumulative Balance of {selected_rb_currency}").interactive()
        st.altair_chart(rb_chart, use_container_width=True)
    else:
        st.error("Running Balance calculation failed.")

# =========================================================================
# Tab 5: Suggested Reports
# =========================================================================
with tab5:
    st.header("Suggested Analytics & Advanced Reports")
    with st.expander("Report 4: Top 10 Largest Transactions", expanded=True):
        if 'Total Fiat Amount ($)' in df.columns:
            top_transactions = df.iloc[(-df['Total Fiat Amount ($)'].abs()).argsort()[:10]].copy()
            st.dataframe(top_transactions, use_container_width=True)
            csv_tx = top_transactions.to_csv(index=False).encode('utf-8')
            st.download_button(label="⬇️ Download Top 10 CSV", data=csv_tx, file_name='Report_4_Top_10.csv', mime='text/csv')

    with st.expander("Report 5: Monthly Transaction Volume", expanded=True):
        if 'Timestamp' in df.columns and 'Total Fiat Amount ($)' in df.columns:
            temp_df = df[['Timestamp', 'Total Fiat Amount ($)']].dropna(subset=['Timestamp']).copy()
            monthly_data = temp_df.set_index('Timestamp').resample('M').agg(
                transaction_count=('Timestamp', 'size'),
                total_fiat_value=('Total Fiat Amount ($)', 'sum')
            ).reset_index()
            monthly_data['Month'] = monthly_data['Timestamp'].dt.to_period('M').astype(str)
            st.dataframe(monthly_data, use_container_width=True)
            
            base = alt.Chart(monthly_data).encode(x=alt.X('Month:O', title='Month'))
            line_count = base.mark_line(color='steelblue').encode(y=alt.Y('transaction_count', axis=alt.Axis(titleColor='steelblue')))
            bar_value = base.mark_bar(opacity=0.5).encode(y=alt.Y('total_fiat_value', axis=alt.Axis(titleColor='orange')), color=alt.value("orange"))
            st.altair_chart(line_count + bar_value, use_container_width=True)

    with st.expander("Report 6: Top 10 Counterparties"):
        counterparty_col = next((col for col in df.columns if '3rd Party' in col or 'To Address' in col or 'From Address' in col), None)
        if counterparty_col:
            top_cp = df[counterparty_col].value_counts().head(10).reset_index()
            top_cp.columns = [counterparty_col, 'Transaction Count']
            st.dataframe(top_cp, use_container_width=True)
            chart_cp = alt.Chart(top_cp).mark_bar().encode(x=alt.X('Transaction Count'), y=alt.Y(counterparty_col, sort='-x')).properties(title="Top Counterparties")
            st.altair_chart(chart_cp, use_container_width=True)

# =========================================================================
# Tab 6: Report: Date-Specific Flow (UPDATED & FIXED)
# =========================================================================
with tab6:
    st.header("Report Settings: Flows & Balances")
    
    # 1. Filters Layout
    col_r6_1, col_r6_2 = st.columns(2)
    
    with col_r6_1:
        # Token Filter: Added 'ALL'
        # SAFE SORTING FIX: Convert to string before sorting to prevent app crashes on mixed data
        unique_tokens = sorted([str(x) for x in df['Original Currency Symbol'].unique()])
        r6_tokens = ['ALL'] + unique_tokens
        
        selected_token_r6 = st.selectbox(
            "Select Token (Currency)", 
            options=r6_tokens,
            key='r6_token_select'
        )
        
    with col_r6_2:
        # Date Filter
        default_date = df['Timestamp'].max().date() if 'Timestamp' in df.columns and not df['Timestamp'].isnull().all() else datetime.date.today()
        balance_eod_date = st.date_input("Balance As Of EOD", value=default_date, key='r6_date_picker')

    st.markdown("---")
    
    # 2. Calculation Logic
    if 'Timestamp' in df.columns and 'Transaction Type' in df.columns and 'Balance Impact (T)' in df.columns:
        
        # LOGIC FOR "ALL" TOKENS
        if selected_token_r6 == 'ALL':
            mask_date = df['Timestamp'].dt.date <= balance_eod_date
            df_r6_all = df[mask_date].copy()
            
            if not df_r6_all.empty:
                st.subheader(f"Financial Summary: All Tokens")
                st.caption(f"Aggregated data for all tokens up to EOD: {balance_eod_date}")
                
                summary_table = df_r6_all.pivot_table(
                    index='Original Currency Symbol',
                    columns='Transaction Type',
                    values='Balance Impact (T)',
                    aggfunc='sum',
                    fill_value=0
                )
                
                for col in ['inflow', 'outflow', 'fees', 'other']:
                    if col not in summary_table.columns:
                        summary_table[col] = 0.0
                        
                summary_table['Net Balance'] = (
                    summary_table['inflow'] + 
                    summary_table['outflow'] + 
                    summary_table['fees'] + 
                    summary_table['other']
                )
                
                summary_table = summary_table[['inflow', 'outflow', 'fees', 'Net Balance']]
                summary_table.columns = ['Total Inflow', 'Total Outflow', 'Total Fees', 'Net Balance (As of Date)']
                summary_table = summary_table.sort_values(by='Net Balance (As of Date)', ascending=False)
                
                st.dataframe(summary_table, use_container_width=True)
                
                csv_r6_all = summary_table.to_csv().encode('utf-8')
                st.download_button(
                    label=f"⬇️ Download All Tokens Summary (As of {balance_eod_date})",
                    data=csv_r6_all,
                    file_name=f'Report_Date_Range_ALL_{balance_eod_date}.csv',
                    mime='text/csv',
                )
            else:
                st.info(f"No transactions found on or before {balance_eod_date}.")

        # LOGIC FOR SINGLE SPECIFIC TOKEN
        else:
            mask_r6 = (
                (df['Original Currency Symbol'] == selected_token_r6) & 
                (df['Timestamp'].dt.date <= balance_eod_date)
            )
            
            df_r6 = df[mask_r6].copy()
            
            if not df_r6.empty:
                inflow_sum = df_r6[df_r6['Transaction Type'] == 'inflow']['Balance Impact (T)'].sum()
                outflow_sum = df_r6[df_r6['Transaction Type'] == 'outflow']['Balance Impact (T)'].sum()
                fees_sum = df_r6[df_r6['Transaction Type'] == 'fees']['Balance Impact (T)'].sum()
                other_sum = df_r6[df_r6['Transaction Type'] == 'other']['Balance Impact (T)'].sum()
                net_balance = inflow_sum + outflow_sum + fees_sum + other_sum
                
                st.subheader(f"Financials for {selected_token_r6}")
                st.caption(f"Data included from start up to EOD: {balance_eod_date}")
                
                col_met1, col_met2, col_met3, col_met4 = st.columns(4)
                with col_met1: st.metric(label="Total Inflow", value=f"{inflow_sum:,.4f}")
                with col_met2: st.metric(label="Total Outflow", value=f"{outflow_sum:,.4f}")
                with col_met3: st.metric(label="Total Fees", value=f"{fees_sum:,.4f}")
                with col_met4: st.metric(label="Net Balance (As of Date)", value=f"{net_balance:,.4f}")
                
                st.markdown("### Transaction Details (Filtered Range)")
                st.dataframe(df_r6, use_container_width=True)
                
                csv_r6 = df_r6.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"⬇️ Download {selected_token_r6} Report (As of {balance_eod_date})",
                    data=csv_r6,
                    file_name=f'Report_Date_Range_{selected_token_r6}_{balance_eod_date}.csv',
                    mime='text/csv',
                )
            else:
                st.info(f"No transactions found for **{selected_token_r6}** on or before **{balance_eod_date}**.")
            
    else:
        st.error("Required columns ('Timestamp', 'Transaction Type', 'Balance Impact (T)') are missing. Cannot generate report.")
