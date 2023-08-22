import threading
from datetime import datetime, timezone
from time import mktime, strptime, time
from typing import Tuple
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
import xmltodict
from default import authenticate, get_available_files, prepare_session, replace_image
from requests import Session
from resources.lib.vodka import media_list, static

addon = xbmcaddon.Addon()
handle = f"[{addon.getAddonInfo('name')}]"


def get_path(is_epg: bool = False) -> str:
    """
    Check if the channel and epg path exists

    :param is_epg: Whether to check for the epg path
    :return: The path if it exists
    :raises IOError: If the path does not exist
    """
    path = addon.getSetting("channelexportpath")
    if is_epg:
        name = addon.getSetting("epgexportname")
    else:
        name = addon.getSetting("channelexportname")
    if not all([path, name]):
        return False
    if not xbmcvfs.exists(path):
        result = xbmcvfs.mkdirs(path)
        if not result:
            raise IOError(f"Failed to create directory {path}")
    # NOTE: we trust the user to enter a valid path
    # there is no sanitization
    return xbmcvfs.translatePath(f"{path}/{name}")


def export_channel_list(_session: Session) -> None:
    """
    Export channel list to an m3u file

    :param _session: requests.Session object
    :return: None
    """
    dialog = xbmcgui.Dialog()
    try:
        path = get_path()
    except IOError:
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30054),
            xbmcgui.NOTIFICATION_ERROR,
        )
        return
    if not all([addon.getSetting("username"), addon.getSetting("password")]):
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30055),
            xbmcgui.NOTIFICATION_ERROR,
        )
        return
    authenticate(_session)
    # print m3u header
    output = "#EXTM3U\n\n"
    channels = media_list.get_channel_list(
        _session, addon.getSetting("phoenixgw"), addon.getSetting("kstoken")
    )
    # sort channels by channel number
    channels.sort(
        key=lambda x: int(
            next(
                (
                    value.get("value", 0)
                    for key, value in x.get("metas", {}).items()
                    if key == "Channel number"
                ),
                0,
            )
        )
    )
    available_file_ids = []
    for channel in channels:
        media_files = [
            media_file
            for media_file in channel.get("mediaFiles")
            if media_file.get("type") in static.media_file_ids
        ]
        # sort media files that contain 'HD' earlier
        media_files.sort(key=lambda x: x.get("type").lower().find("hd"), reverse=True)
        if not media_files:
            continue
        media_file = media_files[0]["id"]
        available_file_ids.append(str(media_file))
    # check which channels are available
    available_file_ids = get_available_files(_session, available_file_ids)
    for channel in channels:
        channel_id = channel.get("id")
        if not channel_id:
            continue
        epg_id = next(
            (
                value.get("value", channel_id)
                for key, value in channel.get("metas", {}).items()
                if key == "EPG_GUID_ID"
            ),
            channel_id,
        )
        name = channel.get("name").strip()
        images = channel.get("images")
        image = None
        if images:
            image = next(
                (image for image in images if image.get("ratio") == "16:10"),
                images[0],
            )["url"]
            if addon.getSetting("webenabled"):
                image = replace_image(image)
        # get media file id
        media_files = [
            media_file
            for media_file in channel.get("mediaFiles")
            if media_file.get("type") in static.media_file_ids
            and media_file.get("id") in available_file_ids
        ]
        # sort media files that contain 'HD' earlier
        media_files.sort(key=lambda x: x.get("type").lower().find("hd"), reverse=True)
        if not media_files:
            continue
        media_file = media_files[0]["id"]
        # print channel data to m3u
        output += f'#EXTINF:-1 tvg-id="{epg_id}" tvg-name="{name}" tvg-logo="{image}" group-title="vodkatv" catchup="vod",{name}\n'
        query = {
            "action": "play_channel",
            "name": name,
            "icon": image,
            "id": channel_id,
            "extra": media_file,
            "pvr": ".pvr",  # hack to make Kodi recognize the stream as a PVR stream
        }
        url = f"plugin://{addon.getAddonInfo('id')}/?{urlencode(query)}"
        output += f"{url}\n\n"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(output)
    except IOError:
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30054),
            xbmcgui.NOTIFICATION_ERROR,
        )
        return
    dialog.notification(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(30056),
        xbmcgui.NOTIFICATION_INFO,
        sound=False,
    )


