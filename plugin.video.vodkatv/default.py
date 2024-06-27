from json import dumps, loads
from random import choice
from socket import gaierror
from sys import argv
from time import time
from urllib.parse import parse_qsl, quote, urlencode, urlparse

import inputstreamhelper  # type: ignore
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
from requests import ConnectionError, HTTPError, Session
from resources.lib.myvodka import login as myvodka_login
from resources.lib.myvodka import vtv
from resources.lib.utils import static as utils_static
from resources.lib.utils import unix_to_date, voda_to_epg_time
from resources.lib.utils.dns_resolver import get_vtv_ip_from_mapi, resolve_domain
from resources.lib.vodka import (
    devices,
    enums,
    login,
    media_list,
    misc,
    recording,
    static,
)
from resources.lib.vodka.playback import (
    PlaybackException,
    get_playback_obj,
    get_recording_playback_object,
)

addon = xbmcaddon.Addon()
addon_name = addon.getAddonInfo("name")
HOME_ID = 10000  # https://kodi.wiki/view/Window_IDs


def add_item(plugin_prefix, handle, name, action, is_directory, **kwargs) -> None:
    """
    Adds an item to the Kodi listing
    """
    url = f"{plugin_prefix}?action={action}"
    item = xbmcgui.ListItem(label=name)
    info_labels = {}
    if kwargs.get("description"):
        info_labels.update({"plot": kwargs["description"]})
    arts = {}
    if kwargs.get("icon"):
        arts.update({"thumb": kwargs["icon"], "icon": kwargs["icon"]})
    if kwargs.get("fanart"):
        arts.update({"fanart": kwargs["fanart"]})
        item.setProperty("Fanart_Image", kwargs["fanart"])
    if kwargs.get("type"):
        info_labels.update({"mediatype": kwargs["type"]})
    if kwargs.get("id"):
        url += "&id=%s" % (kwargs["id"])
    if kwargs.get("year"):
        info_labels.update({"year": kwargs["year"]})
    if kwargs.get("episode"):
        info_labels.update({"episode": kwargs["episode"]})
    if kwargs.get("season"):
        info_labels.update({"season": kwargs["season"]})
    if kwargs.get("show_name"):
        info_labels.update({"tvshowtitle": kwargs["show_name"]})
    if kwargs.get("genre"):
        info_labels.update({"genre": kwargs["genre"]})
    if kwargs.get("country"):
        info_labels.update({"country": kwargs["country"]})
    if kwargs.get("director"):
        info_labels.update({"director": kwargs["director"]})
    if kwargs.get("cast"):
        info_labels.update({"cast": kwargs["cast"]})
    if kwargs.get("mpaa"):
        info_labels.update({"mpaa": kwargs["mpaa"]})
    if kwargs.get("duration"):
        info_labels.update({"duration": kwargs["duration"]})
    if kwargs.get("extra"):
        url += "&extra=%s" % (kwargs["extra"])
    if kwargs.get("is_livestream"):
        # see https://forum.kodi.tv/showthread.php?pid=2743328#pid2743328 to understand this hack
        # useful for livestreams to not to mark the item as watched + adds switch to channel context menu item
        # NOTE: MUST BE THE LAST PARAMETER in the URL
        url += "&pvr=.pvr"
    if not is_directory:
        item.setProperty("IsPlayable", "true")
    item.setArt(arts)
    item.setInfo(type="Video", infoLabels=info_labels)
    try:
        item.setContentLookup(False)
    except:
        pass  # if it's a local dir, no need for it
    ctx_menu = []
    if kwargs.get("refresh"):
        ctx_menu.append((addon.getLocalizedString(30036), "Container.Refresh"))
    if kwargs.get("ctx_menu"):
        ctx_menu.extend(kwargs["ctx_menu"])
    item.addContextMenuItems(ctx_menu)
    xbmcplugin.addDirectoryItem(int(handle), url, item, is_directory)


def prepare_session() -> Session:
    """
    Prepare a requests session for use within the addon. Also sets
     the user agent to a random desktop user agent if it is not set.

    :return: The prepared session.
    """
    user_agent = addon.getSetting("useragent")
    if not user_agent:
        addon.setSetting("useragent", choice(utils_static.desktop_user_agents))
        user_agent = addon.getSetting("useragent")
    session = Session()
    session.headers.update({"User-Agent": user_agent})
    return session


