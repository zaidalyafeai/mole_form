import streamlit as st
import requests
import re
import json
import os
import subprocess
from github import Github
from git import Repo
from datetime import date
from constants import *

from dotenv import load_dotenv

MASADER_BOT_URL = 'https://masaderbot-production.up.railway.app/run'

st.set_page_config(
    page_title="Masader Form", page_icon="📮", initial_sidebar_state="collapsed",
)
"# 📮 :rainbow[Masader Form]"
load_dotenv()  # Load environment variables from a .env file

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def validate_github(username):
    response = requests.get(f"https://api.github.com/users/{username}")
    if response.status_code == 200:
        return True
    else:
        return False
        
def validate_url(url):
    try:
        response = requests.head(url, allow_redirects=True, timeout=5)
        if response.status_code == 200:
            return True
        else:
            return False
    except requests.ConnectionError:
        return False

def validate_comma_separated_number(number: str) -> bool:
    """
    Validates a number with commas separating thousands.
    
    Args:
        number (str): The number as a string.
        
    Returns:
        bool: True if valid, False otherwise.
    """
    # Regular expression pattern to match numbers with comma-separated thousands
    pattern = r'^\d{1,3}(,\d{3})*$'
    
    # Match the pattern
    return bool(re.fullmatch(pattern, number))

def update_session_config(json_data):
    for key in json_data:
        if key in ['Year']:
            try:
                st.session_state[key] = int(json_data[key])
            except:
                st.session_state[key] = 2024
        elif key in ['Collection Style', 'Domain']:
            st.session_state[key] = [val.strip() for val in json_data[key].split(',')]
        elif key == 'Tasks':
            tasks = []
            other_tasks = []
            for task in [task.strip() for task in json_data[key].split(',')]:
                if task not in column_options['Tasks'].split(','):
                    other_tasks.append(task)
                else:
                    tasks.append(task)
            
            if len(other_tasks):
                st.session_state['Other Tasks'] = ','.join(other_tasks)
                tasks.append('other')
            
            if len(tasks):
                st.session_state['Tasks'] = tasks

        elif key == 'Subsets':
            for i,subset in enumerate(json_data[key]):
                for subkey in subset:
                    st.session_state[f'subset_{i}_{subkey.lower()}'] = json_data[key][i][subkey]
        else:
            st.session_state[key] = json_data[key].strip()
            
def reload_config(json_data):
    if 'metadata' in json_data:
        json_data = json_data['metadata']
    update_session_config(json_data)


def render_form():
    i = 0
    
    while True:
        col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
        with col1:
            name = st.text_input("Name:", key=f"subset_{i}_name")
        with col3:
            volume = st.text_input("Volume", key=f"subset_{i}_volume")
        with col2:
            dialect = st.selectbox(
                "Dialect", 
                column_options['Dialect'].split(','), 
                key=f"subset_{i}_dialect"
            )
        with col4:
            unit = st.selectbox(
                "Unit", 
                column_options['Unit'].split(','), 
                key=f"subset_{i}_unit"
            )
        if name:
            i += 1
        else:
            break
        
    
def update_pr(new_dataset):

    # Configuration
    REPO_NAME = "ARBML/masader"  # Format: "owner/repo"
    BRANCH_NAME = "add-new-dataset"
    PR_TITLE = f"Adding {new_dataset['Name']} to the catalogue"
    PR_BODY = f"This is a pull request by @{st.session_state.gh_username} to add a new dataset to the catalogue."

    # Initialize GitHub client
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)

    # Clone repository
    repo_url = f"https://{GITHUB_TOKEN}@github.com/{REPO_NAME}.git"
    local_path = "./temp_repo"
    if os.path.exists(local_path):
        subprocess.run(["rm", "-rf", local_path])  # Clean up if exists
    Repo.clone_from(repo_url, local_path)

    # Modify file
    local_repo = Repo(local_path)
    
    data_name = new_dataset['Name'].lower().strip()
    for symbol in [' ', '/', '\\', ':', '*', '?', '"', '<', '>', '|', '.']:
        data_name = data_name.replace(symbol, '_')

    FILE_PATH = f'datasets/{data_name}.json'
    with open(f'{local_path}/{FILE_PATH}', "w") as f:
        json.dump(new_dataset, f, indent=4)

    # Create a new branch
    local_repo.git.checkout("-b", BRANCH_NAME)
    local_repo.git.pull("origin", 'main')

    # Commit and push changes
    local_repo.git.add(FILE_PATH)
    local_repo.git.commit("-m", "Update data.json")
    local_repo.git.push("--set-upstream", "origin", BRANCH_NAME)

    # Create a pull request
    pr = repo.create_pull(
        title=PR_TITLE,
        body=PR_BODY,
        head=BRANCH_NAME,
        base=repo.default_branch,
    )

    st.success(f"Pull request created: {pr.html_url}")
    st.balloons()

