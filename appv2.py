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
from streamlit_tags import st_tags
from dotenv import load_dotenv
from streamlit_pdf_viewer import pdf_viewer

MASADER_BOT_URL = "http://0.0.0.0:8080/run"

st.set_page_config(
    page_title="Masader Form",
    page_icon="📮",
    initial_sidebar_state="collapsed",
    layout="wide",
)
"# 📮 :rainbow[Masader Form]"

load_dotenv()  # Load environment variables from a .env file
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GIT_USER_NAME = os.getenv("GIT_USER_NAME")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL")


import requests

def fetch_json_with_token(url: str):
    """
    Fetch a JSON file from a GitHub URL using a personal access token.

    Args:
        url (str): The raw GitHub URL of the JSON file.
        token (str): Your GitHub personal access token.

    Returns:
        dict: Parsed JSON content if successful.
    """
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.raw",
    }

    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()  # Parse the JSON content
    else:
        raise Exception(f"Failed to fetch JSON. Status code: {response.status_code}, Message: {response.text}")

# Example Usage
url = "https://raw.githubusercontent.com/ARBML/masader_bot/main/schema/ar.json"

try:
    input_json = fetch_json_with_token(url)
except Exception as e:
    print("Error:", str(e))

evaluation_subsets = {}
for c in input_json:
    if 'validation_group' in input_json[c]:
        group = input_json[c]['validation_group']
        if group not in evaluation_subsets:
            evaluation_subsets[group] = []
        evaluation_subsets[group].append(c)

validation_columns = []
for c in evaluation_subsets:
    validation_columns += evaluation_subsets[c]

NUM_VALIDATION_COLUMNS = len(validation_columns)

column_types = {}
for c in input_json:
    column_types[c] = input_json[c]['output_type']

required_columns = []
for c in input_json:
    if input_json[c]['required']:
        required_columns.append(c)

columns = list(input_json.keys())
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
    except:
        return False


def validate_dataname(name: str) -> bool:
    """
    Validates the name of the dataset.

    Args:
        name (str): The name of the dataset.

    Returns:
        bool: True if valid, False otherwise.
    """

    for char in name.lower():
        if char not in VALID_SYMP_NAMES:
            st.error(f"Invalid character in the dataset name {char}")
            return False
    return True


def validate_comma_separated_number(number: str) -> bool:
    """
    Validates a number with commas separating thousands.

    Args:
        number (str): The number as a string.

    Returns:
        bool: True if valid, False otherwise.
    """
    # Regular expression pattern to match numbers with comma-separated thousands
    pattern = r"^\d{1,3}(,\d{3})*$"

    # Match the pattern
    return bool(re.fullmatch(pattern, number))


def update_session_config(json_data):
    for column in json_data:
        type = column_types[column]
        if type == "List[str]":
            values = json_data[column]
            st.session_state[column] = values

        elif "List[Dict[" in type:
            subsets = json_data[column]
            keys = type.replace("List[Dict[", "").replace("]]", "").split(",")
            keys = [key.strip() for key in keys]
            i = 0
            nostop = True
            while nostop:
                for key in keys:
                    if f"{column}_{i}_{key}" in st.session_state:
                        del st.session_state[f"{column}_{i}_{key}"]
                    else:
                        nostop = False
                        break
                i += 1
            if len(subsets) > 0:
                for i, subset in enumerate(subsets):
                    for subkey in subset:
                        st.session_state[f"{column}_{i}_{subkey}"] = subset[subkey]
            else:
                for subkey in keys:
                    if subkey in input_json:
                        if 'options' in input_json[subkey]:
                            st.session_state[f"{column}_0_{subkey}"] = input_json[subkey]['options'][-1]
                        else:
                            st.session_state[f"{column}_0_{subkey}"] = ""
        else:
            st.session_state[column] = json_data[column]


def reload_config(json_data):
    if "metadata" in json_data:
        json_data = json_data["metadata"]
    # make sure all the keys exist in the json data

    for key in list(json_data.keys()):
        if key not in columns:
            print('deleting', key)
            del json_data[key]
    print(json_data)
    update_session_config(json_data)
    st.session_state.show_form = True