def authenticate(session: Session, addon_from_thread: xbmcaddon.Addon = None) -> None:
    """
    Handles initial login, device registration and token refresh.
    Also generates the device key if it is not set.

    :param session: The requests session.
    :return: None
    """
    addon_local = addon_from_thread or addon
    if not all(
        [addon_local.getSetting("username"), addon_local.getSetting("password")]
    ):
        return
    if not addon_local.getSetting("devicekey"):
        device_id = misc.generate_ud_id()
        addon_local.setSetting("devicekey", device_id)
    ks_expiry = addon_local.getSetting("ksexpiry")
    if ks_expiry and int(ks_expiry) > int(time()):
        return  # KS token is valid so no need to reauthenticate
    prog_dialog = xbmcgui.DialogProgress()
    prog_dialog.create(addon_name)
    # KS login
    # refresh KS token if it expired
    if ks_expiry and int(ks_expiry) < time():
        try:
            prog_dialog.update(85, addon_local.getLocalizedString(30016))
            (
                access_token,
                refresh_token,
                expiration_date,
                refresh_expiration_date,
            ) = login.refresh_access_token(
                session,
                addon_local.getSetting("jsonpostgw"),
                addon_local.getSetting("ksrefreshtoken"),
                ud_id=addon_local.getSetting("devicekey"),
                api_user=addon_local.getSetting("apiuser"),
                api_pass=addon_local.getSetting("apipass"),
                platform=addon_local.getSetting("platform"),
                device_brand_id=enums.DeviceBrandId.PCMAC.value,
                token=addon_local.getSetting("kstoken"),
                domain_id=addon_local.getSetting("domainid"),
                site_guid=addon_local.getSetting("siteguid"),
            )
            prog_dialog.close()
        except HTTPError as e:
            # check if the error is 403
            # if it is, then the refresh token is invalid
            # so we need to reauthenticate
            if e.response.status_code == 403:
                addon_local.setSetting("ksexpiry", "")
                authenticate(session, addon_local)
                return
            else:
                raise e
    # fresh login
    else:
        # reset MyVodka expiry
        xbmcgui.Window(HOME_ID).setProperty("kodi.vodka.myvodka_expiry", "")
        prog_dialog.update(50, addon_local.getLocalizedString(30022))
        pkey, vodka_config = login.get_config(
            session, addon_local.getSetting("devicekey")
        )
        json_post_gw = next(
            (
                item["JsonGW"]
                for item in vodka_config["params"]["Gateways"]
                if item.get("JsonGW")
            ),
            None,
        )
        phoenix_gw = next(
            (
                item["JsonGW"]
                for item in vodka_config["params"]["GatewaysPhoenix"]
                if item.get("JsonGW")
            ),
            None,
        )
        license_url_base = next(
            (
                item["SSPLicenseServerUrl"]
                for item in vodka_config["params"]["NagraSettings"]
                if item.get("SSPLicenseServerUrl")
            ),
            None,
        )
        tenant_id = next(
            (
                item["TenantID"]
                for item in vodka_config["params"]["NagraSettings"]
                if item.get("TenantID")
            ),
            None,
        )
        init_obj = vodka_config["params"]["InitObj"]
        api_user = next(
            (item["ApiUser"] for item in init_obj if item.get("ApiUser")), None
        )
        api_pass = next(
            (item["ApiPass"] for item in init_obj if item.get("ApiPass")), None
        )
        platform = next(
            (item["Platform"] for item in init_obj if item.get("Platform")), None
        )
        if not all(
            [
                json_post_gw,
                phoenix_gw,
                license_url_base,
                tenant_id,
                api_user,
                api_pass,
                platform,
            ]
        ):
            prog_dialog.close()
            raise ValueError("Missing required parameters.")
        addon_local.setSetting("jsonpostgw", json_post_gw)
        addon_local.setSetting("phoenixgw", phoenix_gw)
        addon_local.setSetting("licenseurlbase", license_url_base)
        addon_local.setSetting("tenantid", tenant_id)
        addon_local.setSetting("apiuser", api_user)
        addon_local.setSetting("apipass", api_pass)
        addon_local.setSetting("platform", platform)
        # we don't store the public key as it's not needed after a login
        prog_dialog.update(75, addon_local.getLocalizedString(30023))
        try:
            login_response, access_token, refresh_token = login.sign_in(
                session,
                json_post_gw,
                addon_local.getSetting("devicekey"),
                api_user,
                api_pass,
                platform,
                addon_local.getSetting("username"),
                addon_local.getSetting("password"),
                pkey,
            )
        except login.LoginError as e:
            prog_dialog.close()
            dialog = xbmcgui.Dialog()
            dialog.ok(
                addon_name,
                addon_local.getLocalizedString(30025).format(message=e.message),
            )
            return
        # NOTE: tokens have a pipe character and the expiration date appended to them here
        access_token, expiration_date = access_token.split("|")
        refresh_token, refresh_expiration_date = refresh_token.split("|")
        site_guid = login_response["SiteGuid"]
        domain_id = login_response["DomainID"]
        addon_local.setSetting("domainid", str(domain_id))
        addon_local.setSetting("siteguid", site_guid)
        # register device
        prog_dialog.update(90, addon_local.getLocalizedString(30024))
        try:
            devices.register_device(
                session,
                json_post_gw,
                addon_local.getSetting("devicenick"),
                ud_id=addon_local.getSetting("devicekey"),
                api_user=api_user,
                api_pass=api_pass,
                platform=platform,
                device_brand_id=enums.DeviceBrandId.PCMAC.value,
                token=access_token,
                domain_id=domain_id,
                site_guid=site_guid,
            )
        except devices.DeviceRegistrationError as e:
            prog_dialog.close()
            dialog = xbmcgui.Dialog()
            dialog.ok(
                addon_name,
                addon_local.getLocalizedString(30025).format(message=e.message),
            )
            return
        prog_dialog.close()
        # show success dialog
        dialog = xbmcgui.Dialog()
        dialog.ok(addon_name, addon_local.getLocalizedString(30026))
    addon_local.setSetting("kstoken", access_token)
    addon_local.setSetting("ksrefreshtoken", refresh_token)
    addon_local.setSetting("ksexpiry", str(expiration_date))
    addon_local.setSetting("ksrefreshexpiry", str(refresh_expiration_date))


def main_menu() -> None:
    """
    Renders the main menu of the addon.

    :return: None
    """
    # channel list
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30027),
        action="channel_list",
        is_directory=True,
    )
    # recordings
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30096),
        action="recordings",
        is_directory=True,
        extra="0",  # page number
    )
    # device list (kaltura)
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30043),
        action="device_list",
        is_directory=True,
    )
    # device list (MyVodka)
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30128),
        action="myvodka_device_list",
        is_directory=True,
    )
    # settings
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30112),
        action="settings",
        is_directory=True,
    )
    # about
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30053),
        action="about",
        is_directory=True,
    )
    xbmcplugin.endOfDirectory(int(argv[1]))


def get_available_files(session: Session, file_ids: list) -> list:
    """
    Get the list of available file IDs.

    :param session: The requests session.
    :param file_ids: The list of file IDs.
    :return: The list of available file IDs.
    """
    # split the list of channels into chunks of 100 in the for loop
    # to avoid sending too many requests at once
    available_channels = []
    for i in range(0, len(file_ids), 100):
        # NOTE: original app does this in chunks of 10
        # but that seems to be too slow, so we do it in chunks of 100
        chunk = file_ids[i : min(i + 100, len(file_ids))]
        response = media_list.product_price_list(
            session,
            addon.getSetting("phoenixgw"),
            chunk,
            addon.getSetting("kstoken"),
        )
        for product in response:
            # NOTE: values here are only guesses
            if product.get("purchaseStatus") in [
                "subscription_purchased",
                "free",
                "ppv_purchased",
                "collection_purchased",
                "pre_paid_purchased",
                "subscription_purchased_wrong_currency",
            ]:
                available_channels.append(product.get("fileId"))
    return available_channels


def replace_image(image_url: str) -> str:
    image_url = urlparse(image_url)
    hostname = image_url.hostname
    scheme = image_url.scheme
    image_url = image_url._replace(scheme="http")._replace(
        netloc=f"127.0.0.1:{addon.getSetting('webport')}"
    )
    params = {
        "h": hostname,
        "s": scheme,
    }
    return image_url.geturl() + "?" + urlencode(params)


