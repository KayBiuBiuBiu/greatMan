from urllib.parse import quote

import time

from base.base_page import BasePage


class DrinkPage(BasePage):
    path = "/packageGames/drink-party/drink-party"
    game_key = "drinkParty"

    def open(self):
        return self.navigate(self.path)

    def ensure_lobby(self):
        try:
            self.app.reLaunch(self.path)
        except Exception:
            try:
                self.app.relaunch(self.path)
            except Exception:
                self.open()
        self.sleep(1.5)
        return self

    def enter_room(self, room_id, room_code):
        rid = quote(str(room_id))
        code = quote(str(room_code))
        url = self.path + "?roomId=" + rid + "&roomCode=" + code
        self.relaunch_url(url)
        self.sleep(2)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=25,
            message="drink enter_room failed",
        )
        return self.room_info()

    def create_room(self, nick="Minium房主", cloud=None):
        if cloud:
            raw = cloud.call_function(
                cloud.service_for(self.game_key),
                {
                    "action": "create",
                    "nickName": nick,
                    "avatarUrl": "",
                    "_test": True,
                },
            )
            info = cloud._parse_cf_result(raw)
            if info.get("roomId"):
                return self.enter_room(info["roomId"], info["roomCode"])
        self.ensure_lobby()
        try:
            self.input_text("input", nick)
        except Exception:
            pass
        self.tap_any_text(["创建聚会组", "创建", "开始互动"], selector="button", timeout=10)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=25,
            message="drink roomId not created",
        )
        return self.room_info()

    def create_room_via_cloud(self, cloud, nick="Minium房主"):
        return self.create_room(nick=nick, cloud=cloud)

    def join_room(self, room_code, nick="Minium玩家"):
        self.open()
        inputs = self.page.get_elements("input")
        if len(inputs) >= 2:
            inputs[0].input(nick)
            inputs[1].input(str(room_code))
        else:
            self.input_text("input", nick)
        self.tap_any_text(["加入互动组", "加入"], timeout=8)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=15,
            message="drink join failed",
        )
        return self.room_info()

    def mark_ready(self):
        try:
            self.tap_any_text(["准备", "已准备"], selector="button", timeout=4)
        except Exception:
            self.log("ready button not visible, continuing")
        return self

    def is_start_enabled(self):
        data = self.page_data()
        if data.get("canStart") is not None:
            return bool(data.get("canStart"))
        return bool(data.get("isRoundStarter")) and (
            (data.get("state") or {}).get("phase") == "waiting"
        )

    def wait_until_start_enabled(self, timeout=20, cloud=None, room_id=None):
        end = time.time() + timeout
        while time.time() < end:
            if self.is_start_enabled():
                return True
            time.sleep(0.8)
        return False

    def start_round(self, cloud=None, room_id=None, room_code=None):
        if cloud and getattr(cloud, "enabled", False):
            return self.cloud_start(
                cloud, "start_round", room_id=room_id, room_code=room_code
            )
        self.wait_until(
            lambda: bool(self.data_value("isRoundStarter"))
            and (self.data_value("state") or {}).get("phase") == "waiting",
            timeout=20,
            message="waiting to become round starter in lobby",
        )
        self.tap_any_text(["开始本轮", "开始互动"], selector="button", timeout=10)
        self.sleep(2)
        return self

    def reveal_if_needed(self):
        try:
            self.try_call_page_method("_tryReveal")
        except Exception as exc:
            self.log(f"page reveal hook skipped: {exc}")
        self.sleep(1)
        return self

    def next_round(self):
        try:
            self.tap_any_text(["下一轮"], selector="button", timeout=5)
        except Exception:
            self.log("next round button not visible; current user may not be ringer")
        return self

    def room_info(self):
        state = self.data_value("state", default={}) or {}
        return {
            "roomId": self.data_value("roomId"),
            "roomCode": self.data_value("roomCode") or state.get("roomCode"),
            "state": state,
        }
