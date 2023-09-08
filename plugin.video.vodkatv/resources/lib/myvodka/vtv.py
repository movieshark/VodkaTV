from uuid import uuid4

from requests import Session


def get_devices(session: Session, url: str, authorization: str, entity_id: str) -> dict:
    """
    Get the devices.

    :param session: requests.Session object
    :param authorization: The authorization
    :param entity_id: The entity ID
    :return: The response
    """
    headers = {
        "Authorization": authorization,
        "X-Correlation-Id": str(uuid4()),
        "Entity-Id": entity_id,
        "Accept-Language": "hu",
    }
    response = session.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def edit_device(
    session: Session, url: str, authorization: str, entity_id: str, data: dict
) -> bool:
    """
    Edit the device.

    :param session: requests.Session object
    :param authorization: The authorization token
    :param entity_id: The entity ID of the subscription
    :param data: The data to send
    :return: True if successful
    """
    headers = {
        "Authorization": authorization,
        "X-Correlation-Id": str(uuid4()),
        "Entity-Id": entity_id,
        "Accept-Language": "hu",
    }
    response = session.put(url, headers=headers, json=data)
    json_response = response.json()
    if json_response.get("result") != "success":
        raise Exception(json_response.get("error"))
    return True


def delete_device(
    session: Session, url: str, authorization: str, entity_id: str
) -> bool:
    """
    Delete the device.

    :param session: requests.Session object
    :param authorization: The authorization token
    :param entity_id: The entity ID of the subscription
    :return: True if successful
    """
    headers = {
        "Authorization": authorization,
        "X-Correlation-Id": str(uuid4()),
        "Entity-Id": entity_id,
        "Accept-Language": "hu",
    }
    response = session.delete(url, headers=headers)
    json_response = response.json()
    if json_response.get("result") != "success":
        raise Exception(json_response.get("error"))
    return True
