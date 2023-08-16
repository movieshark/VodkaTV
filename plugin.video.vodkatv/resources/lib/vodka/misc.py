import re
from base64 import b64encode
from json import loads
from uuid import uuid4

from Cryptodome.Cipher import PKCS1_v1_5
from Cryptodome.PublicKey import RSA
from requests import Session
from xmltodict import parse

from . import static


def construct_init_obj(**kwargs) -> dict:
    """
    Construct the init object that's used regularly in API calls.

    :param kwargs: Additional parameters.
    :return: The init object.
    """
    api_user = kwargs.get("api_user", "")
    api_pass = kwargs.get("api_pass", "")
    domain_id = kwargs.get("domain_id", "")
    site_guid = kwargs.get("site_guid", "")
    locale_language = kwargs.get("locale_language", static.locale_language)
    locale_country = kwargs.get("locale_country", static.locale_country)
    locale_device = kwargs.get("locale_device", static.locale_device)
    locale_user_state = kwargs.get("locale_user_state", static.locale_user_state)
    platform = kwargs.get("platform", "")
    token = kwargs.get("token", "")
    ud_id = kwargs.get("ud_id", "")

    init_obj = {
        "ApiUser": api_user,
        "ApiPass": api_pass,
        "DomainID": domain_id,
        "SiteGUID": site_guid,
        "Locale": {
            "LocaleLanguage": locale_language,
            "LocaleCountry": locale_country,
            "LocaleDevice": locale_device,
            "LocaleUserState": locale_user_state,
        },
        "Platform": platform,
        "UDID": ud_id,
    }
    if token:
        init_obj["Token"] = token
    return init_obj


def encrypt_password(password: str, public_key: str) -> str:
    """
    Encrypt the password with the public key using PKCS#1 v1.5.

    :param password: The password.
    :param public_key: The public key.
    :return: The encrypted password.
    """
    rsa_key = RSA.importKey(public_key)
    cipher = PKCS1_v1_5.new(rsa_key)
    return b64encode(cipher.encrypt(password.encode("utf-8"))).decode("utf-8")


def get_browser(user_agent: str) -> str:
    """
    Get the browser from the user agent.

    :param user_agent: The user agent.
    :return: The browser.
    """
    if "Firefox" in user_agent:
        return "firefox"
    elif "Edg" in user_agent:
        return "edge"
    else:
        return "chrome"


def get_base_domain(session: Session, initxml_url: str) -> str:
    """
    Get the base domain for the API calls.

    :param session: The requests session to use.
    :param initxml_url: The initxml url.
    :return: The base domain.
    """
    response = session.get(initxml_url)
    response.raise_for_status()
    xml_data = parse(response.text)
    return xml_data["INIT"]["dms_url"]


def extract_config_js_values(session: Session) -> dict:
    """
    Extracts various interesting values from the config.js file

    :param session: The requests session to use.
    :return: The extracted values in a dict.
    """
    response = session.get(static.get_config_js())
    response.raise_for_status()
    # match everything (multiline) from 'publicKeyPEM': '
    # until the very next single quote that's not escaped
    # replace the backslashes from the multiline JSON value with nothing
    public_key = (
        re.search(r"'publicKeyPEM': '(.*?[^\\])'", response.text, flags=re.DOTALL)
        .group(1)
        .replace("\\", "")
    )
    keys = [
        "INIT_XML_URL",
        "DMS_USER",
        "DMS_PASS",
        "DMS_APP_NAME",
        "DMS_CVER",
        "DMS_PLATFORM",
        "DMS_GET_CONFIG_PATH",
    ]
    output = {"publicKeyPEM": public_key}
    for key in keys:
        # match everything from 'INIT_XML_URL': '
        # until the very next single quote that's not escaped
        value = re.search(r"'{}': '(.*?[^\\])'".format(key), response.text).group(1)
        output[key] = value
    return output


def generate_ud_id() -> str:
    """
    Generate a random UDID.

    :return: The UDID.
    """
    return str(uuid4())


def get_config_js_to_dict(session: Session) -> dict:
    """
    Get the configuration that contains the public key ToS etc
    For now unused and dangerous method since the JS provider can
    easily hijack unwanted parameters

    :param session: The requests session to use.
    :return: The configuration as a dict.
    """
    response = session.get(static.get_config_js())
    response.raise_for_status()
    # NOTE: we shouldn't do this with regex, ideas are welcome
    # I suck at regexes BTW
    # matches the object from constant('configsApp', {...});
    # multiline regex
    configs_app = re.search(
        r"constant\('configsApp',\s*({.*?})\s*\);", response.text, flags=re.DOTALL
    ).group(1)
    # replace single quotes with double quotes
    configs_app = configs_app.replace("'", '"')
    # remove multiline comments using regex
    configs_app = re.sub(r"/\*.*?\*/", "", configs_app, flags=re.DOTALL)
    # remove single line comments using regex but only if they are after a comma
    configs_app = re.sub(r",\s*//.*?\n", ",", configs_app)
    # quote all keys if they are not quoted already
    configs_app = re.sub(r"([a-zA-Z0-9_]+): ", r'"\1": ', configs_app)
    # remove trailing commas
    configs_app = re.sub(r",(\s*})", r"\1", configs_app)
    # replace backslashes with double backslashes if they are not escaped already
    configs_app = re.sub(r"(?<!\\)(\\\\)*\\", r"\\\\", configs_app)
    # Remove invalid control characters
    configs_app = re.sub(r"[\u0000-\u001F]", "", configs_app)
    return loads(configs_app)
