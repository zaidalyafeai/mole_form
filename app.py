from __future__ import annotations

import streamlit as st  # ignore
import requests
import re
import json
import os
from pathlib import Path
from datetime import date
from constants import *
from github_push import GithubPushError, load_github_credentials, push_metadata_to_github, validate_github_username
from streamlit_tags import st_tags
from dotenv import load_dotenv
from streamlit_pdf_viewer import pdf_viewer
import streamlit.components.v1 as components
import base64

MOLE_URL = "https://mextract-production.up.railway.app"


st.set_page_config(
    page_title="Masader Form",
    page_icon="📮",
    initial_sidebar_state="collapsed",
    layout="wide",
)
"# 📮 :rainbow[Masader Form]"

_APP_DIR = Path(__file__).resolve().parent


load_dotenv(_APP_DIR / ".env", override=True)
GITHUB_TOKEN, GIT_USER_NAME, GIT_USER_EMAIL = load_github_credentials()

import requests

# Example Usage
mode = st.selectbox("Mode", ["ar", "en", "ru", "jp", "fr", "multi"])

try:
    schema_payload = requests.post(
        f"{MOLE_URL}/schema", data={"name": mode}, timeout=60
    ).json()
    schema = (
        json.loads(schema_payload)
        if isinstance(schema_payload, str)
        else schema_payload
    )
except Exception as e:
    st.error(f"Failed to load schema: {e}")
    st.stop()

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


def canonical_column_key(key: str) -> str | None:
    if key in columns:
        return key
    spaced = key.replace("_", " ")
    if spaced in columns:
        return spaced
    underscored = key.replace(" ", "_")
    if underscored in columns:
        return underscored
    return None


def to_catalogue_key(key: str) -> str:
    canonical = canonical_column_key(key)
    return (canonical or key).replace("_", " ")


def config_value(json_data: dict, column: str):
    for key in (column, column.replace("_", " "), column.replace(" ", "_")):
        if key in json_data:
            return json_data[key]
    return default_for_column(column)


def normalize_config_to_schema(config: dict) -> dict:
    normalized: dict = {}
    for key, value in config.items():
        if key == "annotations_from_paper":
            if isinstance(value, dict):
                annotations = {}
                for ann_key, ann_value in value.items():
                    col = canonical_column_key(ann_key)
                    annotations[col if col else ann_key] = ann_value
                normalized[key] = annotations
            else:
                normalized[key] = value
            continue

        canonical = canonical_column_key(key)
        if not canonical:
            normalized[key] = value
            continue

        existing = normalized.get(canonical)
        if existing is None or (not existing and value):
            normalized[canonical] = value
    return normalized


def config_to_catalogue_format(config: dict) -> dict:
    catalogue: dict = {}
    for key, value in config.items():
        if key == "annotations_from_paper" and isinstance(value, dict):
            catalogue[key] = {to_catalogue_key(k): v for k, v in value.items()}
        else:
            catalogue[to_catalogue_key(key)] = value
    return catalogue


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


def default_for_column(column: str):
    answer_type = column_types[column]
    if "options" in schema[column]:
        if answer_type in ["str", "url", "bool"]:
            return schema[column]["options"][-1]
        if answer_type == "list[str]":
            return [schema[column]["options"][-1]]
    if answer_type == "list[str]":
        return []
    if "list[dict" in answer_type:
        return []
    if answer_type == "year":
        return date.today().year
    if answer_type == "int":
        return 0
    if answer_type == "float":
        return 0.0
    if answer_type == "bool":
        return False
    return ""


def coerce_value_for_column(column: str, value):
    answer_type = column_types[column]
    if "options" not in schema[column]:
        return value

    options = schema[column]["options"]

    if answer_type == "str":
        if value in options:
            return value
        if isinstance(value, str):
            lowered = value.lower()
            for option in options:
                if option.lower() == lowered:
                    return option
        return default_for_column(column)

    if answer_type == "list[str]":
        if not isinstance(value, list):
            return default_for_column(column)
        coerced = []
        for item in value:
            if item in options:
                coerced.append(item)
                continue
            if isinstance(item, str):
                lowered = item.lower()
                for option in options:
                    if option.lower() == lowered:
                        coerced.append(option)
                        break
        return coerced if coerced else default_for_column(column)

    return value


def ensure_widget_value(column: str, options: list) -> None:
    if column not in st.session_state or not options:
        return
    coerced = coerce_value_for_column(column, st.session_state[column])
    if coerced != st.session_state[column]:
        st.session_state[column] = coerced


