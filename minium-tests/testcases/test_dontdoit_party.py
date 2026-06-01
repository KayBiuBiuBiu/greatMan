from base.base_test import BaseMiniTest
from pages.dontdoit_page import DontdoitPage


class TestDontdoitParty(BaseMiniTest):
    """不要做挑战 Minium 测试套件"""

    def test_09_dontdoit_core_flow(self):
        """
        测试流程：
        1. 主持人创建房间
        2. 玩家加入（3人）
        3. 所有玩家输入禁止动作
        4. 主持人点击开始，系统随机分配
        5. 玩家自认犯规（淘汰）
        """
        page = DontdoitPage(self)

        # 1. 主持人创建房间
        info = page.create_room(cloud=self.cloud)
        room_code = info.get("roomCode")
        self.assertTrue(room_code, "dontdoit did not return roomCode")
        room_id = info.get("roomId")

        # 2. 种子玩家加入（2个陪玩）
        seed = self._seed(page.game_key, info, count=2)
        self.assertEqual(len(seed), 2, "Should seed 2 players")

        # 3. 所有玩家输入禁止动作
        page.input_my_action("不能说话")
        self.sleep(0.5)

        # 等待其他玩家准备
        self._wait_members(page, 3, seed, room_id=room_id, seed_added=2)
        self._inject_players_for_ui(page, 3)

        # 4. 主持人点击开始挑战
        page.start_game(cloud=self.cloud, room_id=room_id, room_code=room_code)
        self.sleep(2)

        # 验证游戏已开始
        view = page.data_value("view") or {}
        self.assertEqual(view.get("status"), "playing", "Game should be in playing state")

        # 5. 验证禁止动作已分配（我的应该显示为"保密"）
        players = view.get("players") or []
        my_player = next((p for p in players if p.get("openId") == view.get("myOpenId")), None)
        self.assertIsNotNone(my_player, "Current player should be in players list")
        self.assertEqual(my_player.get("displayAction"), "保密", "My action should be hidden as '保密'")

        # 6. 玩家自认犯规
        page.trigger_self()
        self.sleep(1)

        # 验证玩家被淘汰
        view = page.data_value("view") or {}
        self.assertTrue(page.data_value("iAmEliminated"), "Player should be eliminated")

    def test_18_dontdoit_insufficient_players(self):
        """
        测试不足人数场景：
        1. 创建房间（1人）
        2. 验证无法开始（人数不足）
        3. 加入玩家使人数足够
        4. 验证可以开始
        """
        page = DontdoitPage(self)

        # 1. 创建房间
        info = page.create_room(cloud=self.cloud)
        room_code = info.get("roomCode")
        room_id = info.get("roomId")

        # 2. 验证无法开始（只有主持人1人）
        page.input_my_action("不能微笑")
        view = page.data_value("view") or {}
        player_count = len(view.get("players") or [])
        self.assertLess(player_count, 2, "Should have less than 2 players initially")

        can_start = page.data_value("canStart")
        self.assertFalse(can_start, "Should not be able to start with < 2 players")

        # 3. 种子玩家加入使人数足够
        seed = self._seed(page.game_key, info, count=1)
        self.sleep(1)

        # 4. 验证可以开始
        self._wait_members(page, 2, seed, room_id=room_id, seed_added=1)
        self._inject_players_for_ui(page, 2)

        self.assertTrue(
            page.data_value("canStart"),
            "Should be able to start with >= 2 players"
        )

        # 5. 点击开始验证游戏启动
        page.start_game(cloud=self.cloud, room_id=room_id, room_code=room_code)
        self.sleep(1)

        view = page.data_value("view") or {}
        self.assertEqual(view.get("status"), "playing", "Game should start successfully")
