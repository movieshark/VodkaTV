from requests import Session

from . import static
from .misc import construct_init_obj


class RecordingException(Exception):
    """
    Exception raised when recording fails.
    """

    def __init__(self, message: str, status: int):
        self.message = message
        self.status = status


def record_asset(_session: Session, json_post_gw: str, epg_id: int, **kwargs) -> str:
    """
    Creates a single recording of the given EPG ID.

    :param _session: requests.Session object
    :param json_post_gw: The JSON post gateway URL
    :param epg_id: The EPG ID
    :param kwargs: Optional arguments
    :return: The recording ID
    """
    data = {
        "initObj": construct_init_obj(**kwargs),
        "epgId": epg_id,
    }
    response = _session.post(f"{json_post_gw}?m=RecordAsset", json=data)
    response.raise_for_status()
    json_data = response.json()
    if json_data.get("status") != "OK":
        raise RecordingException(json_data.get("msg"), json_data.get("status"))
    return json_data.get("recordingID")


def delete_asset_recording(
    _session: Session, json_post_gw: str, recording_id: str, **kwargs
) -> bool:
    """
    Deletes a recording of the given recording ID.

    :param _session: requests.Session object
    :param json_post_gw: The JSON post gateway URL
    :param recording_id: The recording ID
    :param kwargs: Optional arguments
    :return: True if successful
    """
    data = {
        "initObj": construct_init_obj(**kwargs),
        "recordingID": recording_id,
    }
    response = _session.post(f"{json_post_gw}?m=DeleteAssetRecording", json=data)
    response.raise_for_status()
    json_data = response.json()
    if json_data.get("status") != "OK":
        raise RecordingException(json_data.get("msg"), json_data.get("status"))
    return True


def record_series_by_program_id(
    _session: Session, json_post_gw: str, epg_id: int, **kwargs
) -> str:
    """
    Creates a series recording of the given EPG ID.

    :param _session: requests.Session object
    :param json_post_gw: The JSON post gateway URL
    :param epg_id: The EPG ID
    :param kwargs: Optional arguments
    :return: The recording ID
    """
    data = {
        "initObj": construct_init_obj(**kwargs),
        "assetId": epg_id,
    }
    response = _session.post(f"{json_post_gw}?m=RecordSeriesByProgramId", json=data)
    response.raise_for_status()
    json_data = response.json()
    if json_data.get("status") != "OK":
        raise RecordingException(json_data.get("msg"), json_data.get("status"))
    return json_data.get("recordingID")
