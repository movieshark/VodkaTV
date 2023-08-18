import threading
from sys import argv
from urllib.parse import parse_qsl

import requests
import xbmc
import xbmcaddon
from export_data import main_service as e_main_service
from resources.lib.vodka import static
from web_service import main_service as w_main_service

timeout = 5
addon = xbmcaddon.Addon()
handle = f"[{addon.getAddonInfo('name')}]"

xbmc.log(f"{handle} Playback Manager Service started", xbmc.LOGINFO)


def report_playback(
    params: dict, user_agent: str, playing_state: str, position: float
) -> None:
    """
    Sends playback status to the VTV player reporting API

    :param params: The parameters of the playback
    :param user_agent: The user agent to use
    :param playing_state: The state of the playback (ie. hit, play, pause, stop etc.)
    :param position: The position of the playback
    """
    data = {
        "initObj": {
            "ApiUser": addon.getSetting("apiuser"),
            "ApiPass": addon.getSetting("apipass"),
            "Platform": addon.getSetting("platform"),
            "Locale": {
                "LocaleUserState": "Unknown",
                "LocaleCountry": "null",
                "LocaleDevice": "null",
                "LocaleLanguage": static.locale_language,
            },
            "DomainID": int(addon.getSetting("domainid")),
            "SiteGuid": addon.getSetting("siteguid"),
            "UDID": addon.getSetting("devicekey"),
            "Token": addon.getSetting("kstoken"),
        },
        "assetID": params.get("assetId"),
        "fileID": params.get("id"),
        "assetType": params.get("assetType"),
        "PlayerAssetData": {
            "action": playing_state,
            "location": position,
        },
    }
    xbmc.log(
        f"{handle} Playback Manager Service: sending bookmark request: {playing_state}",
        xbmc.LOGDEBUG,
    )
    try:
        response = requests.post(
            f"{addon.getSetting('jsonpostgw')}?m=AssetBookmark",
            json=data,
            headers={"User-Agent": user_agent},
            timeout=3,
        )
        xbmc.log(
            f"{handle} Playback Manager Service: bookmark request data: {str(data).replace(addon.getSetting('kstoken'), '***')}",
            xbmc.LOGDEBUG,
        )
        xbmc.log(
            f"{handle} Playback Manager Service: bookmark request response: [{response.status_code}] {response.text}",
            xbmc.LOGDEBUG,
        )
    except requests.exceptions.RequestException as e:
        xbmc.log(
            f"{handle} Playback Manager Service: bookmark request error: {e}",
            xbmc.LOGERROR,
        )


class PlaybackStatReporterThread(threading.Thread):
    def __init__(self, user_agent, report_params):
        threading.Thread.__init__(self)
        self.user_agent = user_agent
        self.report_params = report_params
        self.player = xbmc.Player()
        self.report_killed = threading.Event()
        self.last_position = 0

    def run(self):
        while not self.report_killed.is_set():
            self.report_killed.wait(timeout=30)
            if not self.report_killed.is_set() and self.player.isPlayingVideo():
                self.last_position = self.player.getTime()
                report_playback(
                    self.report_params, self.user_agent, "hit", self.last_position
                )

    def stop(self):
        self.report_killed.set()


class XBMCPlayer(xbmc.Player):
    def __init__(self, *args, **kwargs):
        xbmc.Player.__init__(self, *args, **kwargs)
        self.user_agent = addon.getSetting("useragent")
        self.played_url = ""
        self.report_params = {}
        self.keepalive_thread = None
        self.report_thread = None

    def onPlayBackStarted(self):
        # we need the playback stop when the user switches to another video
        # and doesn't stop inbetween, so we can send a STOP request
        self.onPlayBackStopped()
        timeout_counter = 0
        while not self.isPlayingVideo() and timeout_counter < 10:
            timeout_counter += 1
            xbmc.sleep(1000)
        if self.isPlayingVideo() and self.getVideoInfoTag().getTrailer().startswith(
            "plugin://plugin.video.vodkatv/"
        ):
            self.played_url = self.getPlayingFile()
            xbmc.log(
                f"{handle} Playback Manager Service: started playing {self.played_url}",
                xbmc.LOGINFO,
            )
            try:
                query = self.getVideoInfoTag().getTrailer().split("?", 1)[1]
                self.report_params = dict(parse_qsl(query, keep_blank_values=True))
                report_playback(
                    self.report_params, self.user_agent, "play", self.getTime()
                )
                if self.report_thread and self.report_thread.is_alive():
                    self.stop_report_thread()
                self.report_thread = PlaybackStatReporterThread(
                    self.user_agent, self.report_params
                )
                self.report_thread.start()
            except IndexError:
                xbmc.log(
                    f"{handle} Playback Manager Service: failed to parse query string",
                    xbmc.LOGERROR,
                )

    def onPlayBackStopped(self) -> None:
        last_position = 0
        if self.report_thread and self.report_thread.is_alive():
            last_position = self.report_thread.last_position
            self.stop_report_thread()
            xbmc.log(
                f"{handle} Playback Manager Service: stopped reporting thread",
                xbmc.LOGINFO,
            )
        if self.report_params:
            report_playback(self.report_params, self.user_agent, "stop", last_position)
            self.report_params = {}

    def onPlayBackError(self) -> None:
        return self.onPlayBackStopped()

    def onPlayBackEnded(self) -> None:
        return self.onPlayBackStopped()

    def stop_report_thread(self):
        if self.report_thread and self.report_thread.is_alive():
            self.report_thread.stop()
            try:
                self.report_thread.join()
            except RuntimeError:
                pass
        self.report_thread = None

    def onPlayBackPaused(self) -> None:
        if self.report_thread and self.report_thread.is_alive():
            self.stop_report_thread()
            xbmc.log(
                f"{handle} Playback Manager Service: stopped reporting thread",
                xbmc.LOGINFO,
            )
        if self.report_params:
            report_playback(
                self.report_params, self.user_agent, "pause", self.getTime()
            )

    def onPlayBackResumed(self) -> None:
        if self.report_thread and self.report_thread.is_alive():
            self.stop_report_thread()
            xbmc.log(
                f"{handle} Playback Manager Service: stopped reporting thread",
                xbmc.LOGINFO,
            )
        if self.report_params:
            report_playback(self.report_params, self.user_agent, "play", self.getTime())
            self.report_thread = PlaybackStatReporterThread(
                self.user_agent, self.report_params
            )
            self.report_thread.start()
            xbmc.log(
                f"{handle} Playback Manager Service: started reporting thread",
                xbmc.LOGINFO,
            )


if __name__ == "__main__":
    monitor = xbmc.Monitor()
    player = XBMCPlayer()
    export_service = e_main_service()
    web_service = w_main_service()
    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break
    player.stop_report_thread()
    xbmc.log(f"{handle} Playback Manager Service stopped", xbmc.LOGINFO)
    if export_service and export_service.is_alive():
        export_service.stop()
        try:
            export_service.join()
        except RuntimeError:
            pass
        xbmc.log(f"{handle} Export EPG service stopped", level=xbmc.LOGINFO)
    if web_service and web_service.is_alive():
        web_service.stop()
        try:
            web_service.join()
        except RuntimeError:
            pass
        xbmc.log(f"{handle} Web service stopped", level=xbmc.LOGINFO)
