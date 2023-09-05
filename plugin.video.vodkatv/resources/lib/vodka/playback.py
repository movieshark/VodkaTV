from requests import Session

from . import static
from .misc import construct_init_obj


class PlaybackException(Exception):
    """
    Exception raised when playback fails.
    """

    def __init__(self, message: str, code: int):
        self.message = message
        self.code = code


def get_playback_obj(
    _session: Session,
    gateway_phoenix_url: str,
    ks_token: str,
    media_id: int,
    asset_file_id: int,
    **kwargs,
) -> dict:
    """
    Get the playback object for a media item. This is used to get the playback URL and
     optionally the DRM details. Right now MPEG-DASH is hardcoded.

    :param _session: requests.Session object
    :param gateway_phoenix_url: The gateway phoenix URL
    :param ks_token: The ks token
    :param media_id: The ID of the media item
    :param kwargs: Optional arguments
    :return: The playback object
    """
    api_version = kwargs.get("api_version", static.api_version)
    asset_type = kwargs.get("asset_type", "media")
    data = {
        "assetId": media_id,
        "assetType": asset_type,
        "contextDataParams": {
            "objectType": f"{static.get_ott_platform_name()}PlaybackContextOptions",
            "assetFileIds": asset_file_id,
            "context": "PLAYBACK" if asset_type == "media" else "CATCHUP",
            "urlType": "DIRECT",
        },
        "apiVersion": api_version,
        "ks": ks_token,
    }
    response = _session.post(
        f"{gateway_phoenix_url}/asset/action/getPlaybackContext",
        json=data,
    )
    response.raise_for_status()
    result = response.json().get("result", {})
    if result.get("error"):
        raise PlaybackException(result["error"]["message"], result["error"]["code"])
    return result


def get_recording_playback_object(
    _session: Session,
    json_post_gw: str,
    recording_id: str,
    media_id: int,
    referrer: str = "NPVR_TYPE_968",
    **kwargs,
):
    """
    Get the playback object for a recording. This is used to get the playback URL.

    :param _session: requests.Session object
    :param json_post_gw: The JSON post gateway URL
    :param recording_id: The ID of the recording
    :param media_id: The ID of the media item
    :param referrer: The referrer
    :param kwargs: Optional arguments
    """
    data = {
        "initObj": construct_init_obj(**kwargs),
        "mediaFileID": int(media_id),
        "recordingId": recording_id,
        "referrer": referrer,
    }
    response = _session.post(f"{json_post_gw}?m=GetNPVRLicensedLink", json=data)
    response.raise_for_status()
    if response.json().get("status") != "OK":
        raise PlaybackException(response.json().get("status"), 0)
    return response.json()