def channel_list(session: Session) -> None:
    """
    Renders the list of live channels.

    :param session: The requests session.
    :return: None
    """
    channels = media_list.get_channel_list(
        session, addon.getSetting("phoenixgw"), addon.getSetting("kstoken")
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
    potential_file_ids = {}
    no_epg_list = []
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
        epg_id = channel.get("metas", {}).get("EPG_GUID_ID", {}).get("value")
        if not epg_id:
            no_epg_list.append(str(media_file))
        else:
            potential_file_ids[epg_id] = str(media_file)
    # check which channels are available also from non-EPG sources
    available_file_ids = get_available_files(
        session, list(potential_file_ids.values()) + no_epg_list
    )
    epgs = []
    if addon.getSettingInt("epgonchannels") != 4:  # EPG is enabled
        if not addon.getSettingBool("showallchannels"):
            # drop channels that are not available
            for channel_id, media_file_id in list(potential_file_ids.items()):
                if int(media_file_id) not in available_file_ids:
                    potential_file_ids.pop(channel_id)
        # get EPG data in bulk
        chunk_size = addon.getSettingInt("epgfetchinonereq")
        for i in range(0, len(potential_file_ids), chunk_size):
            chunk = list(potential_file_ids.keys())[i : i + chunk_size]
            channel_programs = media_list.get_epg_by_channel_ids(
                session,
                addon.getSetting("jsonpostgw"),
                chunk,
                0,
                1,
                2,
                api_user=addon.getSetting("apiuser"),
                api_pass=addon.getSetting("apipass"),
                domain_id=addon.getSetting("domainid"),
                site_guid=addon.getSetting("siteguid"),
                platform=addon.getSetting("platform"),
                ud_id=addon.getSetting("devicekey"),
            )
            # append the programs to the EPG list
            epgs.extend(channel_programs)
    # TODO: get API version
    for channel in channels:
        channel_id = channel.get("id")
        if not channel_id:
            continue
        name = channel.get("name")
        images = channel.get("images")
        image = None
        if images:
            image = next(
                (image for image in images if image.get("ratio") == "16:10"),
                images[0],
            )["url"]
            if addon.getSettingBool("webenabled"):
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
        playable = False
        if not media_files and not addon.getSettingBool("showallchannels"):
            continue
        elif not media_files and addon.getSettingBool("showallchannels"):
            name = f"[COLOR red]{name}[/COLOR]"  # channel not subscribed
        else:
            playable = True
            media_file = media_files[0]["id"]
        epg_id = channel.get("metas", {}).get("EPG_GUID_ID", {}).get("value")
        description = ""
        if addon.getSettingInt("epgonchannels") != 4:  # EPG is enabled
            epg = next(
                (
                    epg.get("EPGChannelProgrammeObject", {})
                    for epg in epgs
                    if epg.get("EPG_CHANNEL_ID") == str(epg_id)
                ),
                None,
            )
            if epg and addon.getSettingInt("epgonchannels") == 0:
                # current program description and
                # all next programs with start time and title

                # find current program
                current_program = next(
                    (
                        program
                        for program in epg
                        if voda_to_epg_time(program.get("START_DATE"))[1]
                        < time()
                        < voda_to_epg_time(program.get("END_DATE"))[1]
                    ),
                    None,
                )
                if current_program:
                    name += f"[CR][COLOR gray]{current_program.get('NAME')}[/COLOR]"
                    description += current_program.get("DESCRIPTION") + "\n\n"
                # find next programs
                next_programs = [
                    program
                    for program in epg
                    if voda_to_epg_time(program.get("START_DATE"))[1] > time()
                ]
                for program in next_programs:
                    # add start time in bold and title
                    description += (
                        "[B]"
                        + unix_to_date(voda_to_epg_time(program.get("START_DATE"))[1])
                        + "[/B] "
                        + program.get("NAME")
                        + "\n"
                    )
            elif (
                epg and addon.getSettingInt("epgonchannels") == 1
            ):  # next programs first, then current
                # find next programs
                next_programs = [
                    program
                    for program in epg
                    if voda_to_epg_time(program.get("START_DATE"))[1] > time()
                ]
                for program in next_programs:
                    # add start time in bold and title
                    description += (
                        "[B]"
                        + unix_to_date(voda_to_epg_time(program.get("START_DATE"))[1])
                        + "[/B] "
                        + program.get("NAME")
                        + "\n"
                    )
                description += "\n"
                # find current program
                current_program = next(
                    (
                        program
                        for program in epg
                        if voda_to_epg_time(program.get("START_DATE"))[1]
                        < time()
                        < voda_to_epg_time(program.get("END_DATE"))[1]
                    ),
                    None,
                )
                if current_program:
                    name += f"[CR][COLOR gray]{current_program.get('NAME')}[/COLOR]"
                    description += current_program.get("DESCRIPTION") + "\n"
            elif (
                epg and addon.getSettingInt("epgonchannels") == 2
            ):  # only current program
                # find current program
                current_program = next(
                    (
                        program
                        for program in epg
                        if voda_to_epg_time(program.get("START_DATE"))[1]
                        < time()
                        < voda_to_epg_time(program.get("END_DATE"))[1]
                    ),
                    None,
                )
                if current_program:
                    name += f"[CR][COLOR gray]{current_program.get('NAME')}[/COLOR]"
                    description += current_program.get("DESCRIPTION")
            elif (
                epg and addon.getSettingInt("epgonchannels") == 3
            ):  # only next programs
                # find next programs
                next_programs = [
                    program
                    for program in epg
                    if voda_to_epg_time(program.get("START_DATE"))[1] > time()
                ]
                for program in next_programs:
                    # add start time in bold and title
                    description += (
                        "[B]"
                        + unix_to_date(voda_to_epg_time(program.get("START_DATE"))[1])
                        + "[/B] "
                        + program.get("NAME")
                        + "\n"
                    )
        add_item(
            plugin_prefix=argv[0],
            handle=argv[1],
            name=name,
            action="play_channel" if playable else "dummy",
            is_directory=False,
            id=channel_id,
            icon=image,
            is_livestream=True,
            refresh=True,
            extra=media_file if playable else None,
            description=description,
        )
    xbmcplugin.endOfDirectory(int(argv[1]))
    xbmcplugin.setContent(int(argv[1]), "videos")


def try_register_device(session: Session) -> None:
    """
    Tries to register the device if it is not registered for playback.

    :param session: The requests session.
    :return: None
    """
    try:
        devices.register_device(
            session,
            addon.getSetting("jsonpostgw"),
            addon.getSetting("devicenick"),
            ud_id=addon.getSetting("devicekey"),
            api_user=addon.getSetting("apiuser"),
            api_pass=addon.getSetting("apipass"),
            platform=addon.getSetting("platform"),
            device_brand_id=enums.DeviceBrandId.PCMAC.value,
            token=addon.getSetting("kstoken"),
            domain_id=addon.getSetting("domainid"),
            site_guid=addon.getSetting("siteguid"),
        )
    except devices.DeviceRegistrationError as e:
        dialog = xbmcgui.Dialog()
        dialog.ok(addon_name, addon.getLocalizedString(30025).format(message=e.message))


def _gen_mgr_params(playback_obj: list, asset_type: str) -> str:
    """
    Generates the parameters for playback manager's statistics report.

    :param playback_obj: playback object
    :return: parameters for playback manager
    """
    try:
        params = {
            "id": playback_obj["id"],
            "assetId": playback_obj["assetId"],
        }
        if asset_type == "media":
            params["assetType"] = "MEDIA"
        elif asset_type == "epg":
            params["assetType"] = "CATCHUP"
        elif asset_type == "recording":
            params["assetType"] = "NPVR"
    except (KeyError, IndexError):
        return ""
    return urlencode(params)


def get_tag(tags: list, key: str) -> str:
    """
    Gets the tag value from the list of tags.

    :param tags: The list of tags.
    :param key: The tag key.
    :return: The tag value.
    """
    tag = next(
        (tag["Value"] for tag in tags if tag["Key"] == key),
        None,
    )
    return tag


def play(
    session: Session,
    media_id: int,
    asset_file_id: int,
    asset_type: str = "media",
    tries: int = 0,
) -> None:
    """
    Fetches the playback object and attempts to start the playback
     using the chosen DRM system.

    :param session: The requests session.
    :param media_id: The media ID.
    :param asset_file_id: The asset file ID.
    :return: None
    """
    try:
        playback_obj = get_playback_obj(
            session,
            addon.getSetting("phoenixgw"),
            addon.getSetting("kstoken"),
            media_id,
            asset_file_id,
            asset_type=asset_type,
        )
    except PlaybackException as e:
        if e.code == "1003":  # Device not in household
            if tries < 2:
                try_register_device(session)
                return play(session, media_id, asset_file_id, asset_type, tries + 1)
            else:
                dialog = xbmcgui.Dialog()
                dialog.ok(
                    addon_name,
                    addon.getLocalizedString(30147),
                )
            return
        elif e.code == "3037":  # catchup buffer limit reached
            dialog = xbmcgui.Dialog()
            dialog.ok(
                addon_name,
                addon.getLocalizedString(30095),
            )
            return
        else:
            dialog = xbmcgui.Dialog()
            dialog.ok(
                addon_name, addon.getLocalizedString(30025).format(message=e.message)
            )
            return
    # get the first source object
    playback_obj = next(
        (source for source in playback_obj.get("sources", [])),
        None,
    )
    if not playback_obj:
        xbmcgui.Dialog().ok(addon_name, addon.getLocalizedString(30030))
        return
    # get the first entry with scheme=CUSTOM_DRM from the drm list
    drm = next(
        (
            drm
            for drm in playback_obj.get("drm", [])
            if drm.get("scheme") == "CUSTOM_DRM"
        ),
        None,
    )
    if not drm:
        xbmcgui.Dialog().ok(
            addon_name,
            addon.getLocalizedString(30031),
        )
        return
    nv_authorizations = drm.get("data")
    if not nv_authorizations:
        xbmcgui.Dialog().ok(
            addon_name,
            addon.getLocalizedString(30032),
        )
        return
    # construct 'trailer' parameters for playback manager
    trailer_params = _gen_mgr_params(playback_obj, asset_type)
    manifest_url = urlparse(playback_obj.get("url"))
    handle_playback(manifest_url, nv_authorizations, trailer_params)


def handle_playback(
    manifest_url: str, nv_authorizations: str, trailer_params: str
) -> None:
    """
    Helper function that handles the playback of a media or recording.

    :param manifest_url: The manifest URL.
    :param nv_authorizations: The NV authorizations token.
    :param trailer_params: The trailer parameters.
    :return: None
    """

    headers = {}
    if addon.getSettingBool("usedoh"):
        # extract host from domain
        hostname = manifest_url.hostname
        try:
            ip = resolve_domain(addon.getSetting("dohaddress"), hostname)
        except:
            # we handle the IP resolving error below
            pass
        if not ip:
            if addon.getSettingBool("usemapifallbackdns"):
                try:
                    user_agent = addon_name + " v" + addon.getAddonInfo("version")
                    ip = get_vtv_ip_from_mapi(user_agent)
                except:
                    xbmcgui.Dialog().ok(
                        addon_name,
                        addon.getLocalizedString(30146).format(
                            url=manifest_url.geturl()
                        ),
                    )
                    return
            xbmcgui.Dialog().ok(
                addon_name,
                addon.getLocalizedString(30035).format(url=manifest_url.geturl()),
            )
            return
        # replace hostname with IP and specify port 80
        manifest_url = manifest_url._replace(netloc=f"{ip}:80")
        # replace https with http
        manifest_url = manifest_url._replace(scheme="http")
        headers["Host"] = hostname
    else:
        # replace https with http
        manifest_url = manifest_url._replace(scheme="http")
        # replace port 443 with 80
        manifest_url = manifest_url._replace(
            netloc=manifest_url.netloc.replace("443", "80")
        )
    # handle redirect as Kodi's player can't
    try:
        response = session.head(
            manifest_url.geturl(), allow_redirects=False, headers=headers
        )
    except ConnectionError as e:
        original_exception = e
        while not isinstance(original_exception, gaierror) and (
            original_exception.__cause__ or original_exception.__context__
        ):
            original_exception = (
                original_exception.__cause__ or original_exception.__context__
            )
        # if it's a DNS resolution error, we try to resolve using MAPI
        if (
            addon.getSettingBool("usemapifallbackdns")
            and isinstance(original_exception, gaierror)
            and original_exception.errno == -2
        ):
            try:
                user_agent = addon_name + " v" + addon.getAddonInfo("version")
                ip = get_vtv_ip_from_mapi(user_agent)
            except Exception as e:
                xbmcgui.Dialog().ok(
                    addon_name,
                    addon.getLocalizedString(30146).format(url=manifest_url.geturl()),
                )
                return
            headers["Host"] = manifest_url.hostname
            manifest_url = manifest_url._replace(netloc=f"{ip}:80")
            try:
                response = session.head(
                    manifest_url.geturl(), allow_redirects=False, headers=headers
                )
            except Exception as e:
                xbmcgui.Dialog().ok(
                    addon_name,
                    addon.getLocalizedString(30146).format(url=manifest_url.geturl()),
                )
                return
        else:
            raise e
    manifest_url = response.headers.get("Location")
    drm_system = addon.getSettingInt("drmsystem")
    # construct playback item
    is_helper = inputstreamhelper.Helper("mpd", drm="com.widevine.alpha")
    play_item = xbmcgui.ListItem(path=manifest_url)
    play_item.setContentLookup(False)
    play_item.setInfo("video", {"trailer": argv[0] + "?" + trailer_params})
    play_item.setMimeType("application/dash+xml")
    play_item.setProperty("inputstream", is_helper.inputstream_addon)
    play_item.setProperty("inputstream.adaptive.manifest_type", "mpd")
    play_item.setProperty(
        "inputstream.adaptive.manifest_headers",
        urlencode({"User-Agent": addon.getSetting("useragent")}),
    )
    if drm_system == 0:  # Widevine
        if not is_helper.check_inputstream():
            xbmcgui.Dialog().ok(
                addon_name,
                addon.getLocalizedString(30050),
            )
            return
        license_headers = {
            "User-Agent": addon.getSetting("useragent"),
            "Content-Type": "application/octet-stream",  # NOTE: important
            "nv-authorizations": nv_authorizations,
        }
        license_url = f"{addon.getSetting('licenseurlbase')}/{addon.getSetting('tenantid')}/wvls/contentlicenseservice/v1/licenses|{urlencode(license_headers)}|R{{SSM}}|"
        play_item.setProperty("inputstream.adaptive.license_type", "com.widevine.alpha")
    elif drm_system == 1:  # PlayReady
        license_headers = {
            "User-Agent": addon.getSetting("useragent"),
            "Content-Type": "text/xml",
            "SOAPAction": "http://schemas.microsoft.com/DRM/2007/03/protocols/AcquireLicense",
            "nv-authorizations": nv_authorizations,
        }
        license_url = f"{addon.getSetting('licenseurlbase')}/{addon.getSetting('tenantid')}/prls/contentlicenseservice/v1/licenses|{urlencode(license_headers)}|R{{SSM}}|"
        play_item.setProperty(
            "inputstream.adaptive.license_type", "com.microsoft.playready"
        )
    play_item.setProperty(
        "inputstream.adaptive.license_key",
        license_url,
    )
    xbmcplugin.setResolvedUrl(int(argv[1]), True, listitem=play_item)


def play_recording(session: Session, recording_id: int, media_id: list) -> None:
    """
    Method used to play recordings. Unfortunately works very differently from
    live streams and catchups.

    :param session: The requests session.
    :param recording_id: The recording ID.
    :param media_id: The media ID.
    :return: None
    """
    media_id, media_type = loads(media_id.replace("'", '"'))
    referrer = static.npvr_types.get(media_type, list(static.npvr_types.keys())[0])
    try:
        playback_object = get_recording_playback_object(
            session,
            addon.getSetting("jsonpostgw"),
            recording_id,
            int(media_id),
            referrer=referrer,
            api_user=addon.getSetting("apiuser"),
            api_pass=addon.getSetting("apipass"),
            domain_id=addon.getSetting("domainid"),
            site_guid=addon.getSetting("siteguid"),
            platform=addon.getSetting("platform"),
            ud_id=addon.getSetting("devicekey"),
            token=addon.getSetting("kstoken"),
        )
    except PlaybackException as e:
        drm_token = xbmcgui.Window(xbmcgui.getCurrentWindowId()).setProperty(
            "kodi.vodka.drm_token", ""
        )
        try_register_device(session)
        dialog = xbmcgui.Dialog()
        dialog.ok(
            addon_name,
            e.message,
        )
        return
    main_url = playback_object.get("mainUrl")
    if not main_url:
        dialog = xbmcgui.Dialog()
        dialog.ok(
            addon_name,
            addon.getLocalizedString(30030),
        )
        return
    # check if we have a cached DRM token and if it's still valid
    drm_token = xbmcgui.Window(xbmcgui.getCurrentWindowId()).getProperty(
        "kodi.vodka.drm_token"
    )
    if not drm_token or misc.get_token_exp(drm_token) < time():
        # get DRM token
        device_info = devices.get_device(
            session,
            addon.getSetting("phoenixgw"),
            addon.getSetting("kstoken"),
        )
        drm_token = device_info.get("drm", {}).get("data")
        if not drm_token:
            dialog = xbmcgui.Dialog()
            dialog.ok(
                addon_name,
                addon.getLocalizedString(30032),
            )
            return
        xbmcgui.Window(xbmcgui.getCurrentWindowId()).setProperty(
            "kodi.vodka.drm_token", drm_token
        )
    trailer_data = {
        "id": recording_id,
        "assetId": media_id,
    }
    trailer_params = _gen_mgr_params(trailer_data, "recording")
    manifest_url = urlparse(main_url)
    handle_playback(manifest_url, drm_token, trailer_params)


def get_recordings(session: Session, page_num: int) -> None:
    """
    Renders the list of recordings.

    :param session: The requests session.
    :param page_num: The page number.
    :return: None
    """
    # ugly channel cache
    channels = xbmcgui.Window(HOME_ID).getProperty("kodi.vodka.channels")
    epg_ids = {}
    if channels:
        epg_ids = loads(channels)
    else:
        # upon first run, fetch the channel list into a dict where the key
        # is the epg id and the value is a list with the media file id and pvr type
        channels = media_list.get_channel_list(
            session, addon.getSetting("phoenixgw"), addon.getSetting("kstoken")
        )
        for channel in channels:
            epg_id = str(
                next(
                    (
                        value.get("value")
                        for key, value in channel.get("metas", {}).items()
                        if key == "EPG_GUID_ID"
                    ),
                    channel.get("id"),
                )
            )
            if not epg_id:
                continue
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
            media_file = media_files[0]
            epg_ids[epg_id] = [str(media_file["id"]), media_file["type"]]

        xbmcgui.Window(HOME_ID).setProperty("kodi.vodka.channels", dumps(epg_ids))
    page_num = int(page_num)
    recordings = media_list.get_recordings(
        session,
        addon.getSetting("jsonpostgw"),
        page_num,
        api_user=addon.getSetting("apiuser"),
        api_pass=addon.getSetting("apipass"),
        domain_id=addon.getSetting("domainid"),
        site_guid=addon.getSetting("siteguid"),
        platform=addon.getSetting("platform"),
        ud_id=addon.getSetting("devicekey"),
        token=addon.getSetting("kstoken"),
    )
    if not recordings:
        dialog = xbmcgui.Dialog()
        dialog.ok(addon_name, addon.getLocalizedString(30103))
        return
    for recording in recordings:
        recording_id = recording.get("RecordingID")
        if not recording_id:
            continue
        name = recording.get("NAME")
        description = recording.get("DESCRIPTION")
        channel_name = recording.get("ChannelName")
        epg_channel_id = recording.get("EPG_CHANNEL_ID")
        image = recording.get("PIC_URL")
        images = recording.get("EPG_PICTURES")
        cover_image = None
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
            cover_image = images[0].get("Url")
            if isinstance(cover_image, str) and addon.getSetting("webenabled"):
                # i have encountered a case where image was bytes
                cover_image = replace_image(cover_image)
        if isinstance(image, str) and addon.getSettingBool("webenabled"):
            image = replace_image(image)
        epg_tags = recording.get("EPG_TAGS")
        start_time = get_tag(epg_tags, "startTime")
        end_time = get_tag(epg_tags, "endTime")
        booking_time = get_tag(epg_tags, "bookingTime")
        delete_time = get_tag(epg_tags, "deleteTime")
        duration = get_tag(epg_tags, "duration")
        year = get_tag(epg_tags, "year")
        series_name = get_tag(epg_tags, "seriesName")
        season_number = get_tag(epg_tags, "seasonNumber")
        episode_number = get_tag(epg_tags, "episode")
        content_tags = next(
            (tag["Value"] for tag in epg_tags if tag["Key"] == "contentTags"),
            "",
        ).split(" ")
        is_recordable = False
        if static.recordable in content_tags:
            is_recordable = True
        else:
            name = f"[COLOR red]{name}[/COLOR]"
        # construct description
        description += f"\n\n{addon.getLocalizedString(30097)}: {channel_name}"
        if start_time:
            description += f"\n{addon.getLocalizedString(30099)}: {unix_to_date(int(start_time) // 1000)}"
        if end_time:
            description += f"\n{addon.getLocalizedString(30100)}: {unix_to_date(int(end_time) // 1000)}"
        if booking_time:
            description += f"\n{addon.getLocalizedString(30101)}: {unix_to_date(int(booking_time) // 1000)}"
        if delete_time:
            description += f"\n{addon.getLocalizedString(30102)}: {unix_to_date(int(delete_time) // 1000)}"
        ctx_menu = [
            (
                addon.getLocalizedString(30104),
                f"RunPlugin({argv[0]}?action=del_recording&recording_id={recording_id})",
            )
        ]
        # add item
        add_item(
            plugin_prefix=argv[0],
            handle=argv[1],
            name=name,
            description=description,
            action="play_recording" if is_recordable else "dummy",
            is_directory=False,
            id=recording_id,
            icon=image,
            is_livestream=False,
            refresh=True,
            year=year,
            episode=episode_number,
            season=season_number,
            show_name=series_name,
            duration=duration,
            extra=str(epg_ids.get(epg_channel_id)),
            ctx_menu=ctx_menu,
            fanart=cover_image,
        )
    # add pagination
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30098) + " >",
        action="recordings",
        is_directory=True,
        extra=str(page_num + 1),
    )
    xbmcplugin.setContent(int(argv[1]), "episodes")
    xbmcplugin.endOfDirectory(int(argv[1]))


