import threading
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import xbmc
import xbmcaddon
from bottle import default_app, hook, redirect, request, response, route
from xbmcgui import NOTIFICATION_ERROR, Dialog

addon = xbmcaddon.Addon()
name = f"{addon.getAddonInfo('name')} v{addon.getAddonInfo('version')}"
handle = f"[{name}]"
welcome_text = f"{name} Web Service"


class SilentWSGIRequestHandler(WSGIRequestHandler):
    """Custom WSGI Request Handler with logging disabled"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args, **kwargs):
        """Disable log messages"""
        pass


class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    """Multi-threaded WSGI server"""

    allow_reuse_address = True
    daemon_threads = True
    timeout = 1


@hook("before_request")
def set_server_header():
    response.set_header("Server", name)


@route("/")
def index():
    response.content_type = "text/plain"
    return welcome_text


@route("<url:path>", method=["GET"])
def redirect_site(url):
    host = request.query.get("h")
    scheme = request.query.get("s")
    if not all([host, scheme]):
        response.content_type = "text/plain"
        response.status = 400
        return "Missing h or s query parameter"
    redirect(f"{scheme}://{host}{url}", 302)


@route("<url:path>", method=["HEAD"])
def fake_image(url):
    """
    Returns a 200 and image/png content type for any HEAD request
    """
    response.content_type = "image/png"
    return ""


class WebServerThread(threading.Thread):
    def __init__(self, httpd: WSGIServer):
        threading.Thread.__init__(self)
        self.web_killed = threading.Event()
        self.httpd = httpd

    def run(self):
        while not self.web_killed.is_set():
            self.httpd.handle_request()

    def stop(self):
        self.web_killed.set()


def main_service() -> WebServerThread:
    if not addon.getSettingBool("webenabled"):
        xbmc.log(f"{handle} Web service disabled", xbmc.LOGWARNING)
        return
    app = default_app()
    try:
        httpd = make_server(
            addon.getSetting("webaddress"),
            addon.getSettingInt("webport"),
            app,
            server_class=ThreadedWSGIServer,
            handler_class=SilentWSGIRequestHandler,
        )
    except OSError as e:
        if e.errno == 98:
            xbmc.log(
                f"{handle} Web service: port {addon.getSetting('webport')} already in use",
                xbmc.LOGERROR,
            )
            Dialog().notification(
                name,
                addon.getLocalizedString(30091).format(
                    port=addon.getSetting("webport")
                ),
                NOTIFICATION_ERROR,
            )
            return
        raise
    xbmc.log(f"{handle} Web service starting", xbmc.LOGINFO)
    web_thread = WebServerThread(httpd)
    web_thread.start()
    return web_thread
