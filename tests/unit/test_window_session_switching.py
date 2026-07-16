from AssetsManager.window import MainWindow


class _Server:
    def is_running(self):
        return True

    def stop(self):
        events.append("lan.stop")


class _Loader:
    def invalidate_tasks(self):
        events.append("loader.invalidate")
        return 7

    def wait_for_tasks(self, generation):
        events.append(f"loader.wait:{generation}")


class _FileList:
    def __init__(self):
        self._loader = _Loader()

    def navigate_to(self, path, set_root=False):
        events.append("file-list.navigate")


class _Session:
    root_str = "old-root"


class _Service:
    def close_session(self, session):
        events.append("session.close")


class _Window:
    def __init__(self):
        self._lan_server = _Server()
        self._library_session = _Session()
        self.file_list = _FileList()
        self.sidebar = None

    def _library_service(self):
        return _Service()

    def _open_library_session(self, path):
        events.append("session.open")
        return _Session()

    def _apply_scoped_services(self, session):
        events.append("scoped.apply")


def test_switch_library_stops_lan_and_invalidates_thumbnails_before_closing(monkeypatch):
    global events
    events = []
    window = _Window()

    monkeypatch.setattr("AssetsManager.window._alive", lambda widget: widget is not None)
    monkeypatch.setattr("AssetsManager.window.QApplication.instance", lambda: None)

    MainWindow._on_switch_library(window, "new-root")

    assert events[:5] == ["lan.stop", "loader.invalidate", "loader.wait:7", "session.close", "session.open"]