def load_json(url, link = '', pdf = None):
    # Make the GET request to fetch the JSON data
    if link != '':
        response = requests.post(url, data = {'link':link})
    elif pdf:
        response = requests.post(url, files = {'file':pdf})
    else:
        response = requests.get(url)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the JSON content
        json_data = response.json()
        reload_config(json_data)
        return True
    else:
        st.error(response.text)
    return False

def reset_config():
        with open("default.json", "r") as f:
            reload_config(json.load(f))
        
        if 'reload' not in st.session_state:
            st.session_state.reload = True
        else:
            st.session_state.reload = True
    
@st.fragment()
def final_state():
    col1, col2 = st.columns(2)

    with col1:
        submit = st.form_submit_button("Submit")
    with col2:
        save   = st.form_submit_button("Save")

    if submit or save:
        if not validate_github(st.session_state['gh_username'].strip()):
            st.error("Please enter a valid GitHub username.")
        elif not st.session_state['Name'].strip():
            st.error("Please enter a valid dataset name.")
        elif not validate_url(st.session_state['Link']):
            st.error("Please enter a valid repository link.")
        elif not st.session_state['License'].strip():
            st.error("Please select a valid license.")
        elif not st.session_state['Dialect']:
            st.error("Please enter a valid dialect.")
        elif not st.session_state['Domain']:
            st.error("Please select a valid domain.")
        elif not st.session_state['Collection Style']:
            st.error("Please select a valid collection style")
        elif not st.session_state['Description'].strip() or len(st.session_state['Description']) < 10:
            st.error("Please enter a non empty (detailed) description of the dataset")
        elif not validate_comma_separated_number(st.session_state['Volume'].strip()):
            st.error("Please enter a valid volume. for example 1,000")
        elif not st.session_state['Unit'].strip():
            st.error("Please select a valid unit.")
        elif not st.session_state['Host'].strip():
            st.error("Please select a valid host.")
        elif not st.session_state['Tasks']:
            st.error("Please select the Tasks.")
        elif 'other' in st.session_state['Tasks'] and len(st.session_state['Other Tasks'].split(','))< 0:
            st.error("Please enter other tasks.")
        elif not st.session_state['Added By'].strip():
            st.error("Please enter your full name.")
        else:
            config = create_json()
            if submit:
                update_pr(config)
            else:
                save_path = st.text_input("Save Path", value=f"/Users/zaidalyafeai/Documents/Development/masader_bot/testset/{st.session_state['Name'].lower()}.json", help="Enter the directory path to save the JSON file")
                if save_path:
                    with open(save_path, "w") as f:
                        json.dump(config, f, indent=4)
                    st.success(f"Form saved successfully to {save_path}")

def create_json():
    config = {}
    columns = ['Name', 'Subsets', 'HF Link', 'Link', 'License', 'Year', 'Language', 'Dialect', 'Domain', 'Form', 'Collection Style', 'Description', 'Volume', 'Unit', 'Ethical Risks', 'Provider', 'Derived From', 'Paper Title', 'Paper Link', 'Script', 'Tokenized', 'Host', 'Access', 'Cost', 'Test Split', 'Tasks', 'Venue Title', 'Citations', 'Venue Type', 'Venue Name', 'Authors', 'Affiliations', 'Abstract', 'Added By']
    for key in columns:
        if key == 'Subsets':
            config['Subsets'] = []
            i = 0
            while True:
                subset = {}
                if f'subset_{i}_name' in st.session_state:
                    if st.session_state[f'subset_{i}_name'] != "":
                        subset['Name'] = st.session_state[f'subset_{i}_name']
                        subset['Volume'] = st.session_state[f'subset_{i}_volume']
                        subset['Dialect'] = st.session_state[f'subset_{i}_dialect']
                        subset['Unit'] = st.session_state[f'subset_{i}_unit']
                        config['Subsets'].append(subset)
                        i += 1
                        continue
                break
        elif key in ['Collection Style', 'Domain']:
            config[key] = ','.join(st.session_state[key])
        elif key == 'Tasks':
            if 'other' in st.session_state[key]:
                tasks = st.session_state[key]
                tasks.remove('other')
                tasks+= st.session_state['Other Tasks'].split(',')
                config[key] = ','.join(tasks)
            else:
                config[key] = ','.join(st.session_state[key])
        else:
            config[key] = st.session_state[key]
    return config
    