def device_list(session: Session) -> None:
    """
    List devices.

    :param session: requests session
    :return: None
    """

    # request device list
    device_list, _ = devices.get_devices(
        session,
        addon.getSetting("phoenixgw"),
        addon.getSetting("kstoken"),
    )
    # sort by lastActivityTime descending
    device_list.sort(key=lambda x: x.get("lastActivityTime", 0), reverse=True)
    # request currently streaming devices
    streaming_devices, _ = devices.get_streaming_devices(
        session,
        addon.getSetting("phoenixgw"),
        addon.getSetting("kstoken"),
    )
    # create a lookup table for brands
    brand_lookup = devices.get_brands(
        session,
        addon.getSetting("phoenixgw"),
        addon.getSetting("kstoken"),
    )
    for device in device_list:
        brand_id = device.get("brandId")
        brand = brand_lookup.get(brand_id, "unknown")
        name = device.get("name")
        if not name:
            name = brand
        else:
            name = f"{name} ({brand})"
        device_id = device.get("udid")
        if device_id == addon.getSetting("devicekey"):
            name += f" [{addon.getLocalizedString(30037)}]"
        activated_on = unix_to_date(device.get("activatedOn", 0))
        last_activity = unix_to_date(device.get("lastActivityTime", 0))
        household = device.get("householdId")
        state = device.get("state")
        description = (
            f"{addon.getLocalizedString(30011)}: {device_id}\n"
            f"{addon.getLocalizedString(30039)}: {activated_on}\n"
            f"{addon.getLocalizedString(30040)}: {last_activity}\n"
            f"{addon.getLocalizedString(30041)}: {household}\n"
            f"{addon.getLocalizedString(30042)}: {state}"
        )
        asset_id, asset_type = next(
            (
                (
                    streaming_device.get("asset", {}).get("id"),
                    streaming_device.get("asset", {}).get("type"),
                )
                for streaming_device in streaming_devices
                if streaming_device.get("udid") == device.get("udid")
            ),
            (None, None),
        )
        if asset_id:
            name = f"[COLOR=red]{addon.getLocalizedString(30115)} | {name}[/COLOR]"
            media = media_list.get_media_by_id(
                session,
                addon.getSetting("phoenixgw"),
                addon.getSetting("kstoken"),
                asset_id,
            )
            if media:
                name += f" - {media.get('name')}"
                description += (
                    f"\n{addon.getLocalizedString(30115)}: {media.get('name')}"
                    f"\n{addon.getLocalizedString(30116)}: {asset_type}"
                )
        ctx_menu = []
        if brand in ["PC/MAC", "Android Tablet", "Android Smartphone"]:
            # NOTE: dumb whitelisting, but we don't want the STB and
            # other unknown devices to be deleted
            ctx_menu = [
                (
                    addon.getLocalizedString(30038),
                    f"RunPlugin({argv[0]}?action=del_device&device_id={device_id})",
                )
            ]
        add_item(
            plugin_prefix=argv[0],
            handle=argv[1],
            name=name,
            description=description,
            ctx_menu=ctx_menu,
            refresh=True,
            action="dummy",  # clicking should do nothing
            is_directory=True,
        )
    xbmcplugin.endOfDirectory(int(argv[1]))


