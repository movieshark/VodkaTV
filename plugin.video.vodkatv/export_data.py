import threading
from datetime import datetime, timezone
from time import mktime, strptime, time
from typing import Tuple
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from default import (
    authenticate,
    get_available_files,
    get_tag,
    prepare_session,
    replace_image,
)
from requests import Session
from resources.lib.vodka import media_list, static
from resources.lib.utils import voda_to_epg_time


def get_path(addon: xbmcaddon.Addon(), is_epg: bool = False) -> str:
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


def export_channel_list(addon: xbmcaddon.Addon(), _session: Session) -> None:
    """
    Export channel list to an m3u file

    :param _session: requests.Session object
    :return: None
    """
    dialog = xbmcgui.Dialog()
    try:
        path = get_path(addon)
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
    authenticate(_session, addon)
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


def enc_xml(text) -> str:
    """
    Method to encode an XML string

    :param text: string to encode
    :return: encoded string
    """
    to_replace = {
        "&": "&amp;",
        "'": "&apos;",
        '"': "&quot;",
        ">": "&gt;",
        "<": "&lt;",
    }
    translation_table = str.maketrans(to_replace)
    return text.translate(translation_table)


def export_epg(
    addon: xbmcaddon.Addon,
    _session: Session,
    from_time: int,
    to_time: int,
    utc_offset: int,
    kill_event: threading.Event = None,
) -> None:
    """
    Exports all EPG data between two timestamps to an XMLTV file.

    :param _session: requests.Session object
    :param from_time: Unix timestamp of the start time
    :param to_time: Unix timestamp of the end time
    :param utc_offset: UTC offset
    :param kill_event: threading.Event object to kill the thread (optional)
    :return: None
    """
    handle = f"[{addon.getAddonInfo('name')}]"
    xbmc.log(
        f"{handle} Exporting EPG data from {from_time} days to +{to_time} days started",
        xbmc.LOGINFO,
    )
    dialog = xbmcgui.Dialog()
    try:
        path = get_path(addon, is_epg=True)
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
    authenticate(_session, addon)
    temp_path = path + ".tmp"
    chunk_size = addon.getSettingInt("epgfetchinonereq")
    channels = media_list.get_channel_list(
        _session, addon.getSetting("phoenixgw"), addon.getSetting("kstoken")
    )
    with open(temp_path, "w", encoding="utf-8") as f:
        # print XML header
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')
        # print addont info
        f.write(
            f"<tv generator-info-name=\"{enc_xml(addon.getAddonInfo('name'))}\" generator-info-url=\"plugin://{addon.getAddonInfo('id')}/\">"
        )
        epg_ids = {}
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
            media_files.sort(
                key=lambda x: x.get("type").lower().find("hd"), reverse=True
            )
            if not media_files:
                continue
            media_file = media_files[0]["id"]
            # print channel data to XML
            f.write(f'<channel id="{enc_xml(str(epg_id))}">')
            f.write(f'<display-name lang="hu">{enc_xml(name)}</display-name>')
            if image:
                if isinstance(image, str) and addon.getSetting("webenabled"):
                    # i have encountered a case where image was bytes
                    image = replace_image(image)
                f.write(f'<icon src="{enc_xml(image)}" />')
            f.write("</channel>")
            epg_ids[epg_id] = media_file
        # fetch EPG data in chunks
        for i in range(0, len(epg_ids.keys()), chunk_size):
            # check if we need to abort
            if kill_event and kill_event.is_set():
                return
            chunk = list(epg_ids.keys())[i : i + chunk_size]
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
                        if isinstance(image, str) and addon.getSetting("webenabled"):
                            # i have encountered a case where image was bytes
                            image = replace_image(image)
                    year = get_tag(epg_meta, "year")
                    episode = get_tag(epg_meta, "episode num")
                    season = get_tag(epg_meta, "season number")
                    episode_name = get_tag(epg_meta, "episode name")
                    epg_tags = programme.get("EPG_TAGS")
                    genres = [
                        tag.get("Value")
                        for tag in epg_tags
                        if tag.get("Key") == "genre"
                    ]
                    countries = [
                        tag.get("Value")
                        for tag in epg_tags
                        if tag.get("Key") == "country of production"
                    ]
                    actors = [
                        tag.get("Value")
                        for tag in epg_tags
                        if tag.get("Key") == "actors"
                    ]
                    directors = [
                        tag.get("Value")
                        for tag in epg_tags
                        if tag.get("Key") == "director"
                    ]
                    content_tags = [
                        tag.get("Value")
                        for tag in epg_tags
                        if tag.get("Key") == "contentTags"
                    ]
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
                    f.write(
                        f'<programme start="{enc_xml(start_date)}" stop="{enc_xml(end_date)}" channel="{enc_xml(epg_channel_id)}"'
                    )
                    if to_catchup:
                        f.write(f' catchup-id="{enc_xml(catchup_url)}"')
                    f.write(">")
                    f.write(f'<title lang="hu">{enc_xml(name)}</title>')
                    f.write(f'<desc lang="hu">{enc_xml(description)}</desc>')
                    if year:
                        f.write(f"<date>{enc_xml(year)}</date>")
                    # Prepare categories
                    categories = [
                        f'<category lang="hu">{enc_xml(genre)}</category>'
                        for genre in genres
                    ]
                    if categories:
                        f.write("".join(categories))
                    # Prepare countries
                    countries = [
                        f'<country lang="hu">{enc_xml(country)}</country>'
                        for country in countries
                    ]
                    if countries:
                        f.write("".join(countries))
                    # Prepare credits
                    credits = {}
                    actor_elements = [
                        f"<actor>{enc_xml(actor)}</actor>" for actor in actors
                    ]
                    if actor_elements:
                        credits["actor"] = actor_elements
                    director_elements = [
                        f"<director>{enc_xml(director)}</director>"
                        for director in directors
                    ]
                    if director_elements:
                        credits["director"] = director_elements
                    if credits:
                        f.write("".join(credits))
                    if image:
                        f.write(f'<icon src="{enc_xml(image)}" />')
                    if all([episode, season]):
                        f.write(
                            f'<episode-num system="xmltv_ns">{enc_xml(str(int(season) - 1))}.{enc_xml(str(int(episode) - 1))}.</episode-num>'
                        )
                    if episode_name:
                        f.write(
                            f'<sub-title lang="hu">{enc_xml(episode_name)}</sub-title>'
                        )
                    f.write("</programme>")
        f.write("</tv>")
    # move temp file to final file
    xbmcvfs.rename(temp_path, path)
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
        addon: xbmcaddon.Addon,
        _session: Session,
        from_time: int,
        to_time: int,
        utc_offset: int,
        frequency: int,
        last_updated: int,
    ):
        super().__init__()
        self.addon = addon
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

    @property
    def handle(self) -> str:
        """Returns the addon handle"""
        return f"[{self.addon.getAddonInfo('name')}]"

    def run(self) -> None:
        """
        EPG update thread's main loop.
        """
        while not self.killed.is_set():
            xbmc.log(
                f"{self.handle} EPG update: next update in {min(self.frequency, self.frequency - (self.now - self.last_updated))} seconds",
                xbmc.LOGINFO,
            )
            self.killed.wait(
                min(self.frequency, self.frequency - (self.now - self.last_updated))
            )
            if (
                not self.killed.is_set()
                and not self.failed_count > self.addon.getSettingInt("epgfetchtries")
            ):
                try:
                    export_epg(
                        self.addon,
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
                        f"{self.handle} EPG update failed: {e}",
                        xbmc.LOGERROR,
                    )
                    self.killed.wait(5)

    def stop(self) -> None:
        """
        Sets stop event to the thread.
        """
        self.killed.set()


def main_service(addon: xbmcaddon.Addon) -> EPGUpdaterThread:
    """
    Main service loop.
    """
    handle = f"[{addon.getAddonInfo('name')}]"
    if not addon.getSettingBool("autoupdateepg"):
        xbmc.log(
            f"{handle} EPG autoupdate disabled, won't start", level=xbmc.LOGWARNING
        )
        return
    if not all([addon.getSetting("username"), addon.getSetting("password")]):
        xbmc.log(f"{handle} No credentials set, won't start", level=xbmc.LOGWARNING)
        return
    _session = prepare_session()
    authenticate(_session, addon)
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
        addon, _session, from_time, to_time, utc_offset, frequency, last_update
    )
    epg_updater.start()
    xbmc.log(f"{handle} Export EPG service started", level=xbmc.LOGINFO)
    return epg_updater


if __name__ == "__main__":
    main_service(xbmcaddon.Addon())
