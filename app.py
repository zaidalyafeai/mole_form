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

def update_session_config():
    for key in st.session_state.config:
        if key in ['Year']:
            st.session_state[key] = int(st.session_state.config[key])
        elif key in ['Tasks', 'Collection Style', 'Domain']:
            st.session_state[key] = [val.strip() for val in st.session_state.config[key].split(',')]
        elif key == 'Subsets':
            for i,subset in enumerate(st.session_state.config[key]):
                for subkey in subset:
                    st.session_state[f'{subkey}_{i}'] = st.session_state.config[key][i][subkey]
        else:
            st.session_state[key] = st.session_state.config[key].strip()
            
def reload_config(json_data):
    if 'metadata' in json_data:
        json_data = json_data['metadata']
    st.session_state.config = json_data
    update_session_config()

if 'Subsets' not in st.session_state:
    st.session_state.Subsets = []

def render_form():
    i = 0
    subsets = [] 
    while True:
        col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
        with col1:
            name = st.text_input("Name:", key=f"Name_{i}")
        with col3:
            volume = st.text_input("Volume", key=f"Volume_{i}")
        with col2:
            dialect = st.selectbox(
                "Dialect", 
                column_options['Dialect'].split(','), 
                key=f"Dialect_{i}"
            )
        with col4:
            unit = st.selectbox(
                "Unit", 
                column_options['Unit'].split(','), 
                key=f"Unit_{i}"
            )
        if name:
            i += 1
            subsets.append({f'Name':name, f'Dialect':dialect, f'Volume':volume, f'Unit':unit})
        else:
            st.session_state.config['Subsets']= subsets
            break
        
    
def update_pr(new_dataset):

    # Configuration
    REPO_NAME = "ARBML/masader"  # Format: "owner/repo"
    BRANCH_NAME = "add-new-dataset"
    PR_TITLE = f"Adding {new_dataset['Name']} to the catalogue"
    PR_BODY = f"This is a pull request by @{new_dataset['Added By']} to add a new dataset to the catalogue."

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

def load_json(json_url):
    # Make the GET request to fetch the JSON data
    response = requests.get(json_url)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the JSON content
        json_data = response.json()
        reload_config(json_data)
    else:
        st.error('failed to load json')