def main():

    if "config" not in st.session_state:
        reset_config()

    st.info(
    """
    This is a the Masader form to add datasets to [Masader](https://arbml.github.io/masader/) catalogue.
    Before starting, please make sure you have the following information:
    - Check the dataset does not exist in the catelouge using the search [Masader](https://arbml.github.io/masader/search)
    - You have a valid GitHub username
    - You have the direct link to the dataset repository

    Once you submit the dataset, we will send a PR, make sure you follow up there if you have any questions. 
    If you have face any issues post them on [GitHub](https://github.com/arbml/masader/issues).
    """,
    icon="👾",
)       
    if st.query_params:
        if st.query_params['json_url']:
            load_json(st.query_params['json_url'])
        
    options = st.selectbox("Annotation Options", ["💪🏻 Manual Annotation", "🤖 AI Annotation", "🚥 Load Annotation"], on_change = reset_config)


    if options == "🚥 Load Annotation":
        upload_file = st.file_uploader("Upload Json", help = "You can use this widget to preload any dataset from https://github.com/ARBML/masader/tree/main/datasets")
        json_url = st.text_input("Path to json", placeholder = 'For example: https://raw.githubusercontent.com/ARBML/masader_form/refs/heads/main/shami.json')

        if upload_file:
            json_data = json.load(upload_file)
            reload_config(json_data)
            st.session_state.reload  = False
        elif json_url:
            load_json(json_url)
            st.session_state.reload  = False
        else:
            reset_config()

    elif options == "🤖 AI Annotation":
        paper_url = st.text_input("Insert arXiv or direct pdf link")
        upload_pdf = st.file_uploader("Upload PDF of the paper", help = "You can use this widget to preload any dataset from https://github.com/ARBML/masader/tree/main/datasets")

        if paper_url:
            if 'arxiv' in paper_url and st.session_state.reload:
                if load_json(MASADER_BOT_URL, link=paper_url):
                    st.session_state.reload = False
            else:
                response = requests.get(paper_url)
                response.raise_for_status()  # Raise an error for bad responses (e.g., 404)
                if response.headers.get("Content-Type") == "application/pdf":
                    pdf = (paper_url.split("/")[-1], response.content, response.headers.get('Content-Type', 'application/pdf'))
                    if load_json(MASADER_BOT_URL, pdf=pdf):
                        st.session_state.reload = False  
                else:
                    st.error(f'Cannot retrieve a pdf from the link. Make sure {paper_url} is a direct link to a valid pdf')
                # Extract PDF details                             

        elif upload_pdf:
            # Prepare the file for sending
            pdf = (upload_pdf.name, upload_pdf.getvalue(), upload_pdf.type)
            if load_json(MASADER_BOT_URL, pdf = pdf):
                st.session_state.reload = False
    else:
        st.session_state.reload = False
    
    if not st.session_state.reload :         
        with st.form(key="dataset_form"):
            username = st.text_input("GitHub username*", key = 'gh_username', value = 'zaidalyafeai')
            
            dataset_name = st.text_input("Name of the dataset*", 
                                        help="For example CALLHOME: Egyptian Arabic Speech Translation Corpus",
                                        key = "Name")
            

            # Subsets
            st.markdown("The different subsets in the dataset if it is broken by dialects.")
            render_form()    
            
            # Links
            repo_link = st.text_input("Direct link to the dataset repository*", key = "Link")

            huggingface_link = st.text_input("Huggingface Link", 
                                            help="for example https://huggingface.co/datasets/labr",
                                            key = "HF Link")
            

            # Dataset Properties
            license_type = st.selectbox("License*", 
                                        column_options['License'].split(','), key = "License")
            
            current_year = date.today().year
            year = st.number_input("Year*", 
                                    min_value=2000, 
                                    max_value=current_year,
                                    help="Year of publishing the dataset/paper",
                                    key = 'Year')

            language = st.radio("Language*", ["ar", "multilingual"], key = 'Language')

            dialect = st.selectbox("Dialect*",
                                    column_options['Dialect'].split(','),
                                    help="Used mixed if the dataset contains multiple dialects",
                                    key = 'Dialect')

            domain = st.multiselect("Domain*",
                                column_options['Domain'].split(','), key = 'Domain')
            
            form_type = st.radio("Form*", column_options['Form'].split(','), key ='Form')

            collection_style = st.multiselect("Collection Style*",
                                        column_options['Collection Style'].split(','),
                                        key = 'Collection Style')

            description = st.text_area("Description*", 
                                        help="brief description of the dataset",
                                        key = 'Description')

            # Volume and Units
            volume = st.text_input("Volume*", 
                                    help="How many samples are in the dataset. Please don't use abbreviations like 10K",
                                    key = 'Volume')
            
            unit = st.radio("Unit*", 
                            column_options['Unit'].split(','),
                            help="tokens usually used for ner, pos tagging, etc. sentences for sentiment analysis, documents for text modelling tasks",
                            key = 'Unit')

            ethical_risks = st.radio("Ethical Risks",
                                    column_options['Ethical Risks'].split(','),
                                    help="social media datasets are considered mid risks as they might release personal information, others might contain hate speech as well so considered as high risk",
                                    key = 'Ethical Risks')        

            provider = st.text_input("Provider", 
                                    placeholder="Name of institution i.e. NYU Abu Dhabi", key = 'Provider')
            
            derived_from = st.text_input("Derived From",
                                        placeholder="If the dataset is extracted or collected from another dataset",
                                        key = 'Derived From')
            # Paper Information
            paper_title = st.text_input("Paper Title", key = 'Paper Title')

            paper_link = st.text_input("Paper Link",
                                        placeholder="Direct link to the pdf of the paper i.e. https://arxiv.org/pdf/2110.06744.pdf",
                                        key = 'Paper Link')

            # Technical Details
            script = st.radio("Script*", column_options['Script'].split(','), key='Script')

            tokenized = st.radio("Tokenized*", 
                                column_options['Tokenized'].split(','),
                                help="Is the dataset tokenized i.e. الرجل = ال رجل", key='Tokenized')

            host = st.selectbox("Host*",
                                column_options['Host'].split(','),
                                help="Where the data resides", key='Host')

            access = st.radio("Access*",
                            column_options['Access'].split(','), key='Access')
            cost = ''
            if access == "With-Fee":
                cost = st.text_input("Cost", 
                                    help="For example 1750 $", key='Cost')
            
            test_split = st.radio("Test split*",
                                column_options['Test Split'].split(','),
                                help="Does the dataset have validation / test split", key='Test Split')

            tasks = st.multiselect("Tasks*",
                                column_options['Tasks'].split(','),
                                key = 'Tasks')
            if 'other' in tasks:
                other_tasks = st.text_input("Other Tasks*", placeholder = "Enter other tasks separated by comma", help= "Make sure the tasks don't appear in the Tasks field", key = 'Other Tasks')
                tasks+= other_tasks.split(',')

            no_other_tasks = []
            for task in tasks:
                if task != 'other':
                    no_other_tasks.append(task)

            venue_title = st.text_input("Venue Title", placeholder="Venue shortcut i.e. ACL", key='Venue Title')

            # Venue Type
            venue_type = st.radio(
                "Venue Type",
                options=column_options['Venue Type'].split(','),
                help="Select the type of venue", key='Venue Type'
            )
            # Venue Name
            venue_name = st.text_input(
                "Venue Name",
                placeholder="Full name i.e. Association of Computational Linguistics",
                key='Venue Name'
            )

            # Authors
            authors = st.text_area(
                "Authors",
                placeholder="Add all authors split by comma"
                ,key='Authors'
            )

            # Affiliations
            affiliations = st.text_area(
                "Affiliations",
                placeholder="Enter affiliations", key='Affiliations'
            )

            # Abstract
            abstract = st.text_area(
                "Abstract",
                placeholder="Abstract of the published paper",
                key='Abstract'
            )

            added_by = st.text_input(
                "Full Name*",
                placeholder="Please Enter your full name",
                key='Added By'
            )
            final_state()

if __name__ == "__main__":
    main()