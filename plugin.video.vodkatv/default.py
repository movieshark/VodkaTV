from json import dumps
from random import choice
from sys import argv
from time import time
from urllib.parse import parse_qsl, quote, urlencode, urlparse

import inputstreamhelper  # type: ignore
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
from requests import HTTPError, Session
from resources.lib.utils import static as utils_static
from resources.lib.utils import unix_to_date
from resources.lib.utils.dns_resolver import resolve_domain
from resources.lib.vodka import devices, enums, login, media_list, misc, static
from resources.lib.vodka.playback import PlaybackException, get_playback_obj

addon = xbmcaddon.Addon()
addon_name = addon.getAddonInfo("name")


def add_item(plugin_prefix, handle, name, action, is_directory, **kwargs) -> None:
    """
    Adds an item to the Kodi listing
    """
    url = f"{plugin_prefix}?action={action}&name={quote(name)}"
    item = xbmcgui.ListItem(label=name)
    info_labels = {}
    if kwargs.get("description"):
        url += "&descr=%s" % (quote(kwargs["description"]))
        info_labels.update({"plot": kwargs["description"]})
    arts = {}
    if kwargs.get("icon"):
        url += "&icon=%s" % (quote(kwargs["icon"]))
        arts.update({"thumb": kwargs["icon"], "icon": kwargs["icon"]})
    if kwargs.get("fanart"):
        url += "&fanart=%s" % (quote(kwargs["fanart"]))
        arts.update({"fanart": kwargs["fanart"]})
        item.setProperty("Fanart_Image", kwargs["fanart"])
    if kwargs.get("type"):
        info_labels.update({"mediatype": kwargs["type"]})
    if kwargs.get("id"):
        url += "&id=%s" % (kwargs["id"])
    if kwargs.get("year"):
        info_labels.update({"year": kwargs["year"]})
        url += "&year=%s" % (kwargs["year"])
    if kwargs.get("episode"):
        info_labels.update({"episode": kwargs["episode"]})
        url += "&episode=%s" % (kwargs["episode"])
    if kwargs.get("season"):
        info_labels.update({"season": kwargs["season"]})
        url += "&season=%s" % (kwargs["season"])
    if kwargs.get("show_name"):
        info_labels.update({"tvshowtitle": kwargs["show_name"]})
        url += "&show_name=%s" % (quote(kwargs["show_name"]))
    if kwargs.get("genre"):
        info_labels.update({"genre": kwargs["genre"]})
        url += "&genre=%s" % (quote(dumps(kwargs["genre"])))
    if kwargs.get("country"):
        info_labels.update({"country": kwargs["country"]})
        url += "&country=%s" % (quote(dumps(kwargs["country"])))
    if kwargs.get("director"):
        info_labels.update({"director": kwargs["director"]})
        url += "&director=%s" % (quote(dumps(kwargs["director"])))
    if kwargs.get("cast"):
        info_labels.update({"cast": kwargs["cast"]})
        url += "&cast=%s" % (quote(dumps(kwargs["cast"])))
    if kwargs.get("mpaa"):
        info_labels.update({"mpaa": kwargs["mpaa"]})
        url += "&mpaa=%s" % (quote(kwargs["mpaa"]))
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