def delete_device(session: Session, device_id: str) -> None:
    """
    Delete a device permanently.

    :param session: requests session
    :param device_id: device id
    :return: None
    """

    dialog = xbmcgui.Dialog()
    if dialog.yesno(addon_name, addon.getLocalizedString(30044)):
        try:
            result = devices.delete_device(
                session,
                addon.getSetting("phoenixgw"),
                addon.getSetting("kstoken"),
                device_id,
            )
        except devices.DeviceDeletionError as e:
            dialog.ok(addon_name, str(e))
            return
        if result == True:
            if addon.getSetting("devicekey") == device_id:
                addon.setSetting("devicekey", "")
            dialog.ok(addon_name, addon.getLocalizedString(30045))
        else:
            dialog.ok(
                addon_name, addon.getLocalizedString(30025).format(message=result)
            )
        xbmc.executebuiltin("Container.Refresh")


def prepare_myvodka_session() -> Session:
    """
    Prepares a requests session for MyVodka.

    :return: requests session
    """
    session = Session()
    session.headers.update(
        {
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/4.11.0",
            "Connection": "Keep-Alive",
        }
    )
    return session


def vodka_authenticate() -> None:
    """
    Handles login to MyVodka.

    :return: None
    """
    session = prepare_myvodka_session()

    ox_auth_url = addon.getSetting("oxauthurl")
    ox_auth_client_id = addon.getSetting("oxauthclientid")
    ox_auth_client_secret = addon.getSetting("oxauthclientsecret")
    ox_auth_authorization = addon.getSetting("oxauthauthorization")
    public_api_host = addon.getSetting("publicapihost")
    public_api_client_id = addon.getSetting("publicapiclientid")

    # check if all settings are set
    if not all(
        [
            ox_auth_url,
            ox_auth_client_id,
            ox_auth_client_secret,
            ox_auth_authorization,
            public_api_host,
            public_api_client_id,
        ]
    ):
        dialog = xbmcgui.Dialog()
        dialog.ok(addon_name, addon.getLocalizedString(30135))
        addon.openSettings()
        exit()

    # check if we have a token and if it's still valid
    expiry = xbmcgui.Window(HOME_ID).getProperty("kodi.vodka.myvodka_expiry")
    if not expiry or int(expiry) < int(time()):
        # show progress dialog
        dialog = xbmcgui.DialogProgress()
        dialog.create(addon_name, addon.getLocalizedString(30137))
        try:
            response = myvodka_login.oxauth_login(
                session,
                ox_auth_url,
                ox_auth_client_id,
                ox_auth_client_secret,
                addon.getSetting("username"),
                addon.getSetting("password"),
                ox_auth_authorization,
            )
        except myvodka_login.LoginException as e:
            dialog = xbmcgui.Dialog()
            dialog.ok(addon_name, addon.getLocalizedString(30025).format(message=e))
            exit()
        access_token = response["access_token"]
        dialog.update(50, addon.getLocalizedString(30138))
        response = myvodka_login.publicapi_login(
            session,
            f"{public_api_host}/oauth2/token",
            public_api_client_id,
            access_token,
        )
        access_token = response["access_token"]
        expiry = response["issued_at"] + response["expires_in"]
        subscription_id = response.get("id_profile_svc_response", {}).get(
            "selectedSubscription", {}
        )["id"]
        dialog.update(75, addon.getLocalizedString(30141))
        response = myvodka_login.list_subscriptions(
            session,
            f"{public_api_host}/mva-api/customerAPI/v1/accountAndSubscription",
            f"Bearer {access_token}",
            subscription_id,  # default subscription goes here
        )
        services = response.get("myServices", [])
        subscriptions = []
        for service in services:
            subscriptions = service.get("subscriptions", [])
            # filter to type: TV
            subscriptions = [
                subscription
                for subscription in subscriptions
                if subscription["type"] == "TV"
            ]
            if subscriptions:
                break
        if not subscriptions:
            dialog.close()
            dialog = xbmcgui.Dialog()
            dialog.ok(addon_name, addon.getLocalizedString(30142))
            exit()
        dialog.close()
        if len(subscriptions) < 1:
            # show picker dialog
            dialog = xbmcgui.Dialog()
            subscription_names = [
                f"{subscription['name']} ({subscription['longAddress']})"
                for subscription in subscriptions
            ]
            index = dialog.select(
                addon.getLocalizedString(30143),
                subscription_names,
            )
            if index == -1:
                exit()
        else:
            index = 0
        subscription = subscriptions[index]
        subscription_id = subscription["id"]
        xbmcgui.Window(HOME_ID).setProperty("kodi.vodka.myvodka_expiry", str(expiry))
        xbmcgui.Window(HOME_ID).setProperty(
            "kodi.vodka.myvodka_access_token", access_token
        )
        xbmcgui.Window(HOME_ID).setProperty(
            "kodi.vodka.myvodka_individual_id", subscription_id
        )
    session.close()