def update_session_config(json_data):
    annotations = json_data.get("annotations_from_paper", {})
    for column in columns:
        if use_annotations_paper:
            st.session_state[f"annot_{column}"] = annotations.get(column, 1)
        type = column_types[column]
        if type == "list[str]":
            values = coerce_value_for_column(column, config_value(json_data, column))
            st.session_state[column] = values

        elif "list[dict[" in type:
            subsets = config_value(json_data, column)
            if not isinstance(subsets, list):
                subsets = []
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
                            raw_value = subset[subkey]
                            if subkey in schema and "options" in schema[subkey]:
                                raw_value = coerce_value_for_column(subkey, raw_value)
                            if column_types[subkey] == "float":
                                st.session_state[f"{column}_{i}_{subkey}"] = float(raw_value)
                            else:
                                st.session_state[f"{column}_{i}_{subkey}"] = raw_value
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
            st.session_state[column] = bool(config_value(json_data, column))
        else:
            st.session_state[column] = coerce_value_for_column(
                column, config_value(json_data, column)
            )


def query_param(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    if value is None:
        return default
    return str(value).strip()


def json_url_from_query() -> str:
    return query_param("json_url") or query_param("json_link")


def update_config(config, update_url=True):
    if not config:
        return
    if "metadata" in config:
        config = config["metadata"]

    config = normalize_config_to_schema(config)

    if update_url:
        paper_col = next(
            (c for c in columns if c.replace("_", " ").lower() == "paper link"),
            None,
        )
        if paper_col and paper_col in config:
            st.session_state.paper_url = normalize_paper_url(config[paper_col])

    st.session_state.show_form = True
    merged = create_default_json()
    merged.update(config)
    if "annotations_from_paper" not in merged:
        merged["annotations_from_paper"] = {}
    for column in columns:
        merged["annotations_from_paper"].setdefault(column, 1)
    update_session_config(merged)


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


def github_credentials_ok() -> bool:
    token, user_name, user_email = load_github_credentials()
    if not token:
        st.error(
            "GITHUB_TOKEN is not set. Add it to `.env` in the project root "
            "(see https://github.com/settings/tokens), then restart Streamlit."
        )
        return False
    if not user_name or not user_email:
        st.error("GIT_USER_NAME and GIT_USER_EMAIL must be set in `.env`.")
        return False
    return True


def update_pr(new_dataset):
    if not github_credentials_ok():
        return

    try:
        result = push_metadata_to_github(
            new_dataset,
            st.session_state["gh_username"],
        )
    except GithubPushError as exc:
        st.error(exc.message)
        return

    if result.status == "unchanged":
        st.info(result.message or "No changes made to the dataset")
        return

    if result.pull_request_url:
        action = "updated" if result.status == "updated" else "created"
        st.success(f"Pull request {action}: {result.pull_request_url}")

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
    default_json = {column: default_for_column(column) for column in columns}

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
    st.session_state._last_ai_paper_url = ""
    st.session_state._loaded_json_url = ""
    st.session_state._paper_pdf_cache_key = ""
    st.session_state._paper_pdf_bytes = None


def load_metadata_from_url(url: str) -> dict | None:
    url = url.strip()
    if not url:
        return None
    try:
        return load_json(link=url)
    except requests.RequestException as exc:
        st.error(f"Failed to fetch metadata JSON: {exc}")
    except (json.JSONDecodeError, ValueError) as exc:
        st.error(f"Invalid metadata JSON: {exc}")
    return None


def apply_metadata_from_url(url: str) -> bool:
    if st.session_state.get("_loaded_json_url") == url:
        return bool(st.session_state.get("show_form"))
    metadata = load_metadata_from_url(url)
    if not metadata:
        st.session_state._loaded_json_url = ""
        return False
    update_config(metadata)
    st.session_state._loaded_json_url = url
    return True


ANNOTATION_OPTIONS = [
    "🤖 AI Annotation",
    "🦚 Manual Annotation",
    "🚥 Load Annotation",
]
URL_ANNOTATION_TYPES = {
    "ai": "🤖 AI Annotation",
    "manual": "🦚 Manual Annotation",
    "load": "🚥 Load Annotation",
}


def annotation_index_from_url() -> int:
    if json_url_from_query():
        return ANNOTATION_OPTIONS.index("🚥 Load Annotation")
    annotation_type = query_param("annotation_type").lower()
    label = URL_ANNOTATION_TYPES.get(annotation_type)
    if label:
        return ANNOTATION_OPTIONS.index(label)
    return 1


def run_ai_extraction(paper_url: str) -> None:
    if st.session_state.get("_last_ai_paper_url") == paper_url:
        return
    st.session_state._last_ai_paper_url = paper_url
    try:
        if "arxiv" in paper_url:
            metadata = get_metadata(link=paper_url)
            if metadata:
                update_config(metadata, update_url=False)
            else:
                st.session_state._last_ai_paper_url = ""
            return
        response = requests.get(paper_url, timeout=30)
        response.raise_for_status()
        if response.headers.get("Content-Type") == "application/pdf":
            pdf = (
                paper_url.split("/")[-1],
                response.content,
                response.headers.get("Content-Type", "application/pdf"),
            )
            metadata = get_metadata(pdf=pdf)
            if metadata:
                update_config(metadata)
            else:
                st.session_state._last_ai_paper_url = ""
        else:
            st.error(
                f"Cannot retrieve a pdf from the link. Make sure {paper_url} is a direct link to a valid pdf"
            )
    except requests.RequestException as exc:
        st.error(f"Failed to fetch PDF: {exc}")
        st.session_state._last_ai_paper_url = ""


def apply_url_query_params() -> None:
    pdf_link = query_param("pdf_link")
    json_url = json_url_from_query()
    annotation_type = query_param("annotation_type").lower()

    if pdf_link:
        st.session_state.paper_url = normalize_paper_url(pdf_link)

    if not annotation_type and not pdf_link and not json_url:
        return

    cache_key = f"{annotation_type}|{pdf_link}|{json_url}"
    if st.session_state.get("_query_params_key") == cache_key:
        return
    st.session_state._query_params_key = cache_key

    if json_url:
        apply_metadata_from_url(json_url)
    elif annotation_type == "manual":
        st.session_state.show_form = True
    elif annotation_type == "ai" and pdf_link:
        run_ai_extraction(pdf_link)


def create_name(name):
    if " " in name:
        # first name of each word
        name = name.split(" ")
        name = [n[0] for n in name]
        name = "".join(name)
    return name.lower()


def validate_columns():
    validation = validate_github_username(st.session_state.get("gh_username", "").strip())
    if not validation.ok:
        st.error(validation.error or "Please enter a valid GitHub username.")
        return False
    for key in required_columns:
        label = to_catalogue_key(key)
        value = st.session_state.get(key, default_for_column(key))
        type = column_types[key]
        if type in ["list[str]", "list[dict]"]:
            if len(value) == 0:
                st.error(f"Please enter a valid {label}.")
                return False
        elif type == "str":
            if value == "":
                st.error(f"Please enter a valid {label}.")
                return False
        elif type == "url":
            if not validate_url(value):
                st.error(f"Please enter a valid {label}.")
                return False
        elif type == "int":
            if value == 0:
                st.error(f"Please enter a valid {label}.")
                return False
    return True


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
            config[column] = st.session_state.get(column, default_for_column(column))

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
    if label in required_columns:
        st.write(f"{label}*")
    else:
        st.write(label)
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
        )
    elif type in ["int", "year"]:
        st.number_input(key, key=key, label_visibility="collapsed", step=1, help=help)
    elif (len(options) > 0 and len(options) <= 5) and type == "str":
        ensure_widget_value(key, options)
        st.radio(key, options=options, key=key, label_visibility="collapsed", help=help)
    elif len(options) > 0 and type == "str":
        ensure_widget_value(key, options)
        st.selectbox(
            key, options=options, key=key, label_visibility="collapsed", help=help
        )
    elif type == "list[str]":
        if len(options) > 0:
            ensure_widget_value(key, options)
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