def voda_to_epg_time(voda_time: str) -> Tuple[str, int]:
    """
    Convert Voda time to EPG time format and unix timestamp.

    :param voda_time: Voda time format
    :return: EPG time format (strftime("%Y%m%d%H%M%S %z")), unix timestamp
    """
    # ie. 14/08/2023 21:45:00 -> 20230809144500 +0200
    try:
        voda_time = datetime.strptime(voda_time, "%d/%m/%Y %H:%M:%S")
        return voda_time.strftime("%Y%m%d%H%M%S %z"), int(
            voda_time.replace(tzinfo=timezone.utc).timestamp()
        )
    # https://bugs.python.org/issue27400
    except TypeError:
        voda_time = datetime.fromtimestamp(
            mktime(strptime(voda_time, "%d/%m/%Y %H:%M:%S"))
        )
        return voda_time.strftime("%Y%m%d%H%M%S %z"), int(
            voda_time.replace(tzinfo=timezone.utc).timestamp()
        )


def export_epg(
    _session: Session,
    from_time: int,
    to_time: int,
    utc_offset: int,
    kill_event: threading.Event = None,
):
    """
    Exports all EPG data between two timestamps to an XMLTV file.

    :param _session: requests.Session object
    :param from_time: Unix timestamp of the start time
    :param to_time: Unix timestamp of the end time
    :param utc_offset: UTC offset
    :param kill_event: threading.Event object to kill the thread (optional)
    :return: None
    """
    xbmc.log(
        f"{handle} Exporting EPG data from {from_time} days to +{to_time} days started",
        xbmc.LOGINFO,
    )
    dialog = xbmcgui.Dialog()
    try:
        path = get_path(is_epg=True)
    except IOError:
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30054),
            xbmcgui.NOTIFICATION_ERROR,
        )
        return
    if not all([addon.getSetting("username"), addon.getSetting("password")]):
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30055),
            xbmcgui.NOTIFICATION_ERROR,
        )
        return
    authenticate(_session)
    chunk_size = addon.getSettingInt("epgfetchinonereq")
    channels = media_list.get_channel_list(
        _session, addon.getSetting("phoenixgw"), addon.getSetting("kstoken")
    )
    channel_data = []
    epg_ids = {}
    program_data = []
    for channel in channels:
        # check if we need to abort
        if kill_event and kill_event.is_set():
            return
        epg_id = next(
            (
                value.get("value")
                for key, value in channel.get("metas", {}).items()
                if key == "EPG_GUID_ID"
            ),
            channel.get("id"),
        )
        if not epg_id:
            continue
        name = channel.get("name")
        images = channel.get("images")
        image = None
        if images:
            image = next(
                (image for image in images if image.get("ratio") == "16:10"),
                images[0],
            )["url"]
        # get media file id
        media_files = [
            media_file
            for media_file in channel.get("mediaFiles")
            if media_file.get("type") in static.media_file_ids
        ]
        # sort media files that contain 'HD' earlier
        media_files.sort(key=lambda x: x.get("type").lower().find("hd"), reverse=True)
        if not media_files:
            continue
        media_file = media_files[0]["id"]
        channel = {
            "@id": epg_id,
            "display-name": name,
            "icon": {"@src": image},
        }
        channel_data.append(channel)
        epg_ids[epg_id] = media_file
    # fetch EPG data in chunks
    for i in range(0, len(epg_ids.keys()), chunk_size):
        # check if we need to abort
        if kill_event and kill_event.is_set():
            return
        chunk = list(epg_ids.keys())[
            i : i + chunk_size
        ]  # TODO: look for a more efficient way
        channel_programs = media_list.get_epg_by_channel_ids(
            _session,
            addon.getSetting("jsonpostgw"),
            chunk,
            from_time,
            to_time,
            utc_offset,
            api_user=addon.getSetting("apiuser"),
            api_pass=addon.getSetting("apipass"),
            domain_id=addon.getSetting("domainid"),
            site_guid=addon.getSetting("siteguid"),
            platform=addon.getSetting("platform"),
            ud_id=addon.getSetting("devicekey"),
        )
        for channel in channel_programs:
            epg_channel_id = channel.get("EPG_CHANNEL_ID")
            if not epg_channel_id:
                continue
            programme_object = channel.get("EPGChannelProgrammeObject")
            for programme in programme_object:
                start_date = programme.get("START_DATE")
                end_date = programme.get("END_DATE")
                epg_programme_id = programme.get("EPG_ID")
                if not all([start_date, end_date]):
                    continue
                start_date, start_date_unix = voda_to_epg_time(start_date.strip())
                end_date, end_date_unix = voda_to_epg_time(end_date.strip())
                name = programme.get("NAME")
                description = programme.get("DESCRIPTION")
                epg_meta = programme.get("EPG_Meta", {})
                images = programme.get("EPG_PICTURES")
                image = None
                if images:
                    # sort images by PicWidth and PicHeight, prefer Ratio = bg
                    images.sort(
                        key=lambda x: (
                            x.get("PicWidth", 0),
                            x.get("PicHeight", 0),
                            x.get("Ratio", "") == "bg",
                        ),
                        reverse=True,
                    )
                    image = images[0].get("Url")
                    if addon.getSetting("webenabled"):
                        image = replace_image(image)
                year = next(
                    (
                        meta.get("Value")
                        for meta in epg_meta
                        if meta.get("Key") == "year"
                    ),
                    None,
                )
                episode = next(
                    (
                        meta.get("Value")
                        for meta in epg_meta
                        if meta.get("Key") == "episode num"
                    ),
                    None,
                )
                season = next(
                    (
                        meta.get("Value")
                        for meta in epg_meta
                        if meta.get("Key") == "season number"
                    ),
                    None,
                )
                episode_name = next(
                    (
                        meta.get("Value")
                        for meta in epg_meta
                        if meta.get("Key") == "episode name"
                    ),
                    None,
                )
                epg_tags = programme.get("EPG_TAGS")
                genres = [
                    tag.get("Value") for tag in epg_tags if tag.get("Key") == "genre"
                ]
                countries = [
                    tag.get("Value")
                    for tag in epg_tags
                    if tag.get("Key") == "country of production"
                ]
                actors = [
                    tag.get("Value") for tag in epg_tags if tag.get("Key") == "actors"
                ]
                directors = [
                    tag.get("Value") for tag in epg_tags if tag.get("Key") == "director"
                ]
                content_tags = [
                    tag.get("Value")
                    for tag in epg_tags
                    if tag.get("Key") == "contentTags"
                ]

                programme = {
                    "@start": start_date,
                    "@stop": end_date,
                    "@channel": epg_channel_id,
                    "title": {"@lang": "hu", "#text": name},
                    "desc": {"@lang": "hu", "#text": description},
                }
                catchup_url = f"plugin://{addon.getAddonInfo('id')}/?action=catchup&id={epg_programme_id}&cid={epg_ids[int(epg_channel_id)]}&start={start_date_unix}&end={end_date_unix}"
                to_catchup = False
                if static.recordable in content_tags:
                    catchup_url += "&rec=1"
                    to_catchup = True
                else:
                    catchup_url += "&rec=0"
                if static.restartable in content_tags:
                    catchup_url += "&res=1"
                    to_catchup = True
                else:
                    catchup_url += "&res=0"
                if to_catchup:
                    programme["@catchup-id"] = catchup_url
                if year:
                    programme["date"] = year
                # Prepare categories
                categories = [{"@lang": "hu", "#text": genre} for genre in genres]
                if categories:
                    programme["category"] = categories
                # Prepare countries
                countries = [{"@lang": "hu", "#text": country} for country in countries]
                if countries:
                    programme["country"] = countries
                # Prepare credits
                credits = {}
                actor_elements = [{"#text": actor} for actor in actors]
                if actor_elements:
                    credits["actor"] = actor_elements
                director_elements = [{"#text": director} for director in directors]
                if director_elements:
                    credits["director"] = director_elements
                if credits:
                    programme["credits"] = credits
                if image:
                    programme["icon"] = {"@src": image}
                if all([episode, season]):
                    programme["episode-num"] = {
                        "@system": "xmltv_ns",
                        "#text": f"{int(season) - 1}.{int(episode) - 1}.",
                    }
                if episode_name:
                    programme["sub-title"] = {"@lang": "hu", "#text": episode_name}
                program_data.append(programme)
    xmltv_data = {
        "tv": {
            "@generator-info-name": addon.getAddonInfo("name"),
            "@generator-info-url": f"plugin://{addon.getAddonInfo('id')}/",
            "channel": channel_data,
            "programme": program_data,
        }
    }
    # convert dict to XML and write to file
    with open(path, "w", encoding="utf-8") as f:
        xmltodict.unparse(xmltv_data, output=f, encoding="utf-8")
    if addon.getSettingBool("epgnotifoncompletion"):
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30082),
            xbmcgui.NOTIFICATION_INFO,
        )
    addon.setSetting("lastepgupdate", str(int(time())))


