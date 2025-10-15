import streamlit as st  # ignore
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
import streamlit.components.v1 as components
import base64

MOLE_URL = "https://mextract-production.up.railway.app"
# MOLE_URL = "http://0.0.0.0:8000"


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

# Example Usage
mode = st.selectbox("Mode", ["ar", "en", "ru", "jp", "fr", "multi"])

try:
    schema = requests.post(f"{MOLE_URL}/schema", data={"name": mode}).json()
except Exception as e:
    print("Error:", str(e))

column_types = {}
for c in schema:
    column_types[c] = schema[c]["answer_type"]

column_lens = {}
for c in schema:
    if "answer_max" in schema[c]:
        column_lens[c] = [schema[c]["answer_min"], schema[c]["answer_max"]]
    else:
        column_lens[c] = [schema[c]["answer_min"], -1]
required_columns = []

for c in schema:
    if schema[c]["answer_min"] > 0:
        required_columns.append(c)

use_annotations_paper = False
# use_annotations_paper = st.toggle("Enable annotations from paper", value = True)

columns = list(schema.keys())


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
    for column in columns:
        if use_annotations_paper:
            st.session_state[f"annot_{column}"] = json_data["annotations_from_paper"][
                column
            ]
        type = column_types[column]
        if type == "list[str]":
            values = json_data[column]
            st.session_state[column] = values

        elif "list[dict[" in type:
            subsets = json_data[column]
            keys = type.replace("list[dict[", "").replace("]]", "").split(",")
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
                        if subkey in column_types:
                            if column_types[subkey] == "float":
                                st.session_state[f"{column}_{i}_{subkey}"] = float(subset[subkey])
                            else:
                                st.session_state[f"{column}_{i}_{subkey}"] = subset[subkey]
            else:
                for subkey in keys:
                    if subkey in schema:
                        if "options" in schema[subkey]:
                            st.session_state[f"{column}_0_{subkey}"] = schema[subkey][
                                "options"
                            ][-1]
                        else:
                            type = column_types[subkey]
                            if type == 'float':
                                st.session_state[f"{column}_0_{subkey}"] = 0.0
                            else:
                                st.session_state[f"{column}_0_{subkey}"] = ""
        elif type == "bool":
            st.session_state[column] = bool(json_data[column])
        else:
            st.session_state[column] = json_data[column]


def update_config(config, update_url=True):
    if "metadata" in config:
        config = config["metadata"]

    if update_url:
        if "Paper Link" in config:
            st.session_state.paper_url = config["Paper Link"]

    st.session_state.show_form = True
    if 'annotations_from_paper' not in config:
        config['annotations_from_paper'] = {}
        for column in columns:
            config['annotations_from_paper'][column] = 1
    update_session_config(config)


def render_list_dict(c, type):
    # list[dict[Name, Volume, Unit, Dialect]]
    type = type.replace("list[dict[", "")
    type = type.replace("]]", "")
    keys = [key.strip() for key in type.split(",")]
    i = 0

    while True:
        cols = st.columns(len(keys))
        first_elem = None
        for j, subkey in enumerate(keys):
            elem = None
            with cols[j]:
                if subkey in schema:
                    if "options" in schema[subkey]:
                        options = schema[subkey]["options"]
                        elem = st.selectbox(
                            subkey, options=options, key=f"{c}_{i}_{subkey}"
                        )
                    else:
                        type = column_types[subkey]
                        if type == "float":
                            elem = st.number_input(
                                subkey,
                                key=f"{c}_{i}_{subkey}",
                                step=0.1,
                            )
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
        local_repo.git.commit("-m", f"Creating {FILE_PATH}")
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


def get_metadata(link="", pdf=None):
    url = f"{MOLE_URL}/run"
    # print(pdf)
    if link != "":
        response = requests.post(url, data={"link": link, "schema_name": mode})
    elif pdf:
        response = requests.post(url, files={"file": pdf}, data={"schema_name": mode})
    else:
        response = requests.get(url)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the JSON content
        json_data = response.json()
        return json_data
    else:
        st.error(response.text)
    return None


def create_default_json():
    default_json = {}
    for column in columns:
        type = column_types[column]
        if "options" in schema[column]:
            if type in ["str", "url", "bool"]:
                default_json[column] = schema[column]["options"][-1]
            elif type == "list[str]":
                default_json[column] = [schema[column]["options"][-1]]
            else:
                raise ()
        elif type == "list[str]":  # no options
            default_json[column] = []
        elif "list[dict" in type:
            default_json[column] = []
        elif type == "year":
            default_json[column] = date.today().year
        elif type == "int":
            default_json[column] = 0
        elif type == "float":
            default_json[column] = 0.0
        else:
            default_json[column] = ""

    if use_annotations_paper:
        default_json["annotations_from_paper"] = {}
        for column in columns:
            default_json["annotations_from_paper"][column] = 1
    return default_json