def normalize_paper_url(url: str) -> str:
    url = url.strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    if "arxiv.org" in url:
        url = fix_arxiv_link(url)
    return url


def get_pdf(paper_url):
    paper_url = normalize_paper_url(paper_url)
    response = requests.get(paper_url, timeout=60)
    response.raise_for_status()
    return response.content


def paper_pdf_cache_key() -> str:
    if st.session_state.get("paper_pdf"):
        return f"upload:{st.session_state.paper_pdf.name}"
    if st.session_state.get("paper_url"):
        return f"url:{normalize_paper_url(st.session_state.paper_url)}"
    return ""


def get_paper_pdf_bytes() -> bytes | None:
    if st.session_state.get("paper_pdf"):
        return st.session_state.paper_pdf.getvalue()

    paper_url = st.session_state.get("paper_url", "").strip()
    if not paper_url:
        return None

    paper_url = normalize_paper_url(paper_url)
    cache_key = paper_pdf_cache_key()
    if (
        st.session_state.get("_paper_pdf_cache_key") == cache_key
        and st.session_state.get("_paper_pdf_bytes")
    ):
        return st.session_state["_paper_pdf_bytes"]

    try:
        pdf_bytes = get_pdf(paper_url)
    except requests.RequestException as exc:
        st.error(f"Failed to load PDF: {exc}")
        return None

    st.session_state._paper_pdf_cache_key = cache_key
    st.session_state._paper_pdf_bytes = pdf_bytes
    return pdf_bytes


