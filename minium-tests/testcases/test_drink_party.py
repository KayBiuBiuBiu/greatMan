import unittest

try:
    import minium
except Exception:
    minium = None

from base.base_page import load_config
from pages.drink_page import DrinkPage
from utils.cloud_helper import CloudHelper

BaseMiniTest = minium.MiniTest if minium else unittest.TestCase


class TestDrinkParty(BaseMiniTest):
    """趣味抽签：动态人数 + 倒计时期间不误响铃/闪屏。"""

    @classmethod
    def setUpClass(cls):
        if hasattr(super(), "setUpClass"):
            super().setUpClass()
        cls.config = load_config()

    def setUp(self):
        if hasattr(super(), "setUp"):
            super().setUp()
        self.cloud = CloudHelper(self, self.config)
        self.cloud.enabled = True
        self.min_players = 2

    def tearDown(self):
        try:
            DrinkPage(self).ensure_lobby()
        except Exception:
            pass
        if hasattr(super(), "tearDown"):
            super().tearDown()

    def _create_room(self, page):
        return page.create_room_via_cloud(self.cloud)

    def _seed(self, room_id, room_code, count):
        self.cloud.seed_players(
            DrinkPage.game_key,
            room_id=room_id,
            room_code=room_code,
            count=count,
        )

    def _refresh(self, page):
        try:
            page.try_call_page_method("_refreshRoomState")
        except Exception:
            try:
                page.try_call_page_method("loadView")
            except Exception:
                pass
        page.sleep(1.5)
        return page

    def test_two_players_dynamic_start(self):
        page = DrinkPage(self)
        info = page.create_room(cloud=self.cloud)
        self._seed(info["roomId"], info["roomCode"], self.min_players - 1)
        self._refresh(page)
        page.wait_member_count_at_least(self.min_players)
        page.start_round()
        page.assert_no_error_toast_or_modal()

    def test_countdown_no_false_ring_flash(self):
        """倒计时阶段不应闪屏/响铃（未揭晓前）。"""
        page = DrinkPage(self)
        info = page.create_room(cloud=self.cloud)
        self._seed(info["roomId"], info["roomCode"], 1)
        self._refresh(page)
        page.wait_member_count_at_least(2)
        page.start_round()
        page.wait_until(
            lambda: page.data_value("inCountdown")
            or (page.data_value("state") or {}).get("phase") == "countdown",
            timeout=15,
            message="未进入抽签倒计时",
        )
        self.assertFalse(
            bool(page.data_value("ringFlash")),
            "倒计时阶段不应出现响铃闪屏",
        )
        state = page.data_value("state") or {}
        if state.get("phase") == "countdown":
            self.assertFalse(
                bool(page.data_value("iAmRinger")),
                "倒计时阶段不应标记为响铃者",
            )
        page.sleep(2)
        if (page.data_value("state") or {}).get("phase") == "countdown":
            self.assertFalse(
                bool(page.data_value("ringFlash")),
                "倒计时期间仍出现闪屏",
            )


if __name__ == "__main__":
    unittest.main()