def render_list_dict(c, type):
    # List[Dict[Name, Volume, Unit, Dialect]]
    type = type.replace("List[Dict[", "")
    type = type.replace("]]", "")
    keys = [key.strip() for key in type.split(",")]
    i = 0

    while True:
        cols = st.columns(len(keys))
        first_elem = None
        for j, subkey in enumerate(keys):
            elem = None
            with cols[j]:
                if subkey in input_json:
                    if 'options' in input_json[subkey]:
                        options = input_json[subkey]['options']
                        elem = st.selectbox(subkey, options=options, key=f"{c}_{i}_{subkey}")
                    else:
                        elem = st.text_input(subkey, key=f"{c}_{i}_{subkey}")
                else:
                    elem = st.text_input(subkey, key=f"{c}_{i}_{subkey}")
            if j == 0:
                first_elem = elem
        if first_elem:
            i += 1
        else:
            break


def update_pr(new_dataset):
    PRS = []
    if os.path.exists("prs.json"):
        with open("prs.json", "r") as f:
            PRS = json.load(f)
    else:
        with open("prs.json", "w") as f:
            json.dump(PRS, f, indent=4)

    # create a valid name for the dataset
    data_name = new_dataset["Name"].lower().strip()
    for symbol in VALID_PUNCT_NAMES:
        data_name = data_name.replace(symbol, "_")

    # Configuration
    REPO_NAME = "ARBML/masader"  # Format: "owner/repo"
    BRANCH_NAME = f"add-{data_name}"
    PR_TITLE = f"Adding {new_dataset['Name']} to the catalogue"
    PR_BODY = f"This is a pull request by @{st.session_state['gh_username']} to add a {new_dataset['Name']} to the catalogue."

    # Initialize GitHub client
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)

    # setup name and email
    os.system(f"git config --global user.email {GIT_USER_EMAIL}")
    os.system(f"git config --global user.name {GIT_USER_NAME}")

    # Clone repository
    repo_url = f"https://{GITHUB_TOKEN}@github.com/{REPO_NAME}.git"
    local_path = "./temp_repo"

    pr_exists = False

    # check the list of Pull Requests
    for pr in PRS:
        pr_obj = repo.get_pull(pr["number"])

        # check the branch if it exists
        if pr["branch"] == BRANCH_NAME:
            print("PR already exists")
            pr_exists = True
        else:
            #  delete unused branches
            if pr["state"] == "open":
                if pr_obj.state == "closed":
                    # repo.get_git_ref(f"heads/{pr['branch']}").delete() # might be risky
                    pr["state"] = "closed"

    if os.path.exists(local_path):
        subprocess.run(["rm", "-rf", local_path])  # Clean up if exists
    Repo.clone_from(repo_url, local_path)

    # Modify file
    local_repo = Repo(local_path)

    FILE_PATH = f"datasets/{data_name}.json"

    # if the branch exists
    if pr_exists:
        local_repo.git.checkout(BRANCH_NAME)
        local_repo.git.pull("origin", BRANCH_NAME)
        with open(f"{local_path}/{FILE_PATH}", "w") as f:
            json.dump(new_dataset, f, indent=4)
        local_repo.git.add(FILE_PATH)
        # check if changes made
        if local_repo.is_dirty():
            local_repo.git.commit("-m", f"Updating {FILE_PATH}")
            local_repo.git.push("origin", BRANCH_NAME)
        else:
            st.info("No changes made to the dataset")
            return
    else:
        with open(f"{local_path}/{FILE_PATH}", "w") as f:
            json.dump(new_dataset, f, indent=4)
        local_repo.git.checkout("-b", BRANCH_NAME)
        local_repo.git.pull("origin", "main")
        # Commit and push changes
        local_repo.git.add(FILE_PATH)
        local_repo.git.commit("-m", f"Creating {FILE_PATH}.json")
        local_repo.git.push("--set-upstream", "origin", BRANCH_NAME)

    # if the PR doesn't exist
    if not pr_exists:
        pr = repo.create_pull(
            title=PR_TITLE,
            body=PR_BODY,
            head=BRANCH_NAME,
            base=repo.default_branch,
        )
        st.success(f"Pull request created: {pr.html_url}")
        # add the pr
        PRS.append(
            {
                "name": new_dataset["Name"],
                "url": pr.html_url,
                "branch": BRANCH_NAME,
                "state": "open",
                "number": pr.number,
            }
        )
    else:
        st.success(f"Pull request updated")

    with open("prs.json", "w") as f:
        json.dump(PRS, f, indent=4)

    st.balloons()


def load_json(url, link="", pdf=None):
    # Make the GET request to fetch the JSON data
    if link != "":
        response = requests.post(url, data={"link": link})
    elif pdf:
        response = requests.post(url, files={"file": pdf})
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