def vodka_device_list() -> None:
    """
    Handles login to MyVodka if necessary and renders the device list.

    :param session: requests session
    :return: None
    """
    vodka_authenticate()
    session = prepare_myvodka_session()

    access_token = xbmcgui.Window(HOME_ID).getProperty(
        "kodi.vodka.myvodka_access_token"
    )
    individual_id = xbmcgui.Window(HOME_ID).getProperty(
        "kodi.vodka.myvodka_individual_id"
    )
    # request device list
    device_list = vtv.get_devices(
        session,
        f"{addon.getSetting('publicapihost')}/mva-api/productAPI/v2/vtv",
        f"Bearer {access_token}",
        individual_id,
    )

    connected_devices = device_list.get("connectedDevices", [])

    for device in connected_devices:
        device_id = device.get("id")
        device_name = device.get("name")
        device_type = device.get("type")
        description = f"{addon.getLocalizedString(30011)}: {device_id}\n{addon.getLocalizedString(30116)}: {device_type}"
        add_item(
            plugin_prefix=argv[0],
            handle=argv[1],
            name=device_name if device_name else device_id,
            description=description,
            action="dummy",  # clicking should do nothing
            is_directory=True,
            ctx_menu=[
                (
                    addon.getLocalizedString(30038),
                    f"RunPlugin({argv[0]}?action=del_vodka_device&device={quote(dumps(device))})",
                ),
                (
                    addon.getLocalizedString(30136),
                    f"RunPlugin({argv[0]}?action=rename_vodka_device&device={quote(dumps(device))})",
                ),
            ],
            refresh=True,
        )
    session.close()
    xbmcplugin.endOfDirectory(int(argv[1]))


