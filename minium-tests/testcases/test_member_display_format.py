"""
验证所有游戏的成员显示格式已改为"当前X人"
"""
import unittest

try:
    import minium
except Exception:
    minium = None

from base.base_page import load_config
from pages.dontdoit_page import DontdoitPage
from pages.mystery_reason_page import MysteryReasonPage
from pages.draw_page import DrawPage
from utils.cloud_helper import CloudHelper

BaseMiniTest = minium.MiniTest if minium else unittest.TestCase


class TestMemberDisplayFormat(BaseMiniTest):
    """成员显示格式统一验证"""

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
        self.settings = self.config.get("test_settings", {})

    def _seed(self, game_key, info, count):
        return self.cloud.seed_players(
            game_key,
            room_id=info.get("roomId") or info.get("id"),
            room_code=info.get("roomCode"),
            count=count,
        )

    def test_01_dontdoit_member_display(self):
        """验证不要做挑战成员显示为'当前X人'"""
        page = DontdoitPage(self)

        # 创建房间
        info = page.create_room(cloud=self.cloud)
        room_id = info.get("roomId")
        self.assertTrue(room_id, "dontdoit roomId not created")

        # 加入2个玩家
        seed = self._seed(page.game_key, info, count=2)
        self.cloud.wait_for_cloud_settle(1)

        # 验证成员显示格式
        member_count_line = page.data_value("memberCountLine")
        self.assertIsNotNone(member_count_line, "memberCountLine should exist")
        print(f"[✓] dontdoit memberCountLine: {member_count_line}")

        # 验证格式为"当前X人"（不包含"/"）
        self.assertNotIn('/', member_count_line,
                        f"memberCountLine should not contain '/', got: {member_count_line}")
        self.assertIn('当前', member_count_line,
                     f"memberCountLine should contain '当前', got: {member_count_line}")
        self.assertIn('人', member_count_line,
                     f"memberCountLine should contain '人', got: {member_count_line}")

    def test_02_mystery_reason_member_display(self):
        """验证秘密身份推理成员显示为'当前X人'"""
        page = MysteryReasonPage(self)

        # 创建房间
        info = page.create_room(cloud=self.cloud, difficulty="新手")
        room_id = info.get("roomId")
        self.assertTrue(room_id, "mysteryReason roomId not created")

        # 加入3个玩家
        seed = self._seed(page.game_key, info, count=3)
        self.cloud.wait_for_cloud_settle(1)

        # 验证成员显示格式
        member_count_line = page.data_value("memberCountLine")
        self.assertIsNotNone(member_count_line, "memberCountLine should exist")
        print(f"[✓] mysteryReason memberCountLine: {member_count_line}")

        # 验证格式为"当前X人"（不包含"/"）
        self.assertNotIn('/', member_count_line,
                        f"memberCountLine should not contain '/', got: {member_count_line}")
        self.assertIn('当前', member_count_line,
                     f"memberCountLine should contain '当前', got: {member_count_line}")
        self.assertIn('人', member_count_line,
                     f"memberCountLine should contain '人', got: {member_count_line}")

    def test_03_draw_guess_member_display(self):
        """验证你画我猜成员显示为'当前X人'"""
        page = DrawPage(self)

        # 创建房间
        info = page.create_room(cloud=self.cloud)
        room_id = info.get("roomId")
        self.assertTrue(room_id, "drawGuess roomId not created")

        # 加入2个玩家
        seed = self._seed(page.game_key, info, count=2)
        self.cloud.wait_for_cloud_settle(1)

        # 刷新大厅 UI（seed 后必须刷新才能获取新人数）
        page.refresh_lobby(cloud=self.cloud, room_id=room_id)

        # 验证成员显示格式
        member_count_line = page.data_value("memberCountLine")
        self.assertIsNotNone(member_count_line, "memberCountLine should exist")
        print(f"[✓] drawGuess memberCountLine: {member_count_line}")

        # 验证格式为"当前X人"（不包含"/"）
        self.assertNotIn('/', member_count_line,
                        f"memberCountLine should not contain '/', got: {member_count_line}")
        self.assertIn('当前', member_count_line,
                     f"memberCountLine should contain '当前', got: {member_count_line}")
        self.assertIn('人', member_count_line,
                     f"memberCountLine should contain '人', got: {member_count_line}")

    def test_04_dontdoit_status_hint_format(self):
        """验证不要做挑战游戏中statusHint显示格式"""
        page = DontdoitPage(self)

        # 创建房间并加入玩家
        info = page.create_room(cloud=self.cloud)
        room_id = info.get("roomId")
        seed = self._seed(page.game_key, info, count=2)
        self.cloud.wait_for_cloud_settle(1)

        # 输入禁止动作
        page.input_my_action("不能说话")
        page.sleep(0.5)

        # 启动游戏
        page.start_game(cloud=self.cloud, room_id=room_id)
        page.sleep(2)

        # 验证statusHint格式
        status_hint = page.data_value("statusHint")
        self.assertIsNotNone(status_hint, "statusHint should exist during playing")
        print(f"[✓] dontdoit statusHint: {status_hint}")

        # 验证包含"当前"和"存活"（不是"/"格式）
        self.assertIn('当前', status_hint,
                     f"statusHint should contain '当前', got: {status_hint}")
        self.assertIn('人存活', status_hint,
                     f"statusHint should contain '人存活', got: {status_hint}")
        self.assertNotIn(' / ', status_hint,
                        f"statusHint should not contain ' / ', got: {status_hint}")
