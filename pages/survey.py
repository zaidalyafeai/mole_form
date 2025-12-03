import streamlit as st  # ignore
import requests
import json
import os
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

st.set_page_config(initial_sidebar_state="collapsed")

load_dotenv()
import requests
DATASETS_URL = "https://web-production-25a2.up.railway.app/datasets?features=Name,Paper Title,Paper Link"


st.set_page_config(
    page_title="Masader Survey",
    page_icon="📮",
    initial_sidebar_state="collapsed",
    layout="wide",
)
"# 📮 :rainbow[Masader Survey]"


try:
    response = requests.get(DATASETS_URL)
    if response.status_code == 200:
        datasets = response.json()
except Exception as e:
    print("Error:", str(e))


st.set_page_config(
    page_title="Masader Survey",
    page_icon="📮",
    initial_sidebar_state="collapsed",
    layout="wide",
)

@st.fragment
def search_datasets():
    """Quick search for existing datasets without form submission."""
    st.text("Search Masader Catalouge")
    st.caption("Use the search bar to find datasets in the Masader Catalouge, Use the name of the dataset for example cidar.")
    data_options = [dataset.get("Name").lower().strip() for dataset in datasets]
    data_options = sorted(data_options)
    data_options = [""] + data_options
    selected = st.selectbox(
        "",
        options=data_options,
        key="dataset_search",
        label_visibility="collapsed",
        placeholder="Search datasets..."
    )
    if selected:
        selected_dataset = [dataset for dataset in datasets if dataset.get("Name").lower().strip() == selected][0]
        st.write(f"Paper Title: {selected_dataset['Paper Title']}")
        st.write(f"Paper Link: {selected_dataset['Paper Link']}")

@st.fragment
def submit_to_google_sheets(data, sheet_name="Masader Survey", worksheet_name="Sheet1"):
    """
    Submit form data to Google Sheets
    
    Args:
        data (dict): Dictionary containing form data
        sheet_name (str): Name of the Google Sheet
        worksheet_name (str): Name of the worksheet within the sheet
        
    Returns:
        bool: True if submission was successful, False otherwise
    """
    # Load credentials from environment variable
    creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")
    if not creds_json:
        st.error("Google Sheets credentials not found in environment variables.")
        return False
        
    # Parse the JSON string
    creds_dict = json.loads(creds_json)
    
    # Authenticate with Google Sheets API
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    # Open the Google Sheet
    sheet = client.open(sheet_name).worksheet(worksheet_name)
    # Get headers (first row)
    headers = sheet.row_values(1)
    
    # Prepare data row
    row = []
    for header in headers:
        # Convert header back to original key format if needed
        key = header.lower().replace(' ', '_')
        row.append(str(data.get(key, '')))
    
    # Add new row
    sheet.append_row(row)
    return True        


def main():
    st.info(
        """
    This survey is to collect information about how many datasets we are missing from the [Masader](https://arbml.github.io/masader) catalogue.
    The results of this survey may be used for research purposes.
    """,
    )
    
    # Initialize session state for form submission status
    if 'submitting' not in st.session_state:
        st.session_state.submitting = False
    
    search_datasets()
    st.divider()
    # Search existing datasets
    with st.form(key="dataset_form", border=False):
        # Disable form fields if submitting
        disabled = st.session_state.get('submitting', False)
        job_title = st.selectbox(
            "What is your job title?", 
            ['', 'Student', 'Postdoc', 'Researcher', 'Professor', 'Other'], 
            disabled=disabled
        )
        num_datasets = st.selectbox(
            "How many Arabic datasets you published in your career?", 
            ['0', '1', '2', '3', '+5'], 
            disabled=disabled
        )
        st.markdown(
    "<p style='font-size:15px;'>Do you know any Arabic datasets that don't exist in the catalogue?</p>",
    unsafe_allow_html=True
)
        st.caption("Use the search bar above to find datasets in the Masader Catalouge")
        existing = st.checkbox("Yes", disabled=disabled)
        non_existing_datasets = st.text_area(
            "Please list the datasets that you published and don't exist in the catalogue in the following format, Paper Title, Dataset Link",
            disabled=disabled
        )
        
        submit = st.form_submit_button(
            "Submit", 
            disabled=disabled,
            on_click=lambda: setattr(st.session_state, 'submitting', True)
        )
    
    # Handle form submission
    if submit:
        with st.spinner('Submitting your response...'):
            try:
                submit_to_google_sheets({
                    "time": datetime.now(), 
                    "num_datasets": num_datasets,
                    "existing": existing, 
                    "job_title": job_title,
                    "non_existing_datasets": non_existing_datasets
                })
                st.success("Thank you for your submission!")
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
            finally:
                # Reset submission state
                st.session_state.submitting = False
                st.rerun()  # Rerun to update the form state


if __name__ == "__main__":
    main()
