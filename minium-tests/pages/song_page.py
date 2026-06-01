from base.base_page import BasePage


class SongPage(BasePage):
    path = "/packageGames/song-guess/song-guess"
    game_key = "songGuess"

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
            message="song roomId not created",
        )
        return self.room_info()

    def join_room(self, room_code, nick="Minium抢答"):
        self.open()
        inputs = self.page.get_elements("input")
        if len(inputs) >= 2:
            inputs[0].input(nick)
            inputs[1].input(str(room_code))
        self.tap_any_text(["加入互动组", "加入"], selector="button", timeout=8)
        self.wait_until(lambda: self.data_value("roomId"), timeout=15, message="song join failed")
        return self.room_info()

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
        self.tap_any_text(["开始互动", "开始播放", "开始"], selector="button", timeout=8)
        self.sleep(2)
        return self

    def buzz_and_score(self):
        for text in ["抢答", "答对", "加分", "下一题"]:
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