def main():

    if "config" not in st.session_state:
        with open("default.json", "r") as f:
            st.session_state.config = json.load(f)

    if "uploaded_file" not in st.session_state:
        st.session_state.uploaded_file = False

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
    on = st.toggle("Use external Jsons", help = "Use this option to load an external json file or url")
    if st.query_params:
        if st.query_params['json_url']:
            load_json(st.query_params['json_url'])

    if on:
        uploaded_file = st.file_uploader("", help = "You can use this widget to preload any dataset from https://github.com/ARBML/masader/tree/main/datasets")

        if not st.session_state.uploaded_file:
            if uploaded_file:
                json_data = json.load(uploaded_file)
                reload_config(json_data)
                st.session_state.uploaded_file = True
        json_url = st.text_input("path to json")

        if json_url:
            load_json(json_url)

    # Input for GitHub username with reactive search
    username = st.text_input("GitHub username*", key = 'Added By')
    st.session_state.config["Added By"] = username
    
    dataset_name = st.text_input("Name of the dataset*", 
                                help="For example CALLHOME: Egyptian Arabic Speech Translation Corpus",
                                key = "Name")
    
    st.session_state.config["Name"] = dataset_name

    # Subsets
    st.markdown("The different subsets in the dataset if it is broken by dialects.")
    render_form()    
    
    # Links
    repo_link = st.text_input("Direct link to the dataset repository*", key = "Link")
    st.session_state.config["Link"] = repo_link

    huggingface_link = st.text_input("Huggingface Link", 
                                    help="for example https://huggingface.co/datasets/labr",
                                    key = "HF Link")
    
    st.session_state.config["HF Link"] = huggingface_link

    # Dataset Properties
    license_type = st.selectbox("License*", 
                                column_options['License'].split(','), key = "License")
    
    st.session_state.config["License"] = license_type
    current_year = date.today().year
    year = st.number_input("Year*", 
                            min_value=2000, 
                            max_value=current_year,
                            value = current_year,
                            help="Year of publishing the dataset/paper",
                            key = 'Year')
    st.session_state.config["Year"] = year

    language = st.radio("Language*", ["ar", "multilingual"], key = 'Language')
    st.session_state.config["Language"] = language

    dialect = st.selectbox("Dialect*",
                            column_options['Dialect'].split(','),
                            help="Used mixed if the dataset contains multiple dialects",
                            key = 'Dialect')
    st.session_state.config["Dialect"] = dialect

    domain = st.multiselect("Domain*",
                        column_options['Domain'].split(','), key = 'Domain')
    st.session_state.config["Domain"] = ','.join(domain)
    
    form_type = st.radio("Form*", column_options['Form'].split(','), key ='Form')
    st.session_state.config["Form"] = form_type

    collection_style = st.multiselect("Collection Style*",
                                column_options['Collection Style'].split(','),
                                key = '"Collection Style"')
    st.session_state.config["Collection Style"] = ','.join(collection_style)

    description = st.text_area("Description*", 
                                help="brief description of the dataset",
                                key = 'Description')
    st.session_state.config["Description"] = description

    # Volume and Units
    volume = st.text_input("Volume*", 
                            help="How many samples are in the dataset. Please don't use abbreviations like 10K",
                            key = 'Volume')
    st.session_state.config["Volume"] = volume
    
    unit = st.radio("Unit*", 
                    column_options['Unit'].split(','),
                    help="tokens usually used for ner, pos tagging, etc. sentences for sentiment analysis, documents for text modelling tasks",
                    key = 'Unit')
    st.session_state.config["Unit"] = unit

    ethical_risks = st.radio("Ethical Risks",
                            column_options['Ethical Risks'].split(','),
                            help="social media datasets are considered mid risks as they might release personal information, others might contain hate speech as well so considered as high risk",
                            key = 'Ethical Risks')        
    st.session_state.config["Ethical Risks"] = ethical_risks

    provider = st.text_input("Provider", 
                            placeholder="Name of institution i.e. NYU Abu Dhabi", key = 'Provider')
    st.session_state.config["Provider"] = provider
    
    derived_from = st.text_input("Derived From",
                                placeholder="If the dataset is extracted or collected from another dataset",
                                key = 'Derived From')
    st.session_state.config["Derived From"] = derived_from
    # Paper Information
    paper_title = st.text_input("Paper Title", key = 'Paper Title')
    st.session_state.config["Paper Title"] = paper_title

    paper_link = st.text_input("Paper Link",
                                placeholder="Direct link to the pdf of the paper i.e. https://arxiv.org/pdf/2110.06744.pdf",
                                key = 'Paper Link')
    st.session_state.config["Paper Link"] = paper_link

    # Technical Details
    script = st.radio("Script*", column_options['Script'].split(','), key='Script')
    st.session_state.config["Script"] = script

    tokenized = st.radio("Tokenized*", 
                        column_options['Tokenized'].split(','),
                        help="Is the dataset tokenized i.e. الرجل = ال رجل", key='Tokenized')
    st.session_state.config["Tokenized"] = tokenized

    host = st.selectbox("Host*",
                        column_options['Host'].split(','),
                        help="Where the data resides", key='Host')
    st.session_state.config["Host"] = host

    access = st.radio("Access*",
                    column_options['Access'].split(','), key='Access')
    st.session_state.config["Access"] = access
    cost = ''
    if access == "With-Fee":
        cost = st.text_input("Cost", 
                            help="For example 1750 $", key='Cost')
        st.session_state.config["Cost"] = cost
    
    test_split = st.radio("Test split*",
                        column_options['Test Split'].split(','),
                        help="Does the dataset have validation / test split", key='Test Split')
    st.session_state.config["Test Split"] = test_split        

    tasks = st.multiselect("Tasks*",
                        column_options['Tasks'].split(','),
                        key = 'Tasks')
    if 'other' in tasks:
        other_tasks = st.text_input("Other Tasks*", placeholder = "Enter other tasks separated by comma", help= "Make sure the tasks don't appear in the Tasks field")
        tasks+= other_tasks.split(',')

    no_other_tasks = []
    for task in tasks:
        if task != 'other':
            no_other_tasks.append(task)
    st.session_state.config["Tasks"] = ','.join(no_other_tasks)

    venue_title = st.text_input("Venue Title", placeholder="Venue shortcut i.e. ACL", key='Venue Title')
    st.session_state.config["Venue Title"] = venue_title
    # Venue Type
    venue_type = st.radio(
        "Venue Type",
        options=column_options['Venue Type'].split(','),
        help="Select the type of venue", key='Venue Type'
    )
    st.session_state.config["Venue Type"] = venue_type
    # Venue Name
    venue_name = st.text_input(
        "Venue Name",
        placeholder="Full name i.e. Association of Computational Linguistics",
        key='Venue Name'
    )
    st.session_state.config["Venue Name"] = venue_name

    # Authors
    authors = st.text_area(
        "Authors",
        placeholder="Add all authors split by comma"
        ,key='Authors'
    )
    st.session_state.config["Authors"] = authors

    # Affiliations
    affiliations = st.text_area(
        "Affiliations",
        placeholder="Enter affiliations", key='Affiliations'
    )
    st.session_state.config["Affiliations"] = affiliations

    # Abstract
    abstract = st.text_area(
        "Abstract",
        placeholder="Abstract of the published paper",
        key='Abstract'
    )
    st.session_state.config["Abstract"] = abstract
    submitted = st.button("Submit")

    if submitted:
        if not validate_github(username.strip()):
            st.error("Please enter a valid GitHub username.")
        elif not dataset_name.strip():
            st.error("Please enter a valid dataset name.")
        elif not validate_url(repo_link):
            st.error("Please enter a valid repository link.")
        elif not license_type.strip():
            st.error("Please select a valid license.")
        elif not dialect:
            st.error("Please enter a valid dialect.")
        elif not domain:
            st.error("Please select a valid domain.")
        elif not collection_style:
            st.error("Please select a valid collection style")
        elif not description.strip() or len(description) < 10:
            st.error("Please enter a non empty (detailed) description of the dataset")
        elif not validate_comma_separated_number(volume.strip()):
            st.error("Please enter a valid volume. for example 1,000")
        elif not unit.strip():
            st.error("Please select a valid unit.")
        elif not host.strip():
            st.error("Please select a valid host.")
        elif not tasks:
            st.error("Please select the Tasks.")
        elif 'other' in tasks and not other_tasks.strip():
                st.error("Please enter other tasks.")
        else:
            st.write(st.session_state.config)
        # update_pr(st.session_state.config)        

if __name__ == "__main__":
    main()