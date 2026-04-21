import streamlit as st
import asyncio
import os
import json
import requests
import pandas as pd
from io import BytesIO
from src.places_api import search_places, get_coordinates
from src.business_info import process_businesses
from src.data_export import save_places_to_excel
from src.utils import get_current_date
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Google Maps Lead Generator",
    page_icon=":material/map:",
    layout="wide"
)

# App title and description
st.title("AI-Powered Google Maps Lead Generator")
st.markdown(
    """
    This tool helps you generate leads from Google Maps by:
    1. Searching for businesses matching your criteria
    2. Extracting contact information from their websites
    3. Using AI to find emails and social media profiles
    """
)

# Sidebar for settings
with st.sidebar:
    st.header("Settings")

    # API Keys
    st.subheader("API Keys")
    serper_api_key = st.text_input("Serper API Key", type="password")
    openrouter_api_key = st.text_input("OpenRouter API Key", type="password")

    # LLM Model Settings
    st.subheader("LLM Model")
    llm_model = st.selectbox(
        "Select LLM Model",
        options=[
            "openai/gpt-4.1-mini",
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
            "anthropic/claude-3.5-sonnet",
            "deepseek/deepseek-chat",
            "mistral/mistral-large-2"
        ],
        index=0,
    )

    # Database API
    st.subheader("Database API")
    api_base_url = st.text_input("API Base URL", value=os.environ.get("API_BASE_URL", "http://localhost:8000"))

    # Save settings button
    if st.button("Save Settings", icon=":material/save:"):
        os.environ["SERPER_API_KEY"] = serper_api_key
        os.environ["OPENROUTER_API_KEY"] = openrouter_api_key
        os.environ["LLM_MODEL"] = llm_model
        os.environ["API_BASE_URL"] = api_base_url
        st.success("Settings saved for this session!")

