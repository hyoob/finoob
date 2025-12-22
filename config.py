import streamlit as st

# Helper function to generate the column with dynamic options
def get_category_column(options):
    return st.column_config.SelectboxColumn(
        "category",
        help="The category of the transaction",
        width="medium",
        options=options,
        required=True,
    )

TRANSACTION_COLUMN_CONFIG = {
    "date": st.column_config.DateColumn(
        "date",
        format="YYYY-MM-DD"
    ),
    "label": st.column_config.TextColumn(
        "label",
        help="The subcategory of the transaction",
        required=True,
    )
}