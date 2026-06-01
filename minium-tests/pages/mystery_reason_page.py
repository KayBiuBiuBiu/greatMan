import json
import re
import time
from urllib.parse import quote, urlencode

from base.base_page import BasePage


class MysteryReasonPage(BasePage):
    path = "/packageGames/mystery-reason/mystery-reason"
    game_key = "mysteryReason"
    min_players = 3
    HOST_OPEN_ID = "minium_test_host"

    PHASE_ZH = {
        "waiting": "等待开局",
        "generate_script": "AI 生成剧本",
        "read_script": "读本",
        "public_discuss": "公聊推理",
        "get_evidence": "证据派发",
        "analyze_clue": "线索辩论",
        "final_vote": "投票",
        "wait_unlock_review": "解锁复盘",
        "ai_review": "AI 复盘",
        "finished": "对局结束",
    }

    def open(self):
        return self.navigate(self.path)

    def ensure_lobby(self):
        """离开残留对局，回到未进组大厅。"""
        try:
            self.app.relaunch(self.path)
        except Exception:
            try:
                self.app.reLaunch(self.path)
            except Exception:
                self.open()
        self.sleep(1.5)
        rid = self.data_value("roomId")
        if rid:
            self.log(f"warn: still in room {rid} after relaunch")
        return self

    def apply_room_snapshot(self, snap):
        """注入房内 UI（优先 Page 方法，否则 setData）。"""
        snap = dict(snap or {})
        snap["skipPoll"] = True
        st = snap.get("state") or {}
        v = snap.get("view") or {}
        pl = [
            {
                "openId": m.get("openId"),
                "nickName": m.get("nickName"),
                "roleName": m.get("roleName") or "",
                "displayName": m.get("displayName") or m.get("roleName") or m.get("nickName"),
                "avatarUrl": m.get("avatarUrl") or "",
                "isReady": bool(m.get("isReady")),
            }
            for m in (st.get("memberList") or [])
        ]
        n = len(pl)
        host_oid = st.get("hostOpenId") or ""
        is_host = bool(v.get("isHost")) or host_oid == self.HOST_OPEN_ID
        phase = st.get("phase") or "waiting"
        payload = {
            "roomId": str(snap.get("roomId") or ""),
            "roomCode": str(snap.get("roomCode") or st.get("roomCode") or ""),
            "joinCode": str(snap.get("roomCode") or st.get("roomCode") or ""),
            "pub": st,
            "view": v,
            "phase": phase,
            "phaseZh": {
                "waiting": "等待开局",
                "generate_script": "AI 生成剧本",
                "read_script": "读本",
                "public_discuss": "公聊推理",
                "get_evidence": "证据派发",
                "analyze_clue": "线索辩论",
                "final_vote": "投票",
                "wait_unlock_review": "解锁复盘",
                "ai_review": "AI 复盘",
                "finished": "对局结束",
            }.get(phase, phase),
            "phaseRemainingSeconds": st.get("phaseRemainingSeconds") or 0,
            "isHost": is_host,
            "displayPlayers": pl,
            "memberCountLine": str(n) + "/" + str(max(n, 3)),
            "canStart": is_host and n >= 3 and phase == "waiting",
            "statusHint": "人齐后组长可开始互动" if n >= 3 else "至少 3 人才能开始互动",
        }
        try:
            self.try_call_page_method("applyTestRoomBootstrap", snap)
        except Exception as exc:
            self.log(f"applyTestRoomBootstrap: {exc}")
            try:
                self.page.data = payload
            except Exception as exc2:
                self.log(f"page.data failed: {exc2}")
            try:
                self.try_call_page_method("stopInRoomPollForTest")
            except Exception:
                pass
        self.sleep(1)
        return self

    def is_start_enabled(self):
        data = self.page_data()
        if data.get("roomId"):
            if data.get("canStart") is not None:
                return bool(data.get("canStart"))
            pl = data.get("displayPlayers") or []
            if pl and (data.get("phase") or "waiting") == "waiting":
                return len(pl) >= 3 and bool(data.get("isHost"))
        return super().is_start_enabled()

    @property
    def openId(self):
        return self.HOST_OPEN_ID

    def wait_phase(self, phase, timeout=120, cloud=None, room_id=None):
        label = self.PHASE_ZH.get(phase, phase)
        return self.wait_phase_text(label, timeout=timeout, cloud=cloud, room_id=room_id)

    def has_input_component(self):
        for selector in ("input", "textarea"):
            try:
                if self.page.get_elements(selector):
                    return True
            except Exception:
                pass
        return False

    def has_chat_component(self):
        for selector in ("textarea", ".chat-input", ".mr-chat", "input"):
            try:
                if self.page.get_elements(selector):
                    return True
            except Exception:
                pass
        return False

    SCRIPT_UI_SECTIONS = (
        ("角色名", "roleName"),
        ("人物简介", "profile"),
        ("人物关系", "relationships"),
        ("个人剧情", "roleScript"),
        ("隐藏秘密", "secret"),
        ("时间线", "timeline"),
    )

    def open_script_modal_with_detail(self, detail):
        """云测注入四区块剧本并打开弹窗。"""
        self.try_call_page_method("applyTestScriptDetail", detail or {})
        self.sleep(0.8)
        self.wait_until(
            lambda: self.data_value("showScriptModal"),
            timeout=10,
            message="script modal not shown",
        )
        return self

    def assert_script_modal_sections(self, detail):
        """校验弹窗四区块标题与正文均已渲染。"""
        detail = dict(detail or {})
        self.open_script_modal_with_detail(detail)
        for label, key in self.SCRIPT_UI_SECTIONS:
            self.wait_for_text(label, selector="view", timeout=6)
            expected = str(detail.get(key) or "").strip()
            if not expected:
                raise AssertionError(f"弹窗区块 {label} 内容为空")
            try:
                body = self.get(
                    f".mr-script-section[data-section='{key}'] .mr-script-body",
                    timeout=4,
                )
                shown = str(getattr(body, "inner_text", "") or getattr(body, "text", "") or "").strip()
            except Exception:
                shown = str((self.data_value("scriptDetail") or {}).get(key) or "").strip()
            if not shown:
                raise AssertionError(f"弹窗区块 {label} 未渲染")
            head = expected[: min(12, len(expected))]
            if head not in shown:
                raise AssertionError(f"弹窗区块 {label} 与云侧剧本不一致")
        try:
            self.tap_any_text(["关闭"], selector="button", timeout=5)
        except Exception:
            pass
        return self

    def has_read_script_actions(self):
        if self.data_value("phase") != "read_script":
            return False
        try:
            self.wait_for_text("查看个人剧本", selector="button", timeout=5)
            return True
        except Exception:
            return False

    def has_script_display(self):
        return self.has_read_script_actions()

    def _script_detail(self):
        return self.data_value("scriptDetail") or {}

    def has_role_name_display(self):
        return bool(str(self._script_detail().get("roleName") or "").strip())

    def has_secret_tag(self):
        return bool(str(self._script_detail().get("secret") or "").strip())

    def has_timeline_content(self):
        return bool(str(self._script_detail().get("timeline") or "").strip())

    def has_full_script_content(self):
        d = self._script_detail()
        parts = [
            d.get("roleName"),
            d.get("profile"),
            d.get("relationships"),
            d.get("roleScript"),
            d.get("secret"),
            d.get("timeline"),
        ]
        return all(str(p or "").strip() for p in parts)

    def has_profile_content(self):
        return bool(str(self._script_detail().get("profile") or "").strip())

    def has_relationships_content(self):
        return bool(str(self._script_detail().get("relationships") or "").strip())

    def displayed_member_names(self):
        data = self.page_data()
        return [
            str(m.get("displayName") or m.get("roleName") or m.get("nickName") or "")
            for m in (data.get("displayPlayers") or [])
        ]

    def assert_no_real_nickname_in_display(self, nicknames):
        shown = self.displayed_member_names()
        for nick in nicknames:
            nick = str(nick or "").strip()
            if not nick:
                continue
            for name in shown:
                if nick in str(name or ""):
                    raise AssertionError(
                        f"页面仍展示用户昵称 {nick!r}，当前显示 {shown}"
                    )

    def open_read_script_modal(self, detail=None):
        if detail:
            self.open_script_modal_with_detail(detail)
            return self
        try:
            self.tap_any_text(["查看个人剧本"], selector="button", timeout=8)
            self.sleep(1)
        except Exception as exc:
            self.log(f"open_read_script_modal: {exc}")
        return self

    def open_script_and_read_text(self):
        try:
            self.tap_any_text(["查看个人剧本"], selector="button", timeout=10)
            self.sleep(1)
            text = str(self.data_value("scriptText") or "")
            if not text:
                try:
                    box = self.get(".mr-script-box", timeout=3)
                    text = str(getattr(box, "inner_text", "") or getattr(box, "text", "") or "")
                except Exception:
                    pass
            try:
                self.tap_any_text(["关闭"], selector="button", timeout=5)
            except Exception:
                pass
            return text
        except Exception as exc:
            self.log(f"open_script_and_read_text: {exc}")
            return ""

    def wait_phase_text(self, text, timeout=90, cloud=None, room_id=None):
        end = time.time() + timeout

        def matched():
            data = self.page_data()
            phase = str(data.get("phase") or "")
            phase_zh = str(data.get("phaseZh") or "")
            return text in (phase + " " + phase_zh)

        while time.time() < end:
            if matched():
                return self
            if cloud and room_id and cloud.enabled:
                try:
                    raw = cloud.sync_snapshot(self.game_key, room_id)
                    snap = raw
                    if isinstance(raw, dict) and raw.get("result") and isinstance(
                        raw["result"], dict
                    ):
                        snap = raw["result"]
                    if snap.get("state"):
                        self.apply_room_snapshot(snap)
                except Exception as exc:
                    self.log(f"sync while wait phase: {exc}")
            time.sleep(1)
        raise AssertionError(f"phase text {text!r} not reached")

    def enter_room(self, room_id, room_code):
        cfg = quote(
            json.dumps(
                {"roomId": str(room_id), "roomCode": str(room_code)},
                ensure_ascii=False,
            )
        )
        url = self.path + "?config=" + cfg
        try:
            self.app.reLaunch(url)
        except Exception:
            try:
                self.app.relaunch(url)
            except Exception:
                self.app.navigate_to(url)
        self.sleep(2)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=25,
            message="mystery enter_room failed",
        )
        return self.room_info()

    def create_room_via_setup(self):
        qs = urlencode({"title": "AI迷雾推理局", "screen": "mysteryReason"})
        self.app.navigate_to("/pages/setup/setup?" + qs)
        self.sleep(1)
        self.tap_any_text(["创建聚会组并进入"], selector="button", timeout=10)
        self.sleep(4)
        self.confirm_native_modal()
        self.sleep(2)
        self.wait_until(
            lambda: "mystery-reason" in (self.current_path() or ""),
            timeout=20,
            message="setup did not navigate to mystery-reason",
        )
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=25,
            message="mystery roomId not created via setup",
        )
        return self.room_info()

    def enter_numpad_code(self, room_code):
        code = re.sub(r"\D", "", str(room_code or ""))[:6]
        if len(code) != 6:
            raise ValueError(f"mystery room code must be 6 digits, got: {room_code!r}")
        for ch in code:
            self.get(".mr-numpad-key", inner_text=ch, timeout=4).click()
            self.sleep(0.12)
        return self

    def create_room(self):
        self.ensure_lobby()
        try:
            self.get(".mr-btn-create", timeout=5).click()
            self.sleep(0.5)
        except Exception:
            return self.create_room_via_setup()
        try:
            self.wait_for_text("聚会组口令", selector="view", timeout=12)
            self.confirm_native_modal()
        except Exception as exc:
            self.log(f"create modal confirm skipped: {exc}")
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=25,
            message="mystery roomId not created",
        )
        return self.room_info()

    def join_room(self, room_code):
        self.ensure_lobby()
        self.enter_numpad_code(room_code)
        try:
            self.get(".mr-btn-join", timeout=5).click()
        except Exception:
            self.tap_any_text(["加入聚会组"], selector="button", timeout=8)
        self.wait_until(
            lambda: self.data_value("roomId"),
            timeout=20,
            message="mystery join failed",
        )
        return self.room_info()

    def start_game(self):
        self.tap_any_text(["开始互动"], selector="button", timeout=10)
        self.sleep(2)
        return self

    def open_script_and_close(self):
        try:
            self.tap_any_text(["查看个人剧本"], selector="button", timeout=15)
            self.sleep(1)
            self.tap_any_text(["关闭"], selector="button", timeout=5)
        except Exception as exc:
            self.log(f"script modal skipped: {exc}")
        return self

    def mark_ready(self):
        try:
            self.tap_any_text(["我已读完", "就绪"], selector="button", timeout=6)
        except Exception as exc:
            self.log(f"mark_ready skipped: {exc}")
        return self

    def host_skip_phase(self):
        for label in [
            "组长跳过本阶段",
            "组长结束本阶段",
            "组长结束证据阶段",
        ]:
            try:
                self.tap_any_text([label], selector="button", timeout=3)
                self.sleep(1)
                return self
            except Exception:
                pass
        return self

    def tap_vote_first_target(self):
        try:
            rows = self.page.get_elements(".mr-vote-row")
            if rows:
                rows[0].click()
                self.confirm_native_modal()
                self.sleep(1)
        except Exception as exc:
            self.log(f"vote skipped: {exc}")
        return self

    def play_core_flow(self, cloud, room_id):
        """读本 → 公聊 → 证据 → 投票（长阶段用云测 tcb 推进）。"""
        self.wait_phase_text("读本", timeout=120, cloud=cloud, room_id=room_id)
        if cloud and cloud.enabled:
            cloud.mark_all_ready(self.game_key, room_id=room_id)
            snap = cloud.sync_snapshot(self.game_key, room_id)
            if snap.get("state"):
                self.apply_room_snapshot(snap)
            self.sleep(1)
        else:
            self.open_script_and_close()
            self.mark_ready()
        self.wait_phase_text("公聊", timeout=60)
        if cloud and cloud.enabled:
            for phase in ("get_evidence", "analyze_clue", "final_vote"):
                cloud.advance(self.game_key, room_id=room_id, phase=phase)
                snap = cloud.sync_snapshot(self.game_key, room_id)
                if snap.get("state"):
                    self.apply_room_snapshot(snap)
                self.sleep(1)
        else:
            self.host_skip_phase()
        try:
            self.wait_phase_text("投票", timeout=60)
        except Exception:
            pass
        self.assert_no_error_toast_or_modal()
        return self

    def room_info(self):
        pub = self.data_value("pub", default={}) or {}
        return {
            "roomId": self.data_value("roomId"),
            "roomCode": self.data_value("roomCode") or pub.get("roomCode"),
            "state": pub,
        }
