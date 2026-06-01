import json
import time
from urllib.parse import quote

from base.base_page import BasePage


class WerewolfPage(BasePage):
    path = "/packageGames/werewolf/werewolf"
    game_key = "werewolf"

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
        cfg = quote(
            json.dumps(
                {"roomId": str(room_id), "roomCode": str(room_code)},
                ensure_ascii=False,
            )
        )
        url = self.path + "?config=" + cfg
        self.relaunch_url(url)
        self.sleep(2.5)
        if not self.data_value("roomId"):
            self.bootstrap_room_in_page(room_id, room_code, "afterHasRoomId")
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=20,
            message="werewolf enter_room failed",
        )
        return self.room_info()

    def create_room(self, nick="Minium法官", cloud=None):
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
            message="werewolf roomId not created",
        )
        return self.room_info()

    def join_room(self, room_code, nick="Minium玩家"):
        self.ensure_lobby()
        inputs = self.page.get_elements("input")
        if len(inputs) >= 2:
            inputs[0].input(nick)
            inputs[1].input(str(room_code))
        self.tap_any_text(["加入互动组", "加入"], selector="button", timeout=8)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=15,
            message="werewolf join failed",
        )
        return self.room_info()

    def mark_ready(self):
        try:
            self.tap_any_text(["准备", "已准备"], selector="button", timeout=4)
        except Exception:
            pass
        return self

    def set_player_count(self, count):
        """动态人数模式：无需设定目标人数。"""
        return self

    def refresh_lobby(self, cloud=None, room_id=None):
        rid = room_id or self.data_value("roomId")
        if cloud and cloud.enabled and rid:
            cloud.push_view_to_page(self, self.game_key, rid)
            return self
        for method in ("loadView", "syncDisplayText"):
            try:
                self.try_call_page_method(method)
                break
            except Exception:
                continue
        self.sleep(1.2)
        return self

    def wait_until_start_enabled(self, timeout=20, cloud=None, room_id=None):
        end = time.time() + timeout
        while time.time() < end:
            if self.is_start_enabled():
                return True
            self.refresh_lobby(cloud=cloud, room_id=room_id)
            time.sleep(0.8)
        return False

    def is_start_enabled(self):
        data = self.page_data()
        if data.get("canStart") is not None:
            return bool(data.get("canStart"))
        return super().is_start_enabled()

    def start_game(self, cloud=None, room_id=None, room_code=None):
        if cloud and getattr(cloud, "enabled", False):
            return self.cloud_start(
                cloud, "start_game", room_id=room_id, room_code=room_code
            )
        self.tap_any_text(["开始互动", "开始游戏", "发牌"], selector="button", timeout=8)
        self.sleep(2)
        return self

    def play_day_night_vote(self):
        for text in ["进入夜晚", "天亮了", "发言结束", "投票", "确认", "下一阶段"]:
            try:
                self.tap_any_text([text], selector="button", timeout=2)
                self.sleep(0.5)
            except Exception:
                pass
        return self

    def room_info(self):
        pub = self.data_value("pub", default={}) or {}
        return {
            "roomId": self.data_value("roomId"),
            "roomCode": self.data_value("roomCode") or pub.get("roomCode"),
            "state": pub,
        }