def reset_config():
    default_json = create_default_json()
    update_config(default_json)
    st.session_state.show_form = False
    st.session_state.paper_url = ""
    st.session_state.paper_pdf = None


def create_name(name):
    if " " in name:
        # first name of each word
        name = name.split(" ")
        name = [n[0] for n in name]
        name = "".join(name)
    return name.lower()


def validate_columns():
    """Validate required columns and return list of error messages."""
    errors = []
    
    if not validate_github(st.session_state["gh_username"].strip()):
        errors.append("Please enter a valid GitHub username.")
    
    for key in required_columns:
        value = st.session_state[key]
        type = column_types[key]
        display_key = key.replace('_', ' ')
        
        if type in ["list[str]", "list[dict]"]:
            if len(value) == 0:
                errors.append(f"Please enter a valid {display_key}.")
        elif type == "str":
            if value == "":
                errors.append(f"Please enter a valid {display_key}.")
        elif type == "int":
            if value == 0:
                errors.append(f"Please enter a valid {display_key}.")
    
    return errors


def create_json():
    config = {}

    for column in columns:
        type = column_types[column]
        if "list[dict[" in type:
            config[column] = []
            subset_keys = [key.strip() for key in type.replace("list[dict[", "").replace("]]", "").split(",")]
            i = 0
            while True:
                subset = {}
                matched_subsets = [s for s in st.session_state if f"{column}_{i}_" in s]
                if len(matched_subsets):
                    for subset_key_name in subset_keys:
                        if st.session_state[f"{column}_{i}_{subset_key_name}"] != "":
                            subset[subset_key_name] = st.session_state[f"{column}_{i}_{subset_key_name}"]
                    if len(subset) == len(subset_keys):
                        config[column].append(subset)
                    i += 1
                else:
                    break
        else:
            config[column] = st.session_state[column]

    if use_annotations_paper:
        config["annotations_from_paper"] = {}
        for column in columns:
            config["annotations_from_paper"][column] = (
                1 if st.session_state[f"annot_{column}"] else 0
            )
    return config


def create_element(
    label,
    placeholder="",
    help="",
    key="",
    value="",
    options=[],
    type="str",
):
    if key in required_columns:
        st.write(f"{label}*")
    else:
        st.write(label)
    st.caption(help)
    if use_annotations_paper:
        st.toggle(
            f"Paper annotated",
            key=f"annot_{key}",
            value=True,
        )
    if key in schema:
        if "option_description" in schema[key]:
            desc = ""
            for option in schema[key]["option_description"]:
                desc += f"- **{option}**: {schema[key]['option_description'][option]}\n"
            if help == "":
                help = desc
    if type == "float":
        st.number_input(
            key,
            key=key,
            label_visibility="collapsed",
            step=0.1,
            help=help,
        )
    elif type in ["int", "year"]:
        st.number_input(key, key=key, label_visibility="collapsed", step=1, help=help)
    elif (len(options) > 0 and len(options) <= 5) and type == "str":
        st.radio(key, options=options, key=key, label_visibility="collapsed", help=help)
    elif len(options) > 0 and type == "str":
        st.selectbox(
            key, options=options, key=key, label_visibility="collapsed", help=help
        )
    elif type == "list[str]":
        if len(options) > 0:
            st.multiselect(
                key, options=options, key=key, label_visibility="collapsed", help=help
            )
        else:
            if key not in st.session_state:
                st.session_state[key] = []
            st_tags(
                label="",
                key=key,
                value=st.session_state[key],  # Bind to session state
                suggestions=options,
            )

    elif "list[dict[" in type:
        with st.expander(f"Add {key}"):
            st.caption(
                "Use this field to add dialect subsets of the dataset. For example if the dataset has 1,000 sentences in the Yemeni dialect.\
                        For example take a look at the [shami subsets](https://github.com/ARBML/masader/tree/main/datasets/shami.json)."
            )
            render_list_dict(key, type)
    else:
        if type == "bool":
            st.checkbox(key, key=key, label_visibility="collapsed", help=help)
        elif key in column_lens and column_lens[key][1] > 100:
            st.text_area(
                key,
                key=key,
                placeholder=placeholder,
                help=help,
                label_visibility="collapsed",
            )
        else:
            st.text_input(
                key,
                key=key,
                placeholder=placeholder,
                help=help,
                value=value,
                label_visibility="collapsed",
            )


def fix_arxiv_link(link):
    for version in range(1, 5):
        link = link.replace(f"v{version}", "")
    if link.endswith(".pdf"):
        return link
    if link.endswith("/"):
        link = link[:-1]
    _id = link.split("/")[-1]
    return f"https://arxiv.org/pdf/{_id}.pdf"