def render_paper_preview(height=1200):
    pdf_bytes = get_paper_pdf_bytes()
    if pdf_bytes:
        pdf_viewer(input=pdf_bytes, height=height, width="100%")
        return

    paper_url = st.session_state.get("paper_url", "").strip()
    if paper_url:
        st.warning("Could not load the PDF preview.")
        st.link_button("Open PDF in new tab", normalize_paper_url(paper_url))
    else:
        st.warning("No PDF found")


def download_button(config):
    object_to_download = json.dumps(config, indent=4)
    b64 = base64.b64encode(object_to_download.encode()).decode()

    dl_link = f"""
    <html>
    <head>
    <title>Start Auto Download file</title>
    <script src="http://code.jquery.com/jquery-3.2.1.min.js"></script>
    <script>
    $('<a href="data:text/json;base64,{b64}" download="{create_name(config['Name'])}.json">')[0].click()
    </script>
    </head>
    </html>
    """
    return dl_link


def load_json(file=None, link=""):
    if file:
        data = json.load(file)
    elif link:
        response = requests.get(link, timeout=30)
        response.raise_for_status()
        data = response.json()
    else:
        raise ValueError("No file or link provided to load JSON")

    if isinstance(data, dict) and "metadata" in data:
        return data["metadata"]
    return data


def download_json(config):
    components.html(
        download_button(config),
        height=0,
    )


def displayPDF(link="", pdf=None, height=1200):
    # Opening file from file path
    if pdf:
        base64_pdf = base64.b64encode(pdf).decode("utf-8")
        pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}px"></iframe>'
    elif link != "":
        pdf_display = f'<iframe src="{link}" width="100%" height="{height}px" type="application/pdf"></iframe>'

    # Displaying File
    st.markdown(pdf_display, unsafe_allow_html=True)


@st.fragment
def submit_form():
    col1, col2 = st.columns(2)
    with col1:
        submit = st.form_submit_button("Submit")
    with col2:
        download = st.form_submit_button("Download")

    if submit or download:
        config = config_to_catalogue_format(create_json())
        if download:
            download_json(config)
        elif submit and validate_columns():
            update_pr(config)


def main():
    st.info(
        """
    This is the MOLE form to that allows users to annotate metadata of datasets manually or using AI.
    - There are three options
        - 🦚 Manual Annotation: You can have to insert all the metadata manually.
        - 👾 AI Annotation: Insert the pdf/arxiv link to extract the metadata automatically. 
        - 🚥 Load Annotation: Use this option to load a saved metadata annotation.

    Deep-link with query parameters: `?annotation_type=manual|ai|load`, `pdf_link=<url>`, or `json_url=<direct-json-url>` (e.g. a raw GitHub link to a `.json` file).
    If you have face any issues post them on [GitHub](https://github.com/IVUL-KAUST/MOLE/issues).
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

    apply_url_query_params()

    options = st.selectbox(
        "Annotation Options",
        ANNOTATION_OPTIONS,
        index=annotation_index_from_url(),
        on_change=reset_config,
    )

    if options == "🚥 Load Annotation":
        upload_file = st.file_uploader(
            "Upload Json",
            help="You can use this widget to preload any dataset from https://github.com/ARBML/masader/tree/main/datasets",
        )
        json_url = st.text_input(
            "Direct link to metadata JSON",
            value=json_url_from_query(),
            placeholder="https://raw.githubusercontent.com/ARBML/masader/main/datasets/shami.json",
        )

        if upload_file:
            metadata = load_json(file=upload_file)
            if metadata:
                update_config(metadata)
                st.session_state._loaded_json_url = upload_file.name
        elif json_url:
            apply_metadata_from_url(json_url)
        elif not st.session_state.show_form:
            reset_config()

    if options == "🤖 AI Annotation":
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
            st.session_state._paper_pdf_cache_key = ""
            st.session_state._paper_pdf_bytes = None
            metadata = get_metadata(pdf=pdf)
            update_config(metadata, update_url=False)
        elif paper_url:
            run_ai_extraction(paper_url)
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
                render_paper_preview(height=height)

        with col1:
            with st.container(height=height):
                with st.form(key="dataset_form", border=False):
                    create_element(
                        "GitHub username*", key="gh_username", value="zaidalyafeai"
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
                            help='',
                            type=schema[key]["answer_type"],
                        )
                    submit_form()


if __name__ == "__main__":
    main()