def create_default_json():
    default_json = {}
    for column in columns:
        type = column_types[column]
        if 'options' in input_json[column]:
            if type in ["str"]:
                default_json[column] = input_json[column]['options'][-1]
            elif type == "List[str]":
                default_json[column] = [input_json[column]['options'][-1]]
            else:
                raise()
        elif type == "List[str]": # no options
            default_json[column] = []
        elif "List[Dict" in type:
            default_json[column] = []
        elif type == "date":
            default_json[column] = date.today().year
        elif type == "int":
            default_json[column] = 0
        elif type == "float":
            default_json[column] = 0.0
        else:
            default_json[column] = ""
    return default_json

def reset_config():
    default_json = create_default_json()
    reload_config(default_json)
    st.session_state.show_form = False


@st.fragment()
def final_state():
    col1, col2 = st.columns(2)

    with col1:
        submit = st.form_submit_button("Submit")
    with col2:
        save = st.form_submit_button("Save")

    if submit or save:
        if not validate_github(st.session_state["gh_username"].strip()):
            st.error("Please enter a valid GitHub username.")
        for key in required_columns:
            value = st.session_state[key]
            type  = column_types[key]
            if type in ["List[str]", "List[Dict]"]:
                if len(value) == 0:
                    st.error(f"Please enter a valid {key}.")
                    break
            elif type == "str":
                if value == "":
                    st.error(f"Please enter a valid {key}.")
                    break
            elif type == "url":
                if not validate_url(value):
                    st.error(f"Please enter a valid {key}.")
                    break
            elif type == "int":
                if value == 0:
                    st.error(f"Please enter a valid {key}.")
                    break
            else:
                continue
        else:
            config = create_json(use_annotations_paper = True)
            if submit:
                update_pr(config)
            else:
                save_path = f"/Users/zaidalyafeai/Documents/Development/masader_bot/validset/{st.session_state['Name'].lower()}.json"
                with open(save_path, "w") as f:
                    json.dump(config, f, indent=4)
                st.success(f"Form saved successfully to [{save_path}]({save_path})")


def create_json(use_annotations_paper = False):
    config = {}
    for column in columns:
        type = column_types[column]
        if "List[Dict[" in type:
            config[column] = []
            i = 0
            while True:
                subset = {}
                matched_subsets = [s for s in st.session_state if f"subset_{i}_" in s]
                if len(matched_subsets):
                    for subset_key_name in matched_subsets:
                        subset_name = subset_key_name.split("_")[-1]
                        subset[subset_name] = st.session_state[subset_key_name]
                    config[column].append(subset)
                    i += 1
                else:
                    break
        else:
            config[column] = st.session_state[column]
    if use_annotations_paper:
        config['annotations_from_paper'] = {}
        for column in columns:
            if column in ['Citations', 'Added By']:
                config['annotations_from_paper'][column] = -1
            else:
                config['annotations_from_paper'][column] = 1
    return config


def create_element(label, placeholder="", help="", key="", value="", options=[], type = "str"):
    if label in required_columns:
        st.write(f'{label}*')
    else:
        st.write(label)
    if key in input_json:
        if 'option_description' in input_json[key]:
            desc = ""
            for option in input_json[key]['option_description']:
                desc += f"- **{option}**: {input_json[key]['option_description'][option]}\n"
            if help == "":
                help = desc
    if type in ["int", "float", "date"]:
        st.number_input(key, key=key, label_visibility="collapsed", step = 1, help = help)
    elif (len(options) > 0 and len(options) <= 5) and type == "str":
        st.radio(key, options=options, key=key, label_visibility="collapsed", help = help)
    elif len(options) > 0 and type == "str":
        st.selectbox(key, options=options, key=key, label_visibility="collapsed", help = help)
    elif type == "List[str]":
        if len(options) > 0:
            st.multiselect(key, options=options, key=key, label_visibility="collapsed", help = help)
        else:
            if key not in st.session_state:
                st.session_state[key] = []
            st_tags(
            label = "",
            key=key,
            value=st.session_state[key],  # Bind to session state
            suggestions=options,
        )

    elif "List[Dict[" in type:
        with st.expander(f"Add {key}"):
            st.caption(
                "Use this field to add dialect subsets of the dataset. For example if the dataset has 1,000 sentences in the Yemeni dialect.\
                        For example take a look at the [shami subsets](https://github.com/ARBML/masader/tree/main/datasets/shami.json)."
            )
            render_list_dict(key, type)
    elif key in ["Description", "Abstract"]:
        st.text_area(
            key,
            key=key,
            placeholder=placeholder,
            help=help,
            label_visibility="collapsed",
        )
    elif type in ["str", "url"]:
        st.text_input(
            key,
            key=key,
            placeholder=placeholder,
            help=help,
            value=value,
            label_visibility="collapsed",
        )