def get_utc_offset() -> int:
    """
    Get the UTC offset in hours from the local time

    :return: UTC offset in hours
    """
    now = datetime.now()
    utc_now = datetime.utcnow()
    utc_offset = now - utc_now
    return round(utc_offset.total_seconds() / 3600)


class EPGUpdaterThread(threading.Thread):
    """
    A thread that updates the EPG data in the background.
    """

    def __init__(
        self,
        _session: Session,
        from_time: int,
        to_time: int,
        utc_offset: int,
        frequency: int,
        last_updated: int,
    ):
        super().__init__()
        self._session = _session
        self.from_time = from_time
        self.to_time = to_time
        self.utc_offset = utc_offset
        self.frequency = frequency
        self.last_updated = last_updated
        self.killed = threading.Event()
        self.failed_count = 0

    @property
    def now(self) -> int:
        """Returns the current time in unix format"""
        return int(time())

    def run(self):
        """
        EPG update thread's main loop.
        """
        while not self.killed.is_set():
            xbmc.log(
                f"{handle} EPG update: next update in {min(self.frequency, self.frequency - (self.now - self.last_updated))} seconds",
                xbmc.LOGINFO,
            )
            self.killed.wait(
                min(self.frequency, self.frequency - (self.now - self.last_updated))
            )
            if not self.killed.is_set() and not self.failed_count > addon.getSettingInt(
                "epgfetchtries"
            ):
                try:
                    export_epg(
                        self._session,
                        -self.from_time,
                        self.to_time,
                        self.utc_offset,
                        self.killed,
                    )
                    self.last_updated = self.now
                    self.failed_count = 0
                except Exception as e:
                    self.failed_count += 1
                    xbmc.log(
                        f"{handle} EPG update failed: {e}",
                        xbmc.LOGERROR,
                    )
                    self.killed.wait(5)

    def stop(self):
        """
        Sets stop event to the thread.
        """
        self.killed.set()