def get_pdf(paper_url):
    if "arxiv.org" in paper_url:
        paper_url = fix_arxiv_link(paper_url)
    response = requests.get(paper_url)
    return response.content


def download_button(config):
    object_to_download = json.dumps(config, indent=4)
    b64 = base64.b64encode(object_to_download.encode()).decode()

    dl_link = f"""
    <html>
    <head>
    <title>Start Auto Download file</title>
    <script src="https://code.jquery.com/jquery-3.2.1.min.js"></script>
    <script>
    $('<a href="data:text/json;base64,{b64}" download="{create_name(config['Name'])}.json">')[0].click()
    </script>
    </head>
    </html>
    """
    return dl_link


def load_json(file=None, link=""):
    if file:
        out_json = json.load(file)
    elif link:
        response = requests.get(link)
        response.raise_for_status()  # Raise an error for bad responses (e.g., 404)
        out_json = response.json()
    else:
        raise ("Error: can not load json")
    # repace spaces
    out_json = {k.replace(" ", "_"): v for k, v in out_json.items()}
    try:
        st.session_state.paper_url = out_json["Paper_Link"]
    except:
        st.session_state.paper_url = ""
    return out_json

def download_json(config):
    components.html(
        download_button(config),
        height=0,
    )


def displayPDF(link="", pdf=None, height=1200):
    # Opening file from file path
    if pdf:
        try:
            # Check PDF size for diagnostics
            pdf_size = len(pdf) / (1024 * 1024)  # Size in MB
            if pdf_size > 10:
                print(f"Large PDF detected ({pdf_size:.1f} MB). This may cause display issues.")
            
            # Use streamlit_pdf_viewer for better compatibility
            pdf_viewer(pdf, height=height, render_text=True)
        except Exception as e:
            error_msg = str(e).lower()
            if "memory" in error_msg or "size" in error_msg:
                print(f"PDF too large to display ({pdf_size:.1f} MB). Try a smaller file.")
            elif "corrupt" in error_msg or "invalid" in error_msg:
                print("PDF file appears to be corrupted or invalid.")
            else:
                print(f"PDF viewer failed: {str(e)}")
            
            print("Trying alternative display method...")
            # Fallback to base64 iframe method
            try:
                if len(pdf) < 5 * 1024 * 1024:  # Only try iframe for files < 5MB
                    base64_pdf = base64.b64encode(pdf).decode("utf-8")
                    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}px"></iframe>'
                    st.markdown(pdf_display, unsafe_allow_html=True)
                    print("Using fallback display method")
                else:
                    print("PDF too large for fallback display method")
            except Exception as e2:
                print(f"All display methods failed: {str(e2)}")
    elif link != "":
        try:
            # For external links, try to fetch and display with pdf_viewer
            if "arxiv" in link:
                print("Fetching PDF from ArXiv...")
                # For arxiv links, fetch the PDF content with timeout
                response = requests.get(link, timeout=30)
                if response.status_code == 200:
                    pdf_size = len(response.content) / (1024 * 1024)
                    if pdf_size > 10:
                        print(f"Large PDF from ArXiv ({pdf_size:.1f} MB). This may take time to load.")
                    pdf_viewer(response.content, height=height, render_text=True)
                else:
                    print(f"Failed to fetch PDF from {link} (Status: {response.status_code})")
            else:
                # For other links, use iframe as fallback
                st.info("Loading PDF from external link...")
                pdf_display = f'<iframe src="{link}" width="100%" height="{height}px" type="application/pdf"></iframe>'
                st.markdown(pdf_display, unsafe_allow_html=True)
        except requests.exceptions.Timeout:
            print("Timeout while fetching PDF. The server may be slow or the file too large.")
        except requests.exceptions.RequestException as e:
            print(f"Network error while fetching PDF: {str(e)}")
        except Exception as e:
            error_msg = str(e).lower()
            if "memory" in error_msg:
                print("PDF too large to display in viewer.")
            else:
                print(f"Error displaying PDF from link: {str(e)}")
            
            print("Trying iframe fallback...")
            # Fallback to iframe method
            pdf_display = f'<iframe src="{link}" width="100%" height="{height}px" type="application/pdf"></iframe>'
            st.markdown(pdf_display, unsafe_allow_html=True)
    else:
        st.error("No PDF content provided")


@st.fragment
def submit_form():
    # Error placeholder at the top
    error_container = st.container()
    
    col1, col2 = st.columns(2)
    with col1:
        submit = st.form_submit_button("Submit PR")
    with col2:
        download = st.form_submit_button("Download")

    if submit or download:
        errors = validate_columns()
        if not errors:
            config = create_json()
            config = {key.replace('_', ' '): value for key, value in config.items()}
            if download:
                download_json(config)
            elif submit:
                update_pr(config)
        else:
            with error_container:
                st.error("**Validation Errors:** Please fix the following issues:")
                for error in errors:
                    st.error(f"• {error}")


