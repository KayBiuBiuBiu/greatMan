import time
from urllib.parse import quote

from base.base_page import BasePage


class TruthPage(BasePage):
    path = "/packageGames/play/play"
    game_key = "truthDareRoom"

    def open_room_mode(self, room_code=None):
        config = "{}"
        if room_code:
            config = quote('{"roomCode":"%s"}' % room_code)
        url = f"{self.path}?title={quote('真心话大冒险')}&config={config}"
        return self.navigate(url)

    def enter_room(self, room_code):
        try:
            self.app.reLaunch(
                f"{self.path}?title={quote('真心话大冒险')}"
                f"&config={quote('{\"roomCode\":\"%s\"}' % room_code)}"
            )
        except Exception:
            self.open_room_mode(room_code=room_code)
        self.sleep(2.5)
        self.wait_until(
            lambda: self.data_value("roomCode") == str(room_code),
            timeout=20,
            message="truth dare enter_room failed",
        )
        for method in ("_bootTruthDareRoom", "_refreshTdSync"):
            try:
                self.try_call_page_method(method)
                break
            except Exception:
                continue
        self.sleep(1.5)
        return self.room_info()

    def create_room(self, cloud=None):
        if cloud:
            raw = cloud.call_function(
                cloud.service_for(self.game_key),
                {
                    "action": "create",
                    "nickName": "Minium主持",
                    "selectedGame": "truthDare",
                    "_test": True,
                },
            )
            info = cloud._parse_cf_result(raw)
            room_code = info.get("roomCode")
            if room_code:
                entered = self.enter_room(room_code)
                entered["roomId"] = info.get("id") or info.get("roomId")
                return entered
        self.open_room_mode()
        self.sleep(2)
        return self.room_info()

    def join_room(self, room_code):
        return self.enter_room(room_code)

    def refresh_lobby(self, cloud=None, room_id=None):
        code = self.data_value("roomCode")
        if cloud and cloud.enabled and code:
            cloud.sync_truth_dare_page(self, code)
            return self
        for method in ("_refreshTdSync", "refreshRoomPlayers", "refreshTdState"):
            try:
                self.try_call_page_method(method, True)
                break
            except TypeError:
                try:
                    self.try_call_page_method(method)
                    break
                except Exception:
                    continue
            except Exception:
                continue
        self.sleep(1.2)
        return self

    def is_start_enabled(self):
        data = self.page_data()
        if data.get("canStart") is not None:
            return bool(data.get("canStart"))
        return super().is_start_enabled()

    def wait_until_start_enabled(self, timeout=20, cloud=None, room_id=None):
        end = time.time() + timeout
        while time.time() < end:
            if self.is_start_enabled():
                return True
            self.refresh_lobby(cloud=cloud, room_id=room_id)
            time.sleep(0.8)
        return False

    def mark_ready(self):
        try:
            self.tap_any_text(["准备", "已准备"], selector="button", timeout=4)
        except Exception:
            pass
        return self

    def start_round(self, cloud=None, room_id=None, room_code=None):
        if cloud and getattr(cloud, "enabled", False):
            return self.cloud_start(
                cloud, "start_round", room_id=room_id, room_code=room_code
            )
        self.tap_any_text(["开始本轮"], selector="button", timeout=8)
        return self

    def vote_tie_easter_egg(self):
        for text in ["真心话", "大冒险", "投票", "确认"]:
            try:
                self.tap_any_text([text], selector="button", timeout=2)
            except Exception:
                pass
        self.sleep(1)
        return self

    def room_info(self):
        return {
            "roomId": self.data_value("roomId"),
            "roomCode": self.data_value("roomCode"),
            "state": self.page_data(),
        }