def main_service() -> EPGUpdaterThread:
    """
    Main service loop.
    """
    if not addon.getSettingBool("autoupdateepg"):
        xbmc.log(
            f"{handle} EPG autoupdate disabled, won't start", level=xbmc.LOGWARNING
        )
        return
    if not all([addon.getSetting("username"), addon.getSetting("password")]):
        xbmc.log(f"{handle} No credentials set, won't start", level=xbmc.LOGWARNING)
        return
    _session = prepare_session()
    authenticate(_session)
    if not addon.getSetting("kstoken"):
        xbmc.log(f"{handle} No KSToken set, won't start", level=xbmc.LOGWARNING)
        return
    # get epg settings
    from_time = addon.getSettingInt("epgfrom")
    to_time = addon.getSettingInt("epgto")
    utc_offset = get_utc_offset()
    frequency = addon.getSettingInt("epgupdatefrequency")
    last_update = addon.getSetting("lastepgupdate")
    if not last_update:
        last_update = 0
    else:
        last_update = int(last_update)
    if not all([from_time, to_time, frequency]):
        xbmc.log(f"{handle} EPG settings not set, won't start", level=xbmc.LOGWARNING)
        return
    # start epg updater thread
    epg_updater = EPGUpdaterThread(
        _session, from_time, to_time, utc_offset, frequency, last_update
    )
    epg_updater.start()
    xbmc.log(f"{handle} Export EPG service started", level=xbmc.LOGINFO)
    return epg_updater


if __name__ == "__main__":
    main_service()
