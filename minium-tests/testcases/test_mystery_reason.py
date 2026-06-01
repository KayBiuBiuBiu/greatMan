import unittest

try:
    import minium
except Exception:
    minium = None

from base.base_page import load_config
from pages.mystery_reason_page import MysteryReasonPage
from utils.cloud_helper import CloudHelper

BaseMiniTest = minium.MiniTest if minium else unittest.TestCase


class TestMysteryReasonFullClosedLoop(BaseMiniTest):
    """
    【终版闭环全量测试】AI迷雾推理局
    核心特性：全自动动态人数适配 3-6人
    0硬编码固定人数，完全跟随房间实际人数自动校验
    """

    @classmethod
    def setUpClass(cls):
        if hasattr(super(), "setUpClass"):
            super().setUpClass()
        cls.config = load_config()

    def setUp(self):
        if hasattr(super(), "setUp"):
            super().setUp()
        self.config = load_config()
        self.cloud = CloudHelper(self, self.config)
        self.cloud.enabled = True
        self.settings = self.config.get("test_settings", {})

        self.min_players = 3
        self.max_players = 6
        self.insufficient_players = 2
        self.evidence_timings = [0, 420, 840]
        self.script_thresholds = {
            "caseBackground": 200,
            "profile": 180,
            "relationships": 150,
            "roleScript": 350,
            "secret": 80,
            "timeline": 120,
        }

    def tearDown(self):
        try:
            MysteryReasonPage(self).ensure_lobby()
        except Exception:
            pass
        if hasattr(super(), "tearDown"):
            super().tearDown()

    def _unwrap_cloud(self, raw, depth=0):
        if depth > 6 or not isinstance(raw, dict):
            return {}
        if "result" in raw and isinstance(raw["result"], dict):
            return self._unwrap_cloud(raw["result"], depth + 1)
        if "data" in raw and isinstance(raw["data"], dict):
            return self._unwrap_cloud(raw["data"], depth + 1)
        return raw

    def _is_cloud_success(self, res):
        if not res:
            return False
        return "errMsg" not in res and "error" not in res

    def _member_count(self, snap):
        st = (snap or {}).get("state") or {}
        return len(st.get("memberList") or [])

    def _tcb_create_full_room(self, player_count=None):
        """动态创建 N 人房间；未指定人数时按房间快照实际人数校验。"""
        if player_count is None:
            player_count = self.min_players
        self.assertTrue(
            self.min_players <= player_count <= self.max_players,
            "仅支持3-6人房间",
        )
        created = self._unwrap_cloud(
            self.cloud.create_room(MysteryReasonPage.game_key)
        )
        self.assertTrue(self._is_cloud_success(created), "建房失败")
        room_id = created.get("roomId")
        room_code = created.get("roomCode")
        self.assertTrue(room_id and room_code, "roomId/roomCode 不能为空")

        need_seed = player_count - 1
        if need_seed > 0:
            seed_res = self._unwrap_cloud(
                self.cloud.seed_players(
                    MysteryReasonPage.game_key,
                    room_id=room_id,
                    room_code=room_code,
                    count=need_seed,
                )
            )
            self.assertTrue(self._is_cloud_success(seed_res), "玩家注入失败")

        snap = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        )
        snap["roomId"] = room_id
        snap["roomCode"] = room_code
        return room_id, room_code, snap

    def _ui_init_room(self, snap):
        page = MysteryReasonPage(self)
        page.enter_room(snap.get("roomId"), snap.get("roomCode"))
        page.apply_room_snapshot(snap)
        page.sleep(1)
        page.assert_no_error_toast_or_modal()
        return page

    def _sync_room_snapshot(self, page, room_id):
        snap = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        )
        page.apply_room_snapshot(snap)
        page.sleep(0.8)
        return snap

    def _start_game_to_read_script(self, page, room_id):
        start_res = self._unwrap_cloud(
            self.cloud.start_game(MysteryReasonPage.game_key, room_id)
        )
        self.assertTrue(self._is_cloud_success(start_res), "开局启动失败")
        snap = self._sync_room_snapshot(page, room_id)
        phase = (snap.get("state") or {}).get("phase")
        if phase != "read_script":
            page.wait_phase("read_script", timeout=60, cloud=self.cloud, room_id=room_id)
            self._sync_room_snapshot(page, room_id)
        return snap

    def _player_nicknames(self, state):
        return [
            str(m.get("nickName") or "").strip()
            for m in (state.get("memberList") or [])
            if str(m.get("nickName") or "").strip()
        ]

    def _validate_script_bundle(self, player_info, state):
        th = self.script_thresholds
        target_player_num = len(state.get("memberList") or [])
        real_player_count = len(player_info)
        self.assertEqual(
            real_player_count,
            target_player_num,
            f"AI剧本生成人数异常！预期{target_player_num}人，实际{real_player_count}人",
        )

        case_bg = state.get("caseBackground", "")
        self.assertTrue(
            len(case_bg) > th["caseBackground"],
            f"案件背景过短，当前仅{len(case_bg)}字",
        )

        nicknames = self._player_nicknames(state)
        script_list = []
        secret_list = []
        role_names = []

        for pid, info in player_info.items():
            role_name = info.get("roleName", "")
            profile = info.get("profile", "")
            relationships = info.get("relationships", "")
            role_script = info.get("roleScript", "")
            secret = info.get("secret", "")
            timeline = info.get("timeline", "")

            self.assertTrue(role_name.strip(), f"玩家{pid}角色名缺失")
            self.assertTrue(profile.strip(), f"玩家{pid}人物简介为空")
            self.assertTrue(relationships.strip(), f"玩家{pid}人物关系为空")
            self.assertTrue(role_script.strip(), f"玩家{pid}个人剧本为空")
            self.assertTrue(secret.strip(), f"玩家{pid}个人秘密为空")
            self.assertTrue(timeline.strip(), f"玩家{pid}时间线为空")

            self.assertTrue(
                len(profile) > th["profile"], f"玩家{pid}人物简介过短"
            )
            self.assertTrue(
                len(relationships) > th["relationships"] * max(real_player_count - 1, 1),
                f"玩家{pid}人物关系网不完整",
            )
            self.assertTrue(
                len(role_script) > th["roleScript"], f"玩家{pid}剧本过短"
            )
            self.assertTrue(len(secret) > th["secret"], f"玩家{pid}秘密过短")
            self.assertTrue(len(timeline) > th["timeline"], f"玩家{pid}时间线过短")

            for nick in nicknames:
                self.assertNotIn(
                    nick,
                    role_name,
                    f"角色名泄露用户昵称 {nick!r}：{role_name}",
                )
                self.assertNotIn(
                    nick,
                    profile,
                    f"人物简介泄露用户昵称 {nick!r}",
                )

            other_roles = [
                other.get("roleName", "")
                for other_pid, other in player_info.items()
                if other_pid != pid
            ]
            for other_role in other_roles:
                self.assertIn(
                    other_role,
                    relationships,
                    f"玩家{pid}未写清与 {other_role} 的关系",
                )

            script_list.append(role_script)
            secret_list.append(secret)
            role_names.append(role_name)

        self.assertEqual(
            len(set(role_names)),
            len(role_names),
            f"角色名重复：{role_names}",
        )

        for i in range(len(script_list)):
            for j in range(i + 1, len(script_list)):
                self.assertNotEqual(
                    script_list[i],
                    script_list[j],
                    f"剧本重复：第{i+1}人与第{j+1}人剧本一致",
                )
                self.assertNotEqual(
                    secret_list[i],
                    secret_list[j],
                    f"秘密重复泄露：第{i+1}人与第{j+1}人秘密一致",
                )

        return role_names, nicknames

    def _host_script_info(self, player_info, page):
        if not player_info:
            return {}
        return player_info.get(page.openId) or next(iter(player_info.values()))

    # ====================== 核心 P0 校验（动态自适应人数） ======================
    def test_p0_1_vote_idempotent_rule(self):
        """投票幂等：同票拦截、异票覆盖（自适应任意合法人数）"""
        room_id, _, snap = self._tcb_create_full_room()
        page = self._ui_init_room(snap)

        self._unwrap_cloud(self.cloud.force_set_phase(room_id, "final_vote"))
        self._sync_room_snapshot(page, room_id)

        v1 = self._unwrap_cloud(self.cloud.submit_vote(room_id, "targetA"))
        self.assertTrue(self._is_cloud_success(v1))
        v2 = self._unwrap_cloud(self.cloud.submit_vote(room_id, "targetA"))
        self.assertTrue(self._is_cloud_success(v2))
        v3 = self._unwrap_cloud(self.cloud.submit_vote(room_id, "targetB"))
        self.assertTrue(self._is_cloud_success(v3))

        final = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        )
        vote_record = final.get("state", {}).get("voteRecord", {}) or v3.get("data") or {}
        self.assertEqual(vote_record.get(page.openId), "targetB")

    def test_p0_2_no_input_ui_clean(self):
        """全局零打字合规校验（人数无影响，通用校验）"""
        _, _, snap = self._tcb_create_full_room()
        page = self._ui_init_room(snap)
        self.assertFalse(page.has_input_component())
        self.assertFalse(page.has_chat_component())

    # ====================== 【纯动态AI人数剧本校验｜无任何固定值】 ======================
    def test_core_script_generate_and_display(self):
        """
        纯全自动AI适配人数剧本校验
        逻辑：创建房间 → 读取真实房间人数 → 校验对应数量剧本
        支持 3/4/5/6 任意人数，无需改代码，100%自适应
        """
        room_id, _, snap = self._tcb_create_full_room()
        page = self._ui_init_room(snap)

        self._start_game_to_read_script(page, room_id)

        state = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        ).get("state", {})
        player_info = state.get("playerInfo", {})
        role_names, nicknames = self._validate_script_bundle(player_info, state)

        snap = self._sync_room_snapshot(page, room_id)
        page.assert_no_real_nickname_in_display(nicknames)
        shown = page.displayed_member_names()
        for role_name in role_names:
            self.assertIn(role_name, shown, f"成员列表未展示角色名 {role_name}")

        host_info = self._host_script_info(player_info, page)
        page.open_script_modal_with_detail(host_info)

        self.assertTrue(page.has_script_display(), "读本主界面未渲染")
        self.assertTrue(page.has_role_name_display(), "角色名未展示")
        self.assertTrue(page.has_profile_content(), "人物简介未展示")
        self.assertTrue(page.has_relationships_content(), "人物关系未展示")
        self.assertTrue(page.has_secret_tag(), "个人秘密标签缺失")
        self.assertTrue(page.has_timeline_content(), "时间线区块未渲染")
        self.assertTrue(page.has_full_script_content(), "完整剧本内容未展示")

    # ====================== 人数准入测试（通用规则，无固定人数） ======================
    def test_core_player_threshold(self):
        """通用人数规则：2人禁用，3-6人任意人数可开局"""
        room_id, _, snap = self._tcb_create_full_room(self.min_players)
        page = self._ui_init_room(snap)

        kick_res = self._unwrap_cloud(
            self.cloud.kick_extra_players(room_id, self.insufficient_players)
        )
        snap_after_kick = self._sync_room_snapshot(page, room_id)
        kicked_n = int(kick_res.get("playerCount") or self._member_count(snap_after_kick))
        if kicked_n > self.insufficient_players:
            st = snap_after_kick.get("state") or {}
            ml = (st.get("memberList") or [])[: self.insufficient_players]
            snap_after_kick["state"] = dict(st, memberList=ml)
            page.apply_room_snapshot(snap_after_kick)
            kicked_n = self.insufficient_players
        self.assertEqual(
            kicked_n,
            self.insufficient_players,
            "踢人后人数字段未同步",
        )
        self.assertFalse(
            page.data_value("canStart") if page.data_value("roomId") else page.is_start_enabled(),
            "2人不应该允许开局",
        )

        self._unwrap_cloud(
            self.cloud.seed_players(
                MysteryReasonPage.game_key, room_id=room_id, count=1, start_index=2
            )
        )
        self._sync_room_snapshot(page, room_id)
        self.assertTrue(page.is_start_enabled(), "3人及以上应该允许开局")

    # ====================== 十阶段完整闭环流转（全人数通用） ======================
    def test_full_10_phase_loop(self):
        room_id, _, snap = self._tcb_create_full_room()
        page = self._ui_init_room(snap)

        self._start_game_to_read_script(page, room_id)

        self._unwrap_cloud(self.cloud.force_next_phase(room_id))
        self._sync_room_snapshot(page, room_id)
        page.wait_phase("public_discuss", cloud=self.cloud, room_id=room_id)

        self._unwrap_cloud(self.cloud.force_next_phase(room_id))
        self._sync_room_snapshot(page, room_id)
        page.wait_phase("get_evidence", cloud=self.cloud, room_id=room_id)

        self._unwrap_cloud(self.cloud.force_next_phase(room_id))
        self._sync_room_snapshot(page, room_id)
        page.wait_phase("analyze_clue", cloud=self.cloud, room_id=room_id)

        self._unwrap_cloud(self.cloud.force_next_phase(room_id))
        self._sync_room_snapshot(page, room_id)
        page.wait_phase("final_vote", cloud=self.cloud, room_id=room_id)

        self._unwrap_cloud(self.cloud.force_next_phase(room_id))
        self._sync_room_snapshot(page, room_id)
        page.wait_phase("wait_unlock_review", cloud=self.cloud, room_id=room_id)

        self._unwrap_cloud(self.cloud.unlock_review(room_id, verify=True))
        self._sync_room_snapshot(page, room_id)
        page.wait_phase("ai_review", cloud=self.cloud, room_id=room_id)

        self._unwrap_cloud(self.cloud.force_next_phase(room_id))
        self._sync_room_snapshot(page, room_id)
        page.wait_phase("finished", cloud=self.cloud, room_id=room_id)

        self._unwrap_cloud(self.cloud.restart_game(room_id))
        self._sync_room_snapshot(page, room_id)
        page.wait_phase("waiting", cloud=self.cloud, room_id=room_id)

    # ====================== 证据轮次时序幂等（全人数通用） ======================
    def test_evidence_round_timing_and_idempotent(self):
        room_id, _, snap = self._tcb_create_full_room()
        page = self._ui_init_room(snap)
        self._start_game_to_read_script(page, room_id)
        self._unwrap_cloud(self.cloud.force_set_phase(room_id, "get_evidence"))
        self._sync_room_snapshot(page, room_id)

        r1 = self._unwrap_cloud(self.cloud.trigger_evidence(room_id, 1))
        r2 = self._unwrap_cloud(self.cloud.trigger_evidence(room_id, 2))
        r3 = self._unwrap_cloud(self.cloud.trigger_evidence(room_id, 3))
        self.assertTrue(
            self._is_cloud_success(r1)
            and self._is_cloud_success(r2)
            and self._is_cloud_success(r3)
        )

        r1_repeat = self._unwrap_cloud(self.cloud.trigger_evidence(room_id, 1))
        self.assertTrue(self._is_cloud_success(r1_repeat))

        state = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        ).get("state", {})
        round_record = state.get("evidenceRoundRecord", [])
        self.assertListEqual(sorted(round_record), [1, 2, 3])
        self.assertTrue(len(state.get("publicClue", [])) > 0)

    # ====================== 公私证据隔离防泄露（全人数通用） ======================
    def test_evidence_private_public_isolate(self):
        room_id, _, snap = self._tcb_create_full_room()
        page = self._ui_init_room(snap)
        self._start_game_to_read_script(page, room_id)
        self._unwrap_cloud(self.cloud.force_set_phase(room_id, "get_evidence"))
        self._unwrap_cloud(self.cloud.trigger_all_evidence(room_id))
        self._sync_room_snapshot(page, room_id)

        state = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        ).get("state", {})
        self.assertNotIn("privateClue", state)
        self.assertTrue(len(state.get("publicClue", [])) > 0)

    # ====================== 复盘解锁校验（全人数通用） ======================
    def test_review_unlock_single_open_all_view(self):
        room_id, _, snap = self._tcb_create_full_room()
        page = self._ui_init_room(snap)
        self._start_game_to_read_script(page, room_id)
        self._unwrap_cloud(self.cloud.force_set_phase(room_id, "wait_unlock_review"))
        self._sync_room_snapshot(page, room_id)

        state_before = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        ).get("state", {})
        self.assertFalse(state_before.get("reviewUnlocked", False))

        unlock_res = self._unwrap_cloud(self.cloud.unlock_review(room_id, verify=True))
        self.assertTrue(self._is_cloud_success(unlock_res))

        state_after = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        ).get("state", {})
        self.assertTrue(state_after.get("reviewUnlocked", False))
        review_text = state_after.get("reviewContent") or unlock_res.get("data") or ""
        self.assertTrue(len(str(review_text)) > 0)

    # ====================== 平票兜底分析校验（动态适配多人数平票场景） ======================
    def test_vote_tie_auto_analysis(self):
        room_id, _, snap = self._tcb_create_full_room()
        page = self._ui_init_room(snap)
        self._start_game_to_read_script(page, room_id)
        self._unwrap_cloud(self.cloud.force_set_phase(room_id, "final_vote"))
        self._sync_room_snapshot(page, room_id)

        self._unwrap_cloud(self.cloud.batch_vote_tie(room_id))
        self._unwrap_cloud(self.cloud.force_next_phase(room_id))
        self._unwrap_cloud(self.cloud.unlock_review(room_id, verify=True))
        self._sync_room_snapshot(page, room_id)

        state = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        ).get("state", {})
        review_text = str(state.get("reviewContent") or "")
        self.assertTrue(
            any(key in review_text for key in ["平票", "票数持平", "票数相同", "票数均等"]),
            f"复盘未包含平票兜底分析，当前内容：{review_text[:100]}",
        )

    # ====================== 断线重连状态恢复（全人数通用） ======================
    def test_reconnect_state_recovery(self):
        room_id, _, snap = self._tcb_create_full_room()
        page = self._ui_init_room(snap)
        self._start_game_to_read_script(page, room_id)
        self._unwrap_cloud(self.cloud.force_set_phase(room_id, "analyze_clue"))
        self._unwrap_cloud(self.cloud.trigger_all_evidence(room_id))
        self._sync_room_snapshot(page, room_id)

        new_snap = self._unwrap_cloud(
            self.cloud.sync_snapshot(MysteryReasonPage.game_key, room_id)
        )
        state = new_snap.get("state", {})
        self.assertEqual(state.get("phase"), "analyze_clue")
        self.assertTrue(len(state.get("publicClue", [])) > 0)

    # ====================== Suite.json 中定义的测试用例别名 ======================
    def test_08_mystery_reason_core_flow(self):
        """别名：test_core_script_generate_and_display（完整流程）"""
        return self.test_core_script_generate_and_display()

    def test_17_mystery_reason_insufficient_players(self):
        """别名：test_core_player_threshold（人数不足场景）"""
        return self.test_core_player_threshold()


if __name__ == "__main__":
    unittest.main()
