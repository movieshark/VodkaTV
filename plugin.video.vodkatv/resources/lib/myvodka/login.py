from urllib.parse import quote_plus
from uuid import uuid4

from requests import Session
from resources.lib.myvodka import static


class LoginException(Exception):
    """
    Exception raised when login fails.
    """

    def __init__(self, reason: str, result_code: str, error: str):
        self.reason = reason
        self.result_code = result_code
        self.error = error

    def __str__(self):
        return f"Login failed: {self.reason} ({self.result_code}) - {self.error}"


def oxauth_login(
    session: Session,
    url: str,
    client_id: str,
    client_secret: str,
    username: str,
    password: str,
    authorization: str,
    keep_signed_in: bool = True,
) -> dict:
    """
    Login to oxauth endpoint and return the response.

    :param session: requests.Session object
    :param url: The oxauth URL
    :param client_id: The client ID
    :param client_secret: The client secret
    :param username: The username
    :param password: The password
    :param authorization: The authorization
    :param keep_signed_in: Whether to keep signed in
    :return: The response
    """
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": quote_plus(static.scope),
        "grant_type": static.grant,
        "keep_signed_in": "true" if keep_signed_in else "false",
        "password": password,
        "username": username,
    }
    headers = {
        "Authorization": authorization,
    }
    response = session.post(url, data=data, headers=headers)
    json_response = response.json()
    print(json_response)
    if json_response.get("result_code") != "SUCCESS":
        raise LoginException(
            json_response.get("reason"),
            json_response.get("result_code"),
            json_response.get("error"),
        )
    return json_response


def publicapi_login(session: Session, url: str, client_id: str, assertion: str) -> dict:
    """
    Login to publicapi endpoint and return the response.

    :param session: requests.Session object
    :param platform: The platform
    :param version: The version
    :param client_id: The client ID
    :param assertion: The assertion
    :return: The response
    """
    data = {
        "client_id": client_id,
        "assertion": assertion,
        "grant_type": static.grant_type,
    }
    headers = {
        "X-Correlation-Id": str(uuid4()),
        "Accept-Language": "hu",
    }
    response = session.post(url, data=data, headers=headers)
    response.raise_for_status()
    return response.json()


def list_subscriptions(
    session: Session, url: str, authorization: str, entity_id: str
) -> dict:
    """
    List subscriptions entitled to the customer.

    :param session: requests.Session object
    :param authorization: The authorization bearer token
    :param entity_id: The entity ID of the currently selected subscription
    :return: The response
    """
    headers = {
        "X-Correlation-Id": str(uuid4()),
        "Accept-Language": "hu",
        "Authorization": authorization,
        "Entity-Id": entity_id,
    }
    response = session.get(url, headers=headers)
    response.raise_for_status()
    return response.json()
