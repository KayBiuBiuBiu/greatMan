import unittest

try:
    import minium
except Exception:
    minium = None

from base.base_page import load_config
from pages.undercover_page import UndercoverPage
from utils.cloud_helper import CloudHelper

BaseMiniTest = minium.MiniTest if minium else unittest.TestCase


class TestUndercoverDynamicPlayers(BaseMiniTest):
    """谁是卧底：动态人数（进多少人就多少人），至少 3 人可开局。"""

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
        self.min_players = 3
        self.max_players = 12

    def tearDown(self):
        try:
            UndercoverPage(self).ensure_lobby()
        except Exception:
            pass
        if hasattr(super(), "tearDown"):
            super().tearDown()

    def _unwrap(self, raw, depth=0):
        if depth > 6 or not isinstance(raw, dict):
            return {}
        if "result" in raw and isinstance(raw["result"], dict):
            return self._unwrap(raw["result"], depth + 1)
        if "data" in raw and isinstance(raw["data"], dict):
            return self._unwrap(raw["data"], depth + 1)
        return raw

    def _create_room(self, page):
        created = self._unwrap(
            self.cloud.create_room(UndercoverPage.game_key)
        )
        self.assertTrue(created.get("roomId") and created.get("roomCode"))
        page.enter_room(created["roomId"], created["roomCode"])
        return created

    def _seed(self, room_id, room_code, count, start_index=1):
        return self._unwrap(
            self.cloud.seed_players(
                UndercoverPage.game_key,
                room_id=room_id,
                room_code=room_code,
                count=count,
                start_index=start_index,
            )
        )

    def _refresh(self, page, room_id):
        page.refresh_lobby(cloud=self.cloud, room_id=room_id)
        return page

    def _assert_can_start(self, page, player_count, room_id=None):
        self.assertGreaterEqual(page.member_count(), player_count)
        self.assertTrue(
            page.wait_until_start_enabled(cloud=self.cloud, room_id=room_id),
            "组长应可开始互动",
        )

    def test_three_players_can_start_without_target_count(self):
        """3 人即可开局，无需设定目标人数。"""
        page = UndercoverPage(self)
        info = page.create_room()
        self._seed(info["roomId"], info["roomCode"], self.min_players - 1)
        self._refresh(page, info["roomId"])
        self.assertFalse(page.has_target_player_stepper())
        self._assert_can_start(page, self.min_players, info["roomId"])
        page.start_game()
        page.assert_no_error_toast_or_modal()
        page.wait_in_word_phase(timeout=30)

    def test_four_players_dynamic_start(self):
        """4 人进组即可 4 人局，无需凑满 6 人。"""
        page = UndercoverPage(self)
        info = page.create_room()
        self._seed(info["roomId"], info["roomCode"], 3)
        self._refresh(page, info["roomId"])
        self._assert_can_start(page, 4, info["roomId"])
        page.start_game()
        page.wait_in_word_phase(timeout=30)

    def test_two_players_blocked(self):
        """2 人不足，不可开局。"""
        page = UndercoverPage(self)
        info = page.create_room()
        self._seed(info["roomId"], info["roomCode"], 1)
        self._refresh(page, info["roomId"])
        self.assertEqual(page.member_count(), 2)
        self.assertFalse(page.is_start_enabled())


if __name__ == "__main__":
    unittest.main()