# Main form
with st.form("search_form"):
    col1, col2 = st.columns(2)

    with col1:
        location = st.text_input("Location (city, address, etc.)", value="New York")
        search_query = st.text_input("Search Query (e.g., 'coffee shops', 'dentists')", value="Real Estate Agents")

    with col2:
        num_places = st.number_input("Number of Places to Scrape", min_value=20, max_value=1000, value=20, step=20)
        num_pages = max(1, num_places // 20)

    submit_button = st.form_submit_button(
        "Start Lead Generation",
        icon=":material/search:",
    )

# Initialize session state if not already done
if "excel_path" not in st.session_state:
    st.session_state.excel_path = None
if "last_search_query" not in st.session_state:
    st.session_state.last_search_query = ""
if "last_location" not in st.session_state:
    st.session_state.last_location = ""


def row_to_lead(row, search_query="", location=""):
    opening_hours = row.get("opening_hours", "")
    if isinstance(opening_hours, str) and opening_hours:
        try:
            opening_hours = json.loads(opening_hours)
        except Exception:
            opening_hours = [opening_hours]
    elif not isinstance(opening_hours, list):
        opening_hours = []

    return {
        "name": str(row.get("name", "")),
        "address": str(row.get("address", "")),
        "website": str(row.get("website", "")),
        "phone": str(row.get("phone", "")),
        "description": str(row.get("description", "")),
        "rating": float(row["rating"]) if str(row.get("rating", "")).replace(".", "", 1).isdigit() else None,
        "reviews": int(row["reviews"]) if str(row.get("reviews", "")).isdigit() else None,
        "category": str(row.get("category", "")),
        "keywords": str(row.get("keywords", "")),
        "price_level": str(row.get("price_level", "")),
        "opening_hours": opening_hours,
        "email": str(row.get("email", "")),
        "facebook": str(row.get("facebook", "")),
        "twitter": str(row.get("twitter", "")),
        "instagram": str(row.get("instagram", "")),
        "contact": str(row.get("contact", "")),
        "search_query": search_query,
        "location": location,
        "searched": str(row.get("searched", "NO")),
    }


def save_lead(row, search_query, location):
    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
    payload = row_to_lead(row, search_query, location)
    try:
        resp = requests.post(
            f"{base_url}/api/leads",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=10,
        )
        return resp.status_code in (200, 201), resp
    except Exception as e:
        return False, str(e)


def save_leads_batch(rows, search_query, location):
    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
    payload = {"leads": [row_to_lead(r, search_query, location) for r in rows]}
    try:
        resp = requests.post(
            f"{base_url}/api/leads/batch",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30,
        )
        return resp.status_code in (200, 201), resp
    except Exception as e:
        return False, str(e)


async def main_with_progress(location, search_query, num_pages):
    status = st.empty()

    status.text("Getting coordinates for location...")
    coords = get_coordinates(location)
    if not coords:
        st.error("Could not get coordinates for the location. Please check the location name and try again.")
        return None

    status.text("Searching for businesses using Serper Maps API...")
    places_data = search_places(search_query, coords, num_pages)
    if not places_data:
        st.error("No places found. Try a different search query or location.")
        return None

    status.text("Saving initial data to Excel...")
    excel_filename = f"data_{search_query}_{location}_{get_current_date()}.xlsx"
    file_path = save_places_to_excel(places_data, excel_filename)

    status.text("Processing businesses to extract detailed information...")
    progress_bar = st.progress(0)
    progress_text = st.empty()

    async def progress_callback(total, current, business_name):
        progress_bar.progress((current + 1) / total)
        progress_text.text(f"Processing: {current + 1}/{total} - {business_name}")

    await process_businesses(file_path, progress_callback=progress_callback)

    status.text("Lead generation complete!")
    return file_path


# Main execution logic
if submit_button:
    if not os.environ.get("SERPER_API_KEY") or not os.environ.get("OPENROUTER_API_KEY"):
        st.error("Please set your API keys in the sidebar before starting.")
    else:
        with st.spinner("Starting lead generation..."):
            excel_path = asyncio.run(main_with_progress(location, search_query, num_pages))
            if excel_path:
                st.session_state.excel_path = excel_path
                st.session_state.last_search_query = search_query
                st.session_state.last_location = location

# Results section - Always check if the file exists
if st.session_state.excel_path and os.path.exists(st.session_state.excel_path):
    st.subheader("Results")

    try:
        df = pd.read_excel(st.session_state.excel_path)

        if not df.empty:
            saved_query = st.session_state.get("last_search_query", "")
            saved_location = st.session_state.get("last_location", "")

            st.write(f"Found {len(df)} businesses:")

            # Selectable table — prepend a checkbox column
            df_display = df.copy()
            df_display.insert(0, "Save", False)
            edited = st.data_editor(df_display, use_container_width=True, hide_index=True, key="results_editor")

            selected_rows = edited[edited["Save"] == True].drop(columns=["Save"])

            col_dl, col_save_sel, col_save_all, col_clear = st.columns([2, 2, 2, 2])

            # Download button
            with col_dl:
                with open(st.session_state.excel_path, "rb") as excel_file:
                    excel_bytes = excel_file.read()
                st.download_button(
                    label="Download Excel",
                    data=excel_bytes,
                    file_name=os.path.basename(st.session_state.excel_path),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    icon=":material/download:",
                    key="download_button",
                )

            # Save selected rows
            with col_save_sel:
                save_selected = st.button(
                    f"Save Selected ({len(selected_rows)})",
                    icon=":material/playlist_add_check:",
                    disabled=len(selected_rows) == 0,
                    key="save_selected_btn",
                )

            # Save all rows
            with col_save_all:
                save_all = st.button(
                    "Save All to Database",
                    icon=":material/cloud_upload:",
                    key="save_all_btn",
                )

            # Clear results
            with col_clear:
                if st.button(
                    "Clear Results",
                    icon=":material/delete_sweep:",
                    key="clear_btn",
                ):
                    st.session_state.excel_path = None
                    st.session_state.last_search_query = ""
                    st.session_state.last_location = ""
                    st.rerun()

            if save_selected and len(selected_rows) > 0:
                with st.spinner(f"Saving {len(selected_rows)} lead(s) to database..."):
                    if len(selected_rows) == 1:
                        row = selected_rows.iloc[0].to_dict()
                        ok, resp = save_lead(row, saved_query, saved_location)
                        if ok:
                            st.success("Lead saved to database.")
                        else:
                            st.error(f"Failed to save lead: {resp}")
                    else:
                        rows = [selected_rows.iloc[i].to_dict() for i in range(len(selected_rows))]
                        ok, resp = save_leads_batch(rows, saved_query, saved_location)
                        if ok:
                            st.success(f"{len(rows)} leads saved to database.")
                        else:
                            st.error(f"Batch save failed: {resp}")

            if save_all:
                with st.spinner(f"Saving all {len(df)} leads to database..."):
                    rows = [df.iloc[i].to_dict() for i in range(len(df))]
                    ok, resp = save_leads_batch(rows, saved_query, saved_location)
                    if ok:
                        st.success(f"All {len(rows)} leads saved to database.")
                    else:
                        st.error(f"Batch save failed: {resp}")

    except Exception as e:
        st.error(f"Error displaying results: {e}")
        st.write(f"You can find your file at: {st.session_state.excel_path}")