def main():
    if 'paper_pdf' not in st.session_state:
        st.session_state['paper_pdf'] = None
    if 'paper_url' not in st.session_state:
        st.session_state['paper_url'] = None
    st.info(
        """
    This is a the Masader form to add datasets to [Masader](https://arbml.github.io/masader/) catalogue.
    Before starting, please make sure you read the following instructions:
    - There are three options
        - 🦚 Manual Annotation: You can have to insert all the metadata manually.
        - 🤖 AI Annotation: Insert the pdf/arxiv link to extract the metadata automatically. 
        - 🚥 Load Annotation: Use this option to load a saved metadata annotation. 
    - Check the dataset does not exist in the catelouge using the search [Masader](https://arbml.github.io/masader/search)
    - You have a valid GitHub username
    - You have the direct link to the dataset repository

    Once you submit the dataset, we will send a PR, make sure you follow up there if you have any questions. 
    If you have face any issues post them on [GitHub](https://github.com/arbml/masader/issues).
    """,
        icon="👾",
    )

    if "show_form" not in st.session_state:
        reset_config()

    if st.query_params:
        if st.query_params["json_url"]:
            load_json(st.query_params["json_url"])

    options = st.selectbox(
        "Annotation Options",
        ["🦚 Manual Annotation", "🤖 AI Annotation", "🚥 Load Annotation"],
        on_change=reset_config,
    )

    if options == "🚥 Load Annotation":
        upload_file = st.file_uploader(
            "Upload Json",
            help="You can use this widget to preload any dataset from https://github.com/ARBML/masader/tree/main/datasets",
        )
        json_url = st.text_input(
            "Path to json",
            placeholder="For example: https://raw.githubusercontent.com/ARBML/masader_form/refs/heads/main/shami.json",
        )

        if upload_file:
            json_data = json.load(upload_file)
            reload_config(json_data)
        elif json_url:
            load_json(json_url)
        else:
            reset_config()

    elif options == "🤖 AI Annotation":
        st.warning(
            "‼️ AI annotation uses LLMs to extract the metadata form papers. However, this approach\
                   is not reliable as LLMs can hellucinate and extract untrustworthy informations. \
                   Make sure you revise the generated metadata before you submit."
        )
        paper_url = st.text_input("Insert arXiv or direct pdf link")
        upload_pdf = st.file_uploader(
            "Upload PDF of the paper",
            help="You can use this widget to preload any dataset from https://github.com/ARBML/masader/tree/main/datasets",
        )

        if paper_url:
            if st.session_state['paper_url'] != paper_url:
                response = requests.get(paper_url)
                paper_pdf = response.content
                st.session_state['paper_url'] = paper_url
                st.session_state['paper_pdf'] = paper_pdf
            if "arxiv" in paper_url:
                load_json(MASADER_BOT_URL, link=paper_url)
            else:
                response = requests.get(paper_url)
                response.raise_for_status()  # Raise an error for bad responses (e.g., 404)
                if response.headers.get("Content-Type") == "application/pdf":
                    pdf = (
                        paper_url.split("/")[-1],
                        response.content,
                        response.headers.get("Content-Type", "application/pdf"),
                    )
                    load_json(MASADER_BOT_URL, pdf=pdf)
                else:
                    st.error(
                        f"Cannot retrieve a pdf from the link. Make sure {paper_url} is a direct link to a valid pdf"
                    )

        elif upload_pdf:
            # Prepare the file for sending
            pdf = (upload_pdf.name, upload_pdf.getvalue(), upload_pdf.type)
            st.session_state['paper_pdf'] = upload_pdf.getvalue()
            load_json(MASADER_BOT_URL, pdf=pdf)
        else:
            reset_config()
    else:
        st.session_state.show_form = True

    col1, col2 = st.columns(2)
    height = 1200
    with col1:
        if st.session_state.show_form:
            with st.container(height=height):
                with st.form(key="dataset_form", border=False):
                    create_element("GitHub username*", key="gh_username", value="zaidalyafeai")
                    for key in columns:
                        if 'options' in input_json[key]:
                            options = input_json[key]['options']
                        else:
                            options = []
                        create_element(key, options=options, key=key, help = input_json[key]['question'], type = input_json[key]['output_type'])
                    final_state()

    with col2:
        with st.container(height=height):
            if st.session_state['paper_pdf'] is not None:
                pdf_viewer(st.session_state['paper_pdf'], height=height, render_text=True)
            else:
                st.warning("No PDF found")


if __name__ == "__main__":
    main()
