import json
import time
from urllib.parse import quote

from base.base_page import BasePage


class UndercoverPage(BasePage):
    path = "/packageGames/undercover/undercover"
    game_key = "undercover"
    min_players = 3

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
                {"mode": "v2", "roomId": str(room_id), "roomCode": str(room_code)},
                ensure_ascii=False,
            )
        )
        url = self.path + "?config=" + cfg
        try:
            self.app.reLaunch(url)
        except Exception:
            self.app.navigate_to(url)
        self.sleep(2)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=25,
            message="undercover enter_room failed",
        )
        return self.room_info()

    def create_room(self, nick="Minium房主"):
        self.ensure_lobby()
        try:
            self.input_text("input", nick)
        except Exception:
            pass
        self.tap_any_text(["创建聚会组"], selector="button", timeout=10)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=25,
            message="undercover roomId not created",
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
            message="undercover join failed",
        )
        return self.room_info()

    def set_player_count(self, count):
        """动态人数模式：无需设定目标人数。"""
        return self

    def refresh_lobby(self, cloud=None, room_id=None):
        rid = room_id or self.data_value("roomId")
        if cloud and cloud.enabled and rid:
            snap = cloud.sync_snapshot(self.game_key, rid)
            if isinstance(snap, dict) and snap.get("state"):
                self.try_call_page_method("applyTestSyncSnapshot", snap)
        else:
            try:
                self.try_call_page_method("loadView")
            except Exception:
                pass
        self.sleep(1.2)
        return self

    def has_target_player_stepper(self):
        try:
            self.wait_for_text("目标人数", selector="view", timeout=2)
            return True
        except Exception:
            return False

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

    def wait_in_word_phase(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            phase = str(self.data_value("phase") or "")
            state = self.data_value("state", default={}) or {}
            cph = str(state.get("currentPhase") or "")
            if phase == "word" or cph == "word":
                return self
            self.refresh_lobby()
            time.sleep(0.8)
        raise AssertionError("未进入发词阶段 word")

    def mark_ready(self):
        try:
            self.tap_any_text(["准备", "已准备"], selector="button", timeout=4)
        except Exception:
            self.log("ready button not visible, continuing")
        return self

    def start_game(self):
        self.tap_any_text(["开始互动", "开始游戏", "发牌"], selector="button", timeout=10)
        self.sleep(2)
        return self

    def speak_and_vote(self):
        for text in ["我发言", "发言", "投票", "确认投票", "结束", "看本机词", "我知道了"]:
            try:
                self.tap_any_text([text], selector="button", timeout=2)
                self.sleep(0.5)
            except Exception:
                pass
        return self

    def room_info(self):
        state = self.data_value("state", default={}) or {}
        return {
            "roomId": self.data_value("roomId"),
            "roomCode": self.data_value("roomCode") or state.get("roomCode"),
            "state": state,
        }
