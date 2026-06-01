from urllib.parse import quote
import time
from base.base_page import BasePage


class DontdoitPage(BasePage):
    path = "/packageGames/dontdoit/dontdoit"
    game_key = "dontdoitParty"

    def open(self):
        return self.navigate(self.path)

    def create_room(self, nick="Minium主持", cloud=None):
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
                self.open()
                code = info.get("roomCode")
                try:
                    self.input_text("input", nick)
                    if code:
                        inputs = self.page.get_elements("input")
                        if len(inputs) >= 2:
                            inputs[1].input(str(code))
                except Exception:
                    pass
                self.try_call_page_method(
                    "setData",
                    {
                        "roomId": str(info["roomId"]),
                        "roomCode": str(code or ""),
                    },
                )
                self.sleep(1.5)
                return self.room_info() or info
        self.open()
        self.input_text("input", nick)
        self.tap_any_text(["创建聚会组", "创建"], selector="button", timeout=8)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=15,
            message="dontdoit roomId not created",
        )
        return self.room_info()

    def join_room(self, room_code, nick="Minium玩家"):
        self.open()
        inputs = self.page.get_elements("input")
        if len(inputs) >= 2:
            inputs[0].input(nick)
            inputs[1].input(str(room_code))
        self.tap_any_text(["加入聚会组", "加入"], selector="button", timeout=8)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=15,
            message="dontdoit join failed",
        )
        return self.room_info()

    def input_my_action(self, action):
        """输入禁止动作"""
        try:
            inputs = self.page.get_elements("input")
            if len(inputs) >= 1:
                inputs[0].input(str(action))
            self.sleep(0.5)
        except Exception as e:
            self.log(f"Failed to input action: {e}")
        return self

    def mark_ready(self):
        try:
            self.tap_any_text(["准备", "已准备"], selector="button", timeout=4)
        except Exception:
            pass
        return self

    def start_game(self, cloud=None, room_id=None, room_code=None):
        """主持人点击开始挑战"""
        if cloud and getattr(cloud, "enabled", False):
            return self.cloud_start(
                cloud, "startGame", room_id=room_id, room_code=room_code
            )
        self.tap_any_text(["开始挑战", "开始"], selector="button", timeout=8)
        self.sleep(2)
        return self

    def trigger_self(self):
        """玩家点击"我犯规了"按钮"""
        try:
            self.tap_any_text(["我犯规了"], selector="button", timeout=5)
            self.sleep(1)
        except Exception:
            pass
        return self

    def end_game(self):
        """主持人点击结束游戏"""
        try:
            self.tap_any_text(["结束游戏", "结束"], selector="button", timeout=5)
        except Exception:
            pass
        return self

    def room_info(self):
        return {
            "roomId": self.data_value("roomId"),
            "roomCode": self.data_value("roomCode"),
            "view": self.data_value("view"),
        }
