import sqlite3
import pandas as pd
import streamlit as st
import altair as alt

# Function to extract and format time columns from a table using pd.to_datetime with a specified format
def extract_time_columns(db_name, table_name, time_columns, additional_columns=None, time_format='%Y-%m-%d %H:%M:%S'):
    try:
        conn = sqlite3.connect(db_name)
        columns = time_columns + (additional_columns if additional_columns else [])
        query = f"SELECT {', '.join(columns)} FROM {table_name}"
        df = pd.read_sql_query(query, conn)
        conn.close()
        # Convert time columns to datetime format using pd.to_datetime with a specified format
        for col in time_columns:
            df[col] = pd.to_datetime(df[col], format=time_format, errors='coerce')
        df['TableName'] = table_name  # Add the table name as a column
        return df
    except Exception as e:
        print(f"Error extracting data from {table_name} in {db_name}: {e}")
        return pd.DataFrame()

# Extract time columns from each table
log_claw_tables = {
    'SystemLogs': ['TimeGenerated', 'Source', 'EventID'],
    'ApplicationLogs': ['TimeGenerated', 'Source', 'EventID'],
    'SecurityLogs': ['TimeGenerated', 'Source', 'EventID']
}
prefetch_tables = {
    'prefetch_files': ['last_modified', 'last_accessed', 'creation_time', 'executable_name']
}
lnkdb_tables = {
    'JLCE': ['Time_Access', 'Time_Creation', 'Time_Modification', 'Source_Name', 'Artifact'],
    'Custom_JLCE': ['Time_Access', 'Time_Creation', 'Time_Modification', 'Source_Name', 'Artifact']
}

# Initialize empty lists to store dataframes
log_claw_dfs = []
prefetch_dfs = []
lnkdb_dfs = []

# Extract dataframes for Log_Claw tables
for table, cols in log_claw_tables.items():
    log_claw_dfs.append(extract_time_columns('Log_Claw.db', table, cols))

# Extract dataframes for Prefetch tables
for table, cols in prefetch_tables.items():
    prefetch_dfs.append(extract_time_columns('Prefetch.db', table, cols))

# Extract dataframes for LnkDB tables
for table, cols in lnkdb_tables.items():
    lnkdb_dfs.append(extract_time_columns('LnkDB.db', table, cols))

# Combine all dataframes into one
all_dfs = log_claw_dfs + prefetch_dfs + lnkdb_dfs
combined_df = pd.concat(all_dfs, ignore_index=True)

# Step 2: Create three time frames: one for all creation or time generated, the second for the time access, and the third for time modification
# Filter the combined dataframe for each time frame
creation_time_df = combined_df.filter(regex='TimeGenerated|creation_time|Time_Creation|TableName')
access_time_df = combined_df.filter(regex='last_accessed|Time_Access|TableName')
modification_time_df = combined_df.filter(regex='last_modified|Time_Modification|TableName')

# Step 3: Prepare the data for the scatter chart
# Melt the dataframes to have a single column for time and a column for the type of time (creation, modification, access)
creation_time_melted = creation_time_df.melt(id_vars=['TableName'], var_name='Time_Type', value_name='Time')
access_time_melted = access_time_df.melt(id_vars=['TableName'], var_name='Time_Type', value_name='Time')
modification_time_melted = modification_time_df.melt(id_vars=['TableName'], var_name='Time_Type', value_name='Time')

# Add a column to indicate the source database and type of time
creation_time_melted['Database'] = creation_time_melted['Time_Type'].apply(lambda x: 'Log_Claw' if 'TimeGenerated' in x else ('Prefetch' if 'creation_time' in x else 'LnkDB'))
creation_time_melted['Type'] = 'Creation/Generation'
access_time_melted['Database'] = access_time_melted['Time_Type'].apply(lambda x: 'Prefetch' if 'last_accessed' in x else 'LnkDB')
access_time_melted['Type'] = 'Access'
modification_time_melted['Database'] = modification_time_melted['Time_Type'].apply(lambda x: 'Prefetch' if 'last_modified' in x else 'LnkDB')
modification_time_melted['Type'] = 'Modification'

# Combine all melted dataframes into one
melted_df = pd.concat([creation_time_melted, access_time_melted, modification_time_melted], ignore_index=True)

# Add a column to indicate the source or executable name based on the table
def get_source_or_executable(row):
    if row['Database'] == 'Log_Claw':
        return row.get('Source', '')
    elif row['Database'] == 'Prefetch':
        return row.get('executable_name', '')
    else:
        return row.get('Source_Name', '')

melted_df['SourceOrExecutable'] = melted_df.apply(get_source_or_executable, axis=1)

# Step 4: Create the scatter chart using Altair
scatter_chart = alt.Chart(melted_df).mark_circle(size=60).encode(
    x='Time:T',
    y=alt.Y('Type:N', title='Type of Time'),
    color='Database:N',
    tooltip=['Database:N', 'TableName:N', 'SourceOrExecutable:N', 'Time:T']
).properties(
    title='Crow Eye Timeline',
    width=800,
    height=600
)

# Display the scatter chart in Streamlit
st.title("Crow Eye Timeline")
st.altair_chart(scatter_chart, use_container_width=True)