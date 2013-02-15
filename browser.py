import json
import time
import webbrowser
from os import path
from PyQt4 import QtCore
from PyQt4 import QtWebKit
from PyQt4 import QtNetwork

import settings
import event
import network
import external

class BrowserWindow:
  _instances = []

  def __init__(self, startUrl):
    self.ACTIVATE_EVENT = object()
    self.CLOSE_EVENT = object()
    self.DEACTIVATE_EVENT = object()
    self.MOVE_EVENT = object()
    self.RESIZE_EVENT = object()
    self.WHEEL_EVENT = object()

    self._instances.append(self)
    self._startUrl = startUrl
    self._view = MessengerWebView(self)
    self._external = external.External(self)
    self._fade_animation_token = None
    page = self._view.page()
    page.linkClicked.connect(self._on_link_clicked)
    page.setLinkDelegationPolicy(QtWebKit.QWebPage.DelegateAllLinks)
    frame = page.mainFrame()
    frame.javaScriptWindowObjectCleared.connect(self._bind_external)
    event.subscribe(self.CLOSE_EVENT, self._on_close)
    event.subscribe(self.WHEEL_EVENT, self._on_wheel)
    manager = page.networkAccessManager()
    manager.setCookieJar(SettingsBasedCookieJar())
    manager.sslErrors.connect(self._handle_ssl_error)
    cache = QtNetwork.QNetworkDiskCache()
    cache.setCacheDirectory(
        path.join(settings.SETTINGS_DIR, "cache"))
    manager.setCache(cache)
    websettings = page.settings()
    websettings.setAttribute(
        QtWebKit.QWebSettings.DeveloperExtrasEnabled, True)
    websettings.setAttribute(
        QtWebKit.QWebSettings.LocalStorageEnabled, True)
    websettings.setLocalStoragePath(
        path.join(settings.SETTINGS_DIR, "localstorage"))
    event.subscribe(settings.AUTH_CHANGED_EVENT, lambda: self.refresh())
    self.refresh()

  def call_js_function(self, name, *args):
    name_str = json.dumps(name)
    args_str = ",".join(json.dumps(arg) for arg in args)
    script = "window[{0}]({1})".format(name_str, args_str)
    self._view.page().mainFrame().evaluateJavaScript(script)

  def _bind_external(self):
    frame = self._view.page().mainFrame()
    frame.addToJavaScriptWindowObject("external", self._external)

  def fade(self, duration_ms):
    if (self._fade_animation_token):
      print("Fade called during fade, ignored.")
      return
    start_ms = time.time() * 1000
    def _fade_callback():
      t_ms = time.time() * 1000 - start_ms
      if t_ms > duration_ms or t_ms < 0:
        self.hide()
      else:
        self._view.setWindowOpacity(1 - float(t_ms) / duration_ms)
    self._fade_animation_token = event.run_on_main_thread(
        _fade_callback, repeating=True, delay_ms=1000./60)

  def get_rectangle(self):
    g = self._view.geometry()
    return (g.x(), g.y(), g.width(), g.height())

  def _handle_ssl_error(self, reply, errors):
    # Ignore SSL errors when we've overridden the default URL
    global _printed_ssl_ignore
    if settings.get_setting("BaseUrl"):
      reply.ignoreSslErrors()
      if not _printed_ssl_ignore:
        _printed_ssl_ignore = True
        print("Ignoring SSL errors.")
    else:
      print("SSL error!")

  def hide(self):
    self._view.hide()

  def is_active(self):
    return self._view.isActiveWindow()

  def is_visible(self):
    return not self._view.isHidden()

  def navigate(self, url):
    token_url = network.add_access_token(url)
    self._view.load(QtCore.QUrl(token_url))

  def _on_close(self):
    self._external.arbiter_inform_local("FbDesktop.windowClosed", None)

  def _on_link_clicked(self, qurl):
    webbrowser.open(qurl.toString())

  def _on_wheel(self, delta):
    # 120 is the standard wheel delta, but JS works better with 40 for some
    # reason. This is the same adjustment we use on Windows.
    adjusted_delta = delta * 40 / 120
    self._external.arbiter_inform_local("FbDesktop.mouseWheel", adjusted_delta)

  def refresh(self):
    token_url = network.add_access_token(self._startUrl)
    self._view.load(QtCore.QUrl(token_url))

  def set_position(self, x, y):
    self._view.move(x, y)

  def set_rectangle(self, x, y, width, height):
    self._view.setGeometry(x, y, width, height)

  def set_size(self, width, height):
    self._view.resize(width, height)

  def set_title(self, title):
    self._view.setWindowTitle(title)

  def show(self, bringtofront=True):
    if self._fade_animation_token:
      self._fade_animation_token.stop()
      self._fade_animation_token = None
    self._view.setWindowOpacity(1)
    self._view.show()
    if bringtofront:
      self._view.activateWindow()

  def style_toast(self):
    # We would like to prevent the toast from creating a taskbar icon. The Qt
    # way to do this would be to make the toast widget a child of another
    # window and set its Dialog flag. Unfortunately, that seems to mess with
    # focus within the app (the parent window steals focus "back" when the
    # toast goes away). TODO(jacko): Find another way.
    self._view.setWindowFlags(QtCore.Qt.FramelessWindowHint |
                              QtCore.Qt.WindowStaysOnTopHint)
    self._view.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
    self._view.setAttribute(QtCore.Qt.WA_X11DoNotAcceptFocus)

# The only way to capture events like move and close is to subclass the
# QWebView and override these methods. We do as little as possible here,
# though, for abstraction's sake.
class MessengerWebView(QtWebKit.QWebView):
  def __init__(self, browserwindow):
    QtWebKit.QWebView.__init__(self)
    self._bw = browserwindow

  def closeEvent(self, event_obj):
    QtWebKit.QWebView.closeEvent(self, event_obj)
    event.inform(self._bw.CLOSE_EVENT)

  def focusInEvent(self, event_obj):
    QtWebKit.QWebView.focusInEvent(self, event_obj)
    event.inform(self._bw.ACTIVATE_EVENT)

  def focusOutEvent(self, event_obj):
    QtWebKit.QWebView.focusOutEvent(self, event_obj)
    event.inform(self._bw.DEACTIVATE_EVENT)

  def moveEvent(self, event_obj):
    QtWebKit.QWebView.moveEvent(self, event_obj)
    event.inform(self._bw.MOVE_EVENT)

  def resizeEvent(self, event_obj):
    QtWebKit.QWebView.resizeEvent(self, event_obj)
    event.inform(self._bw.RESIZE_EVENT)

  def wheelEvent(self, event_obj):
    QtWebKit.QWebView.wheelEvent(self, event_obj)
    event.inform(self._bw.WHEEL_EVENT, event_obj.delta())

class SettingsBasedCookieJar(QtNetwork.QNetworkCookieJar):
  def __init__(self):
    QtNetwork.QNetworkCookieJar.__init__(self)
    self._cookies = settings.get_setting("CookieJar", {})

  def setCookiesFromUrl(self, cookieList, url):
    cookiesForHost = self._cookies.get(url.host(), {})
    for cookie in cookieList:
      name = bytes(cookie.name()).decode('utf-8')
      value = bytes(cookie.value()).decode('utf-8')
      cookiesForHost[name] = value
    self._cookies[url.host()] = cookiesForHost
    settings.set_setting("CookieJar", self._cookies)
    return True

  def cookiesForUrl(self, url):
    cookieList = []
    for (name, value) in self._cookies.get(url.host(), {}).items():
      cookieList.append(QtNetwork.QNetworkCookie(name, value))
    return cookieList

_printed_ssl_ignore = False
