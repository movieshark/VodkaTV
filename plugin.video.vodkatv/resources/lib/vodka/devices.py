from typing import Tuple

from requests import Session

from . import static
from .enums import DomainResponseStatus
from .misc import construct_init_obj


class DeviceDeletionError(Exception):
    """Raised when a device deletion fails"""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(f"{message} (code: {code})")
        self.code = code


class DeviceRegistrationError(Exception):
    """
    Exception raised when the device registration fails.
    """

    def __init__(self, status_code: DomainResponseStatus):
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


def register_device(
    session: Session, json_post_gw: str, device_name: str, **kwargs
) -> dict:
    """
    Register the device.

    :param session: The requests session to use.
    :param json_post_gw: The JSON post gateway URL.
    :param device_name: The device name.
    :param kwargs: Additional parameters.
    :return: The response.
    """
    device_brand_id = kwargs.get("device_brand_id", static.device_brand_id)
    init_obj = construct_init_obj(**kwargs)
    post_data = {
        "initObj": init_obj,
        "iDeviceBrandID": device_brand_id,
        "sDeviceName": device_name,
    }
    response = session.post(f"{json_post_gw}?m=AddDeviceToDomain", json=post_data)
    response.raise_for_status()
    # get m_oDomainResponseStatus from response
    domain_response_status = response.json()["m_oDomainResponseStatus"]
    if domain_response_status != DomainResponseStatus.OK.value:
        raise DeviceRegistrationError(DomainResponseStatus(domain_response_status))
    return response.json()


def get_devices(
    _session: Session, gateway_phoenix_url: str, ks_token: str, **kwargs
) -> tuple:
    """
    Get the devices registered to the user

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param ks_token: The ks token
    :param kwargs: Optional arguments
    :return: A tuple containing the devices and the total number of devices
    """
    # NOTE: call doesn't exist in official app
    api_version = kwargs.get("api_version", static.api_version)
    data = {
        "apiVersion": api_version,
        "ks": ks_token,
    }
    response = _session.post(
        f"{gateway_phoenix_url}householddevice/action/list",
        json=data,
    )
    return response.json()["result"]["objects"], response.json()["result"]["totalCount"]


def get_device(
    _session: Session, gateway_phoenix_url: str, ks_token: str, **kwargs
) -> dict:
    """
    Get the currently registered device information

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param ks_token: The ks token
    :param kwargs: Optional arguments
    :return: A dict containing the device information
    """
    api_version = kwargs.get("api_version", static.api_version)
    data = {
        "apiVersion": api_version,
        "ks": ks_token,
    }
    response = _session.post(
        f"{gateway_phoenix_url}householddevice/action/get",
        json=data,
    )
    return response.json()["result"]


def get_device_brands(
    _session: Session, gateway_phoenix_url: str, ks_token: str, **kwargs
) -> list:
    """
    Fetches the known device brands from the VTV API

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param ks_token: The ks token
    :param kwargs: Optional arguments
    :return: A list of device brands
    """
    # NOTE: call doesn't exist in official app
    api_version = kwargs.get("api_version", static.api_version)
    data = {
        "apiVersion": api_version,
        "ks": ks_token,
    }
    response = _session.post(
        f"{gateway_phoenix_url}devicebrand/action/list",
        json=data,
    )
    return response.json()["result"]["objects"]


def get_brands(
    _session: Session, gateway_phoenix_url: str, ks_token: str, **kwargs
) -> dict:
    """
    Calls the get_device_brands function and returns a dict
     where the key is the device id and the value is the device name

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param ks_token: KS Token
    :param kwargs: Optional arguments
    :return: dict
    """
    api_version = kwargs.get("api_version", static.api_version)
    brands = get_device_brands(
        _session, gateway_phoenix_url, ks_token, api_version=api_version
    )
    return {brand["id"]: brand["name"] for brand in brands}


def delete_device(
    _session: Session, gateway_phoenix_url: str, ks_token: str, ud_id: str, **kwargs
) -> list:
    """
    Delete a device permanently from the user's household

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param ks_token: The ks token
    :param ud_id: The device's ud_id
    :param kwargs: Optional arguments
    :return: A single item list containing the deletion result
    """
    # NOTE: call doesn't exist in official app
    api_version = kwargs.get("api_version", static.api_version)
    data = {
        "apiVersion": api_version,
        "ks": ks_token,
        "udid": ud_id,
    }
    response = _session.post(
        f"{gateway_phoenix_url}householddevice/action/delete",
        json=data,
    )
    if not isinstance(response.json().get("result"), bool) and response.json().get(
        "result", {}
    ).get("error"):
        raise DeviceDeletionError(
            response.json()["result"]["error"]["message"],
            response.json()["result"]["error"]["code"],
        )
    return response.json()["result"]


def get_streaming_devices(
    _session: Session, gateway_phoenix_url: str, ks_token: str, **kwargs
) -> Tuple[list, int]:
    """
    Get the currently streaming devices registered to the user

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param ks_token: The ks token
    :param kwargs: Optional arguments
    :return: A tuple containing the streaming device list and the
    total number of devices
    """
    # NOTE: call doesn't exist in official app
    api_version = kwargs.get("api_version", static.api_version)
    data = {
        "apiVersion": api_version,
        "ks": ks_token,
        "filter": {
            "objectType": f"{static.get_ott_platform_name()}StreamingDeviceFilter"
        },
    }
    response = _session.post(
        f"{gateway_phoenix_url}streamingdevice/action/list",
        json=data,
    )
    return response.json()["result"]["objects"], response.json()["result"]["totalCount"]
