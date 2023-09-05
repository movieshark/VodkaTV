from typing import Tuple

from requests import Session

from . import static
from .misc import construct_init_obj


def filter(
    _session: Session,
    gateway_phoenix_url: str,
    filter_obj: dict,
    ks_token: str,
    page_idx: int = 1,
    **kwargs,
) -> Tuple[list, int]:
    """
    Calls the list ep with a provided filter object.

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param filter_obj: The filter object
    :param ks_token: The ks token
    :param page_idx: The page index
    :param kwargs: Optional arguments (ie. response_profile: dict, page_size: int = 500)
    :return: A tuple containing the list of media items and the total number of items
    """
    api_version = kwargs.get("api_version", static.api_version)
    page_size = kwargs.get("page_size", 500)
    data = {
        "ks": ks_token,
        "filter": filter_obj,
        "pager": {
            "objectType": f"{static.get_ott_platform_name()}FilterPager",
            "pageSize": page_size,
            "pageIndex": page_idx,
        },
        "apiVersion": api_version,
    }
    response_profile = kwargs.get("response_profile")
    if response_profile:
        data["responseProfile"] = response_profile
    response = _session.post(
        f"{gateway_phoenix_url}/asset/action/list",
        json=data,
    )
    response.raise_for_status()
    total_count = response.json().get("result", {}).get("totalCount", 0)
    if total_count == 0:
        return [], 0
    return response.json()["result"]["objects"], total_count


def get_channel_list(
    _session: Session, gateway_phoenix_url: str, ks_token: str, **kwargs
) -> list:
    """
    Fetches the live channel list from the API

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param ks_token: The ks token
    :param kwargs: Optional arguments
    :return: A list of channels
    """

    filter_obj = {
        "kSql": f"(and asset_type='{static.channel_type}')",
        "idEqual": static.channel_id,
        "objectType": f"{static.get_ott_platform_name()}ChannelFilter",
    }
    response_profile = {
        "objectType": f"{static.get_ott_platform_name()}DetachedResponseProfile",
        "name": f"{static.get_ott_platform_name()}AssetImagePerRatioFilter",
        "filter": {
            "objectType": f"{static.get_ott_platform_name()}AssetImagePerRatioFilter",
        },
    }
    # request all channels in 50 per page chunks
    objects = []
    page_idx = 1
    while True:
        result, total_count = filter(
            _session,
            gateway_phoenix_url,
            filter_obj,
            ks_token,
            page_idx,
            response_profile=response_profile,
            page_size=50,
            **kwargs,
        )
        objects.extend(result)
        if len(objects) >= total_count:
            break
        page_idx += 1
    return objects


def product_price_list(
    _session: Session, gateway_phoenix_url: str, file_ids: list, ks_token: str, **kwargs
):
    """
    Fetches the product price list from the API.
    Used to check whether the user has access to a particular item.

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param file_ids: The list of file ids
    :param ks_token: The ks token
    :param kwargs: Optional arguments
    :return: A list of product prices
    """
    api_version = kwargs.get("api_version", static.api_version)
    data = {
        "ks": ks_token,
        "filter": {
            "fileIdIn": ",".join(file_ids),
            "IsLowest": False,
        },
        "apiVersion": api_version,
    }
    response = _session.post(
        f"{gateway_phoenix_url}/productprice/action/list",
        json=data,
    )
    response.raise_for_status()
    return response.json()["result"]["objects"]


def get_epg_by_channel_ids(
    _session: Session,
    json_post_gw: str,
    channel_ids: list,
    from_offset: int,
    to_offset: int,
    utc_offset: int,
    **kwargs,
) -> list:
    """
    Fetches the epg for a list of channels

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix url
    :param ks_token: The ks token
    :param channel_ids: The list of channel ids
    :param from_offset: The start time offset
    :param to_offset: The end time offset
    :param utc_offset: The UTC offset
    :param kwargs: Optional arguments
    :return: A list of epg items
    """
    data = {
        "initObj": construct_init_obj(**kwargs),
        "iFromOffset": from_offset,
        "iToOffset": to_offset,
        "iUtcOffset": utc_offset,
        "oUnit": "Days",
        "sEPGChannelID": channel_ids,
        "sPicSize": "full",
    }
    response = _session.post(
        f"{json_post_gw}?m=GetEPGMultiChannelProgram",
        json=data,
    )
    response.raise_for_status()
    return response.json()


def get_recordings(
    _session: Session,
    json_post_gw: str,
    page_index: int = 0,
    page_size: int = 50,
    epg_channel_id: int = 0,
    **kwargs,
):
    """
    Fetches the recordings for a list of channels

    :param _session: requests.Session object
    :param json_post_gw: The JSON post gateway URL
    :param page_index: The page index
    :param page_size: The page size
    :param epg_channel_id: The EPG channel ID
    :param kwargs: Optional arguments
    :return: A list of recordings
    """
    data = {
        "pageSize": page_size,
        "pageIndex": page_index,
        "searchBy": "ByRecordingStatus",
        "epgChannelID": epg_channel_id,
        "recordingIDs": [],
        "programIDs": [],
        "seriesIDs": [],
        "recordedEPGOrderObj": {"m_eOrderBy": "StartTime", "m_eOrderDir": "DESC"},
        "recordingStatus": "Completed",
        "initObj": construct_init_obj(**kwargs),
    }
    response = _session.post(
        f"{json_post_gw}?m=GetRecordings",
        json=data,
    )
    response.raise_for_status()
    return response.json()
