from typing import Tuple

from requests import Session

from . import misc, static
from .enums import LoginStatusCodes


class LoginError(Exception):
    """
    Exception raised when login fails.
    """

    def __init__(self, status_code: LoginStatusCodes):
        """
        Initialize the exception.

        :param status_code: The status code.
        """
        self.status_code = status_code
        self.message = status_code.name

    def __str__(self) -> str:
        """
        Get the string representation of the exception.

        :return: The string representation.
        """
        return f"{self.message} ({self.status_code.value})"


def get_config(session: Session, ud_id: str, **kwargs) -> Tuple[str, dict]:
    """
    Get the configuration for the API calls.

    :param session: The requests session to use.
    :param ud_id: The device ID.
    :param kwargs: Additional parameters.
    :return: The public RIM key and the configuration.
    """
    values_from_configjs = misc.extract_config_js_values(session)
    app_name = values_from_configjs["DMS_APP_NAME"]
    os = kwargs.get("os", static.config_platform_os)
    browser = misc.get_browser(session.headers.get("User-Agent", ""))
    app_name = app_name.format(os=os, browser=browser)
    base_domain = misc.get_base_domain(session, values_from_configjs["INIT_XML_URL"])
    params = {
        "username": values_from_configjs["DMS_USER"],
        "password": values_from_configjs["DMS_PASS"],
        "appname": app_name,
        "cver": values_from_configjs["DMS_CVER"],
        "udid": ud_id,
        "platform": values_from_configjs["DMS_PLATFORM"],
    }
    response = session.post(
        base_domain + values_from_configjs["DMS_GET_CONFIG_PATH"], params=params
    )
    response.raise_for_status()
    return values_from_configjs["publicKeyPEM"], response.json()


def sign_in(
    session: Session,
    json_post_gw: str,
    ud_id: str,
    api_user: str,
    api_pass: str,
    platform: str,
    username: str,
    password: str,
    public_key: str,
) -> Tuple[dict, str, str]:
    """
    Sign in to the API.

    :param session: The requests session to use.
    :param json_post_gw: The JSON post gateway URL.
    :param api_user: The API user.
    :param api_pass: The API password.
    :param username: The username.
    :param password: The password.
    :return: The response, the access token and the refresh token.
    """
    data = {
        "initObj": {
            "ApiUser": api_user,
            "ApiPass": api_pass,
            "Platform": platform,
            "Locale": {
                "LocaleUserState": "Unknown",
                "LocaleCountry": "null",
                "LocaleDevice": "null",
                "LocaleLanguage": static.locale_language,
            },
            "UDID": ud_id,
        },
        "username": username,
        "password": misc.encrypt_password(password, public_key),
        "providerID": static.provider_id,
    }
    response = session.post(f"{json_post_gw}?m=SSOSignIn", json=data)
    response.raise_for_status()
    json_data = response.json()
    if json_data["LoginStatus"] != LoginStatusCodes.OK.value:
        raise LoginError(LoginStatusCodes(json_data["LoginStatus"]))
    access_token = response.headers["access_token"]
    refresh_token = response.headers["refresh_token"]
    return json_data, access_token, refresh_token


def refresh_access_token(
    session: Session, json_post_gw: str, refresh_token: str, **kwargs
) -> Tuple[str, str, int, int]:
    """
    Refresh the access token.

    :param session: The requests session to use.
    :param json_post_gw: The JSON post gateway URL.
    :param refresh_token: The refresh token.
    :param kwargs: Additional parameters.
    :return: The new access token, the new refresh token, the expiration time of the access token and the expiration
     time of the refresh token.
    """
    init_obj = misc.construct_init_obj(**kwargs)
    data = {"initObj": init_obj, "refreshToken": refresh_token}
    response = session.post(f"{json_post_gw}?m=RefreshAccessToken", json=data)
    response.raise_for_status()
    json_data = response.json()
    return (
        json_data["access_token"],
        json_data["refresh_token"],
        json_data["expiration_time"],
        json_data["refresh_expiration_time"],
    )