def main():
    st.info(
        """
    This is the MOLE form to that allows users to annotate metadata of datasets manually or using AI.
    - There are three options
        - 🦚 Manual Annotation: You have to insert all the metadata manually.
        - 👾 AI Annotation: Insert the pdf/arxiv link to extract the metadata automatically. 
        - 🚥 Load Annotation: Use this option to load a saved metadata annotation. 
    If you face any issues post them on [GitHub](https://github.com/ARBML/masader/issues).
    """,
    )

    # - Check the dataset does not exist in the catelouge using the search [Masader](https://arbml.github.io/masader/search)
    # - You have a valid GitHub username
    # - You have the direct link to the dataset repository
    # Once you submit the dataset, we will send a PR, make sure you follow up there if you have any questions. 

    if "show_form" not in st.session_state:
        reset_config()

    if "paper_pdf" not in st.session_state:
        st.session_state.paper_pdf = None

    # if st.query_params:
    #     if st.query_params["json_url"]:
    #         load_json(st.query_params["json_url"])

    options = st.selectbox(
        "Annotation Options",
        ["👾 AI Annotation", "🦚 Manual Annotation", "🚥 Load Annotation"],
        index=1,
        on_change=reset_config,
    )

    if options == "🚥 Load Annotation":
        upload_file = st.file_uploader(
            "Upload Json",
            help="You can use this widget to preload any dataset from https://github.com/ARBML/masader/tree/main/datasets",
        )
        json_url = st.text_input(
            "Path to json",
            placeholder="https://raw.githubusercontent.com/ARBML/masader/refs/heads/main/datasets/sada.json",
        )

        if upload_file:
            metadata = load_json(file=upload_file)
            update_config(metadata)
        elif json_url:
            metadata = load_json(link=json_url)
            update_config(metadata)
        else:
            reset_config()

    if options == "👾 AI Annotation":
        st.warning(
            "‼️ AI annotation uses LLMs to extract the metadata form papers. However, this approach\
                is not reliable as LLMs can hellucinate and extract untrustworthy informations. \
                Make sure you revise the generated metadata before you submit."
        )
        upload_pdf = st.file_uploader(
            "Upload PDF of the paper",
            help="You can use this widget to preload any dataset from https://github.com/ARBML/masader/tree/main/datasets",
        )
        paper_url = st.session_state.paper_url
        if upload_pdf:
            # Prepare the file for sending
            pdf = (upload_pdf.name, upload_pdf.getvalue(), upload_pdf.type)
            st.session_state.paper_pdf = upload_pdf
            metadata = get_metadata(pdf=pdf)
            update_config(metadata, update_url=False)
        elif paper_url:
            if "arxiv" in paper_url:
                metadata = get_metadata(link=paper_url)
                update_config(metadata, update_url=False)
            else:
                response = requests.get(paper_url)
                response.raise_for_status()  # Raise an error for bad responses (e.g., 404)
                if response.headers.get("Content-Type") == "application/pdf":
                    pdf = (
                        paper_url.split("/")[-1],
                        response.content,
                        response.headers.get("Content-Type", "application/pdf"),
                    )
                    metadata = get_metadata(pdf=pdf)
                    update_config(metadata)
                else:
                    st.error(
                        f"Cannot retrieve a pdf from the link. Make sure {paper_url} is a direct link to a valid pdf"
                    )
        else:
            reset_config()

    if options == "🦚 Manual Annotation":
        st.session_state.show_form = True

    if options != "🚥 Load Annotation":
        st.text_input("Paper Direct Link", key="paper_url")

    col1, col2 = st.columns(2)
    height = 1200

    if st.session_state.show_form:
        with col2:
            with st.container(height=height):
                if st.session_state.paper_pdf:
                    # Convert to bytes for PDF display
                    pdf_bytes = st.session_state.paper_pdf.getvalue()
                    displayPDF(pdf=pdf_bytes)
                elif st.session_state.paper_url:
                    displayPDF(link=st.session_state.paper_url, height=height)
                else:
                    st.warning("No PDF found")

        with col1:
            with st.container(height=height):
                with st.form(key="dataset_form", border=False):
                    create_element(
                        "GitHub username*", key="gh_username", value=""
                    )
                    for key in columns:
                        if key == "annotations_from_paper":
                            continue
                        if "options" in schema[key]:
                            options = schema[key]["options"]
                        else:
                            options = []
                        create_element(
                            key.replace('_', ' '),
                            options=options,
                            key=key,
                            help=schema[key]["description"],
                            type=schema[key]["answer_type"],
                        )
                    submit_form()


if __name__ == "__main__":
    main()