def rename_vodka_device(device: str) -> None:
    """
    Rename a MyVodka device.

    :param device_id: device id (udid)
    :return: None
    """
    # prompt for new name
    dialog = xbmcgui.Dialog()
    device_data = loads(device)
    device_name = device_data["name"]
    new_name = dialog.input(
        addon.getLocalizedString(30140),
        device_name,
        type=xbmcgui.INPUT_TYPE_TEXT,
    )
    if not new_name:
        return
    # rename device
    vodka_authenticate()
    session = prepare_myvodka_session()
    access_token = xbmcgui.Window(HOME_ID).getProperty(
        "kodi.vodka.myvodka_access_token"
    )
    individual_id = xbmcgui.Window(HOME_ID).getProperty(
        "kodi.vodka.myvodka_individual_id"
    )
    device_id = device_data["id"]
    device_data["name"] = new_name
    try:
        if vtv.edit_device(
            session,
            f"{addon.getSetting('publicapihost')}/mva-api/productAPI/v2/vtv/device/{device_id}",
            f"Bearer {access_token}",
            individual_id,
            device_data,
        ):
            dialog.ok(addon_name, addon.getLocalizedString(30139))
    except Exception as e:
        dialog.ok(addon_name, addon.getLocalizedString(30025).format(message=e))
    session.close()
    xbmc.executebuiltin("Container.Refresh")


def delete_vodka_device(device: str) -> None:
    """
    Delete a MyVodka device.

    :param device_id: device id (udid)
    :return: None
    """
    vodka_authenticate()
    session = prepare_myvodka_session()
    access_token = xbmcgui.Window(HOME_ID).getProperty(
        "kodi.vodka.myvodka_access_token"
    )
    individual_id = xbmcgui.Window(HOME_ID).getProperty(
        "kodi.vodka.myvodka_individual_id"
    )
    device_data = loads(device)
    device_id = device_data["id"]
    dialog = xbmcgui.Dialog()
    try:
        if vtv.delete_device(
            session,
            f"{addon.getSetting('publicapihost')}/mva-api/productAPI/v2/vtv/device/{device_id}",
            f"Bearer {access_token}",
            individual_id,
        ):
            dialog.ok(addon_name, addon.getLocalizedString(30045))
    except Exception as e:
        dialog.ok(addon_name, addon.getLocalizedString(30025).format(message=e))
    session.close()
    xbmc.executebuiltin("Container.Refresh")


def update_epg(_session: Session) -> None:
    """
    Update the EPG file manually.

    :param _session: requests session
    :return: None
    """
    # local import should be fine
    # since it's not used often
    from export_data import export_epg, get_utc_offset

    ks_expiry = addon.getSetting("ksexpiry")
    dialog = xbmcgui.Dialog()
    if ks_expiry and int(ks_expiry) < int(time()):
        # can't update EPG if the token is expired
        # and due to a Kodi bug, when settings are opened
        # we cannot refresh the token
        dialog.ok(addon_name, addon.getLocalizedString(30094))
        return

    # get epg settings
    from_time = addon.getSetting("epgfrom")
    to_time = addon.getSetting("epgto")
    utc_offset = get_utc_offset()

    if not all([from_time, to_time]):
        dialog.ok(addon_name, addon.getLocalizedString(30083))
        return
    dialog.notification(
        addon_name,
        f"{addon.getLocalizedString(30084)}: -{from_time} {addon.getLocalizedString(30086)} - +{to_time} {addon.getLocalizedString(30086)}",
    )
    export_epg(addon, _session, "-" + from_time, to_time, utc_offset)