def authenticate(session: Session) -> None:
    """
    Handles initial login, device registration and token refresh.
    Also generates the device key if it is not set.

    :param session: The requests session.
    :return: None
    """
    if not all([addon.getSetting("username"), addon.getSetting("password")]):
        return
    if not addon.getSetting("devicekey"):
        device_id = misc.generate_ud_id()
        addon.setSetting("devicekey", device_id)
    ks_expiry = addon.getSetting("ksexpiry")
    if ks_expiry and int(ks_expiry) > int(time()):
        return  # KS token is valid so no need to reauthenticate
    prog_dialog = xbmcgui.DialogProgress()
    prog_dialog.create(addon_name)
    # KS login
    # refresh KS token if it expired
    if ks_expiry and int(ks_expiry) < time():
        try:
            prog_dialog.update(85, addon.getLocalizedString(30016))
            (
                access_token,
                refresh_token,
                expiration_date,
                refresh_expiration_date,
            ) = login.refresh_access_token(
                session,
                addon.getSetting("jsonpostgw"),
                addon.getSetting("ksrefreshtoken"),
                ud_id=addon.getSetting("devicekey"),
                api_user=addon.getSetting("apiuser"),
                api_pass=addon.getSetting("apipass"),
                platform=addon.getSetting("platform"),
                device_brand_id=enums.DeviceBrandId.PCMAC.value,
                token=addon.getSetting("kstoken"),
                domain_id=addon.getSetting("domainid"),
                site_guid=addon.getSetting("siteguid"),
            )
            prog_dialog.close()
        except HTTPError as e:
            # check if the error is 403
            # if it is, then the refresh token is invalid
            # so we need to reauthenticate
            if e.response.status_code == 403:
                addon.setSetting("ksexpiry", "")
                authenticate(session)
                return
            else:
                raise e
    # fresh login
    else:
        prog_dialog.update(50, addon.getLocalizedString(30022))
        pkey, vodka_config = login.get_config(session, addon.getSetting("devicekey"))
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
        addon.setSetting("jsonpostgw", json_post_gw)
        addon.setSetting("phoenixgw", phoenix_gw)
        addon.setSetting("licenseurlbase", license_url_base)
        addon.setSetting("tenantid", tenant_id)
        addon.setSetting("apiuser", api_user)
        addon.setSetting("apipass", api_pass)
        addon.setSetting("platform", platform)
        # we don't store the public key as it's not needed after a login
        prog_dialog.update(75, addon.getLocalizedString(30023))
        try:
            login_response, access_token, refresh_token = login.sign_in(
                session,
                json_post_gw,
                addon.getSetting("devicekey"),
                api_user,
                api_pass,
                platform,
                addon.getSetting("username"),
                addon.getSetting("password"),
                pkey,
            )
        except login.LoginError as e:
            prog_dialog.close()
            dialog = xbmcgui.Dialog()
            dialog.ok(
                addon_name, addon.getLocalizedString(30025).format(message=e.message)
            )
            return
        # NOTE: tokens have a pipe character and the expiration date appended to them here
        access_token, expiration_date = access_token.split("|")
        refresh_token, refresh_expiration_date = refresh_token.split("|")
        site_guid = login_response["SiteGuid"]
        domain_id = login_response["DomainID"]
        addon.setSetting("domainid", str(domain_id))
        addon.setSetting("siteguid", site_guid)
        # register device
        prog_dialog.update(90, addon.getLocalizedString(30024))
        try:
            devices.register_device(
                session,
                json_post_gw,
                addon.getSetting("devicenick"),
                ud_id=addon.getSetting("devicekey"),
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
                addon_name, addon.getLocalizedString(30025).format(message=e.message)
            )
            return
        prog_dialog.close()
        # show success dialog
        dialog = xbmcgui.Dialog()
        dialog.ok(addon_name, addon.getLocalizedString(30026))
    addon.setSetting("kstoken", access_token)
    addon.setSetting("ksrefreshtoken", refresh_token)
    addon.setSetting("ksexpiry", str(expiration_date))
    addon.setSetting("ksrefreshexpiry", str(refresh_expiration_date))


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
    # device list
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30043),
        action="device_list",
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
    available_file_ids = get_available_files(session, available_file_ids)
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
        if not media_files:
            continue
        media_file = media_files[0]["id"]
        add_item(
            plugin_prefix=argv[0],
            handle=argv[1],
            name=name,
            action="play_channel",
            is_directory=False,
            id=channel_id,
            icon=image,
            is_livestream=True,
            refresh=True,
            extra=media_file,
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


def _gen_mgr_params(playback_obj: list) -> str:
    """
    Generates the parameters for playback manager's statistics report.

    :param playback_obj: playback object
    :return: parameters for playback manager
    """
    try:
        params = {}
        params["assetType"] = "MEDIA"
        params["id"] = playback_obj["id"]
        params["assetId"] = playback_obj["assetId"]
    except (KeyError, IndexError):
        return ""
    return urlencode(params)


def play(session: Session, media_id: int, asset_file_id: int) -> None:
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
        )
    except PlaybackException as e:
        if e.code == "1003":  # Device not in household
            try_register_device(session)
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
    trailer_params = _gen_mgr_params(playback_obj)
    manifest_url = urlparse(playback_obj.get("url"))
    # extract host from domain
    hostname = manifest_url.hostname
    ip = resolve_domain(hostname)
    if not ip:
        xbmcgui.Dialog().ok(
            addon_name,
            addon.getLocalizedString(30035).format(url=manifest_url.geturl()),
        )
        return
    # replace hostname with IP and specify port 80
    manifest_url = manifest_url._replace(netloc=f"{ip}:80")
    # replace https with http
    manifest_url = manifest_url._replace(scheme="http")
    response = session.head(
        manifest_url.geturl(), allow_redirects=False, headers={"Host": hostname}
    )
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


def update_epg(_session: Session) -> None:
    """
    Update the EPG file manually.

    :param _session: requests session
    :return: None
    """
    # local import should be fine
    # since it's not used often
    from export_data import export_epg, get_utc_offset

    # get epg settings
    from_time = addon.getSetting("epgfrom")
    to_time = addon.getSetting("epgto")
    utc_offset = get_utc_offset()

    dialog = xbmcgui.Dialog()
    if not all([from_time, to_time]):
        dialog.ok(addon_name, addon.getLocalizedString(30083))
        return
    dialog.notification(
        addon_name,
        f"{addon.getLocalizedString(30084)}: -{from_time} {addon.getLocalizedString(30086)} - +{to_time} {addon.getLocalizedString(30086)}",
    )
    export_epg(_session, "-" + from_time, to_time, utc_offset)


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
    elif action == "device_list":
        device_list(session)
    elif action == "del_device":
        delete_device(session, params.get("device_id"))
    elif action == "export_chanlist":
        import export_data

        export_data.export_channel_list(session)
        exit()
    elif action == "export_epg":
        update_epg(session)
    elif action == "about":
        about_dialog()
