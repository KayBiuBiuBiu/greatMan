import json
import time
from urllib.parse import quote

from base.base_page import BasePage


class DrawPage(BasePage):
    path = "/packageGames/draw-guess/draw-guess"
    game_key = "drawGuess"

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
        self.sleep(2.5)
        if not self.data_value("roomId"):
            self.bootstrap_room_in_page(room_id, room_code, "afterHasRoomId")
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=20,
            message="draw enter_room failed",
        )
        return self.room_info()

    def create_room(self, nick="Minium画家", cloud=None):
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
        self.tap_any_text(["创建聚会组", "创建"], selector="button", timeout=10)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=25,
            message="draw roomId not created",
        )
        return self.room_info()

    def join_room(self, room_code, nick="Minium猜者"):
        self.ensure_lobby()
        inputs = self.page.get_elements("input")
        if len(inputs) >= 2:
            inputs[0].input(nick)
            inputs[1].input(str(room_code))
        self.tap_any_text(["加入互动组", "加入"], selector="button", timeout=8)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=15,
            message="draw join failed",
        )
        return self.room_info()

    def refresh_lobby(self, cloud=None, room_id=None):
        rid = room_id or self.data_value("roomId")
        if cloud and cloud.enabled and rid:
            cloud.push_view_to_page(self, self.game_key, rid)
            return self
        for method in ("loadView", "_refreshRoomState", "syncDisplayText"):
            try:
                self.try_call_page_method(method)
                break
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
        self.tap_any_text(["开始互动", "开始画画", "开始"], selector="button", timeout=8)
        self.sleep(2)
        return self

    def draw_stroke(self):
        try:
            canvas = self.get("canvas", timeout=3)
            canvas.touch_start(80, 80)
            canvas.touch_move(180, 120)
            canvas.touch_move(260, 180)
            canvas.touch_end()
        except Exception as exc:
            self.log(f"canvas stroke skipped: {exc}")
        return self

    def submit_guess(self, word="苹果"):
        try:
            self.input_text("input", word)
            self.tap_any_text(["提交", "猜", "确认"], selector="button", timeout=4)
        except Exception as exc:
            self.log(f"submit guess skipped: {exc}")
        return self

    def room_info(self):
        state = self.data_value("state", default={}) or {}
        view = self.data_value("view", default={}) or {}
        rid = self.data_value("roomId") or state.get("roomId") or view.get("roomId")
        return {
            "roomId": rid,
            "roomCode": self.data_value("roomCode") or state.get("roomCode") or view.get("roomCode"),
            "state": state,
        }