def catchup(
    session: Session,
    media_id: int,
    asset_file_id: int,
    start: int,
    stop: int,
    recordable: bool,
    restartable: bool,
) -> None:
    """
    Catchup handler. Decide whether the playback of a certain item is possible or not.

    :param session: requests session
    :param media_id: media id
    :param asset_file_id: asset file id
    :param start: start time (unix time)
    :param stop: stop time (unix time)
    :param recordable: whether the item is recordable or not
    :param restartable: whether the item is restartable or not
    :return: None
    """
    dialog = xbmcgui.Dialog()
    # if its recordable and the title is live now or was in the past, then we can play it
    if recordable and int(start) <= time():
        # if it is live now, ask if they want to record
        if time() <= int(stop):
            choice = dialog.yesnocustom(
                addon_name,
                addon.getLocalizedString(30107),
                customlabel=addon.getLocalizedString(30108),
                nolabel=addon.getLocalizedString(30109),
                yeslabel=addon.getLocalizedString(30110),
            )
            if choice == 0:  # record
                try:
                    recording.record_asset(
                        session,
                        addon.getSetting("jsonpostgw"),
                        media_id,
                        api_user=addon.getSetting("apiuser"),
                        api_pass=addon.getSetting("apipass"),
                        domain_id=addon.getSetting("domainid"),
                        site_guid=addon.getSetting("siteguid"),
                        platform=addon.getSetting("platform"),
                        ud_id=addon.getSetting("devicekey"),
                        token=addon.getSetting("kstoken"),
                    )
                except recording.RecordingException as e:
                    if e.status == "AssetAlreadyScheduled":
                        return dialog.ok(
                            addon_name,
                            addon.getLocalizedString(30113),
                        )
                    return dialog.ok(
                        addon_name,
                        addon.getLocalizedString(30025).format(message=e.status),
                    )
                return dialog.ok(addon_name, addon.getLocalizedString(30111))
            elif choice == 1:  # record series
                try:
                    recording.record_series_by_program_id(
                        session,
                        addon.getSetting("jsonpostgw"),
                        media_id,
                        api_user=addon.getSetting("apiuser"),
                        api_pass=addon.getSetting("apipass"),
                        domain_id=addon.getSetting("domainid"),
                        site_guid=addon.getSetting("siteguid"),
                        platform=addon.getSetting("platform"),
                        ud_id=addon.getSetting("devicekey"),
                        token=addon.getSetting("kstoken"),
                    )
                except recording.RecordingException as e:
                    if e.status == "Unknown":
                        return dialog.ok(
                            addon_name,
                            addon.getLocalizedString(30114),
                        )
                    return dialog.ok(
                        addon_name,
                        addon.getLocalizedString(30025).format(message=e.status),
                    )
                return dialog.ok(addon_name, addon.getLocalizedString(30111))
            # if the user cancels or presses the custom button, we can play
        play(session, media_id, asset_file_id, asset_type="epg")
        return
    # if its restartable and the title is live now, then we can play it
    if restartable and int(start) <= time() <= int(stop):
        play(session, media_id, asset_file_id, asset_type="epg")
        return
    # if the title was in the past, it was restartable, but it's not recordable,
    #  then we can't play it, show a dialog
    elif restartable and not recordable and int(stop) < time():
        dialog.ok(addon_name, addon.getLocalizedString(30093))
        return
    # if title is in the future, then we can't play it, show a dialog
    if int(start) > time():
        dialog = xbmcgui.Dialog()
        if recordable:
            choice = dialog.yesno(
                addon_name,
                addon.getLocalizedString(30092),
                nolabel=addon.getLocalizedString(30109),
                yeslabel=addon.getLocalizedString(30110),
            )
            if choice == 0:  # record
                try:
                    recording.record_asset(
                        session,
                        addon.getSetting("jsonpostgw"),
                        media_id,
                        api_user=addon.getSetting("apiuser"),
                        api_pass=addon.getSetting("apipass"),
                        domain_id=addon.getSetting("domainid"),
                        site_guid=addon.getSetting("siteguid"),
                        platform=addon.getSetting("platform"),
                        ud_id=addon.getSetting("devicekey"),
                        token=addon.getSetting("kstoken"),
                    )
                except recording.RecordingException as e:
                    return dialog.ok(
                        addon_name,
                        addon.getLocalizedString(30025).format(message=e.status),
                    )
                return dialog.ok(addon_name, addon.getLocalizedString(30111))
            elif choice == 1:  # record series
                try:
                    recording.record_series_by_program_id(
                        session,
                        addon.getSetting("jsonpostgw"),
                        media_id,
                        api_user=addon.getSetting("apiuser"),
                        api_pass=addon.getSetting("apipass"),
                        domain_id=addon.getSetting("domainid"),
                        site_guid=addon.getSetting("siteguid"),
                        platform=addon.getSetting("platform"),
                        ud_id=addon.getSetting("devicekey"),
                        token=addon.getSetting("kstoken"),
                    )
                except recording.RecordingException as e:
                    return dialog.ok(
                        addon_name,
                        addon.getLocalizedString(30025).format(message=e.status),
                    )
                return dialog.ok(addon_name, addon.getLocalizedString(30111))
        else:
            dialog.ok(addon_name, addon.getLocalizedString(30092))


def export_chanlist(session: Session) -> None:
    ks_expiry = addon.getSetting("ksexpiry")
    dialog = xbmcgui.Dialog()
    if ks_expiry and int(ks_expiry) < int(time()):
        # can't update channel list if the token is expired
        # and due to a Kodi bug, when settings are opened
        # we cannot refresh the token
        dialog.ok(addon_name, addon.getLocalizedString(30094))
        return

    import export_data

    export_data.export_channel_list(addon, session)
    exit()


def delete_recording(session: Session, recording_id: int) -> None:
    """
    Delete a recording.

    :param session: requests session
    :param recording_id: recording id
    :return: None
    """
    dialog = xbmcgui.Dialog()
    if dialog.yesno(addon_name, addon.getLocalizedString(30105)):
        try:
            recording.delete_asset_recording(
                session,
                addon.getSetting("jsonpostgw"),
                recording_id,
                api_user=addon.getSetting("apiuser"),
                api_pass=addon.getSetting("apipass"),
                domain_id=addon.getSetting("domainid"),
                site_guid=addon.getSetting("siteguid"),
                platform=addon.getSetting("platform"),
                ud_id=addon.getSetting("devicekey"),
                token=addon.getSetting("kstoken"),
            )
        except recording.RecordingException as e:
            dialog.ok(addon_name, addon.getLocalizedString(30025).format(message=e))
            return
        dialog.ok(addon_name, addon.getLocalizedString(30106))
        xbmc.executebuiltin("Container.Refresh")


def about_dialog() -> None:
    """
    Show the about dialog.

    :return: None
    """
    dialog = xbmcgui.Dialog()
    dialog.textviewer(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(30052),
    )


if __name__ == "__main__":
    params = dict(parse_qsl(argv[2].replace("?", "")))
    action = params.get("action")
    # session to be used for all requests
    session = prepare_session()
    # authenticate if necessary
    authenticate(session)

    if action is None:
        if addon.getSettingBool("isfirstrun"):
            # show about dialog
            about_dialog()
            addon.setSettingBool("isfirstrun", False)
        if not all([addon.getSetting("username"), addon.getSetting("password")]):
            # show dialog to login
            dialog = xbmcgui.Dialog()
            dialog.ok(addon_name, addon.getLocalizedString(30028))
            addon.openSettings()
            exit()
        # show main menu
        main_menu()
    elif action == "channel_list":
        channel_list(session)
    elif action == "play_channel":
        play(session, params["id"], params["extra"])
    elif action == "play_recording":
        play_recording(session, params["id"], params["extra"])
    elif action == "recordings":
        get_recordings(session, params["extra"])
    elif action == "device_list":
        device_list(session)
    elif action == "myvodka_device_list":
        vodka_device_list()
    elif action == "del_device":
        delete_device(session, params.get("device_id"))
    elif action == "rename_vodka_device":
        rename_vodka_device(params.get("device"))
    elif action == "del_vodka_device":
        delete_vodka_device(params.get("device"))
    elif action == "export_chanlist":
        export_chanlist(session)
    elif action == "export_epg":
        update_epg(session)
    elif action == "catchup":
        catchup(
            session,
            params["id"],
            params["cid"],
            params["start"],
            params["end"],
            params.get("rec", 0) == "1",
            params.get("res", 0) == "1",
        )
    elif action == "del_recording":
        delete_recording(session, params["recording_id"])
    elif action == "settings":
        addon.openSettings()
    elif action == "about":
        about_dialog()
