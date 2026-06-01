import json
import os
import subprocess
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent / "projects" / "wechat-mini" / "2026-04-26-family-party-games"


class CloudHelper:
    """Cloud helper used by tests.

    Prefer Minium wx.cloud.callFunction; when IDE base library blocks it,
    fall back to `tcb fn invoke` against the deployed SCF.
    """

    SERVICE_BY_GAME = {
        "drinkParty": "drinkRoomService",
        "undercover": "undercoverRoomService",
        "drawGuess": "drawRoomService",
        "songGuess": "musicRoomService",
        "werewolf": "werewolfService",
        "truthDareRoom": "roomService",
        "headband": "headbandRoomService",
        "mysteryReason": "mysteryReasonRoomService",
        "dontdoitParty": "dontdoitRoomService",
    }

    def __init__(self, testcase, config):
        self.testcase = testcase
        self.app = testcase.app
        self.config = config
        self.env_id = config.get("cloud_env_id")
        self.settings = config.get("test_settings", {})
        self.enabled = bool(self.settings.get("use_cloud_test_hooks", False))
        self.project_path = Path(
            config.get("project_path") or PROJECT_ROOT
        ).resolve()

    def log(self, message):
        print(f"[CloudHelper] {message}")

    def _call_via_minium(self, name, data):
        payload = {"name": name, "data": data or {}}
        if self.env_id:
            payload["config"] = {"env": self.env_id}
        last_error = None
        for api in ("call_wx_method", "callWxMethod"):
            fn = getattr(self.app, api, None)
            if callable(fn):
                try:
                    return fn("cloud.callFunction", payload)
                except Exception as exc:
                    last_error = exc
        raise RuntimeError(
            "Minium cannot call wx.cloud.callFunction: " + str(last_error)
        )

    def _parse_tcb_invoke_json(self, stdout):
        text = (stdout or "").strip()
        start = text.find("{")
        if start > 0:
            text = text[start:]
        try:
            outer = json.loads(text)
        except json.JSONDecodeError:
            return {}
        data = outer.get("data") if isinstance(outer, dict) else outer
        if not isinstance(data, dict):
            return {}
        ret = data.get("RetMsg") or data.get("retMsg")
        if isinstance(ret, str) and ret.strip():
            try:
                return json.loads(ret)
            except json.JSONDecodeError:
                return {"raw": ret}
        return data

    def _call_via_tcb(self, name, data, timeout=90):
        params = json.dumps(data or {}, ensure_ascii=False)
        env = os.environ.copy()
        env["NPM_CONFIG_REGISTRY"] = env.get(
            "NPM_CONFIG_REGISTRY", "https://registry.npmjs.org"
        )
        cmd = [
            "npx",
            "-p",
            "@cloudbase/cli@3.4.0",
            "tcb",
            "fn",
            "invoke",
            name,
            "--params",
            params,
            "--json",
        ]
        self.log(f"tcb invoke {name}: {params}")
        proc = subprocess.run(
            cmd,
            cwd=str(self.project_path),
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"tcb fn invoke failed ({proc.returncode}): {proc.stderr or proc.stdout}"
            )
        return self._parse_tcb_invoke_json(proc.stdout)

    def call_function(self, name, data, timeout=90):
        self.log(f"callFunction {name}: {json.dumps(data or {}, ensure_ascii=False)}")
        try:
            return self._call_via_minium(name, data)
        except RuntimeError as exc:
            self.log(f"minium cloud fallback → tcb: {exc}")
            return self._call_via_tcb(name, data, timeout=timeout)

    def service_for(self, game_key):
        return self.SERVICE_BY_GAME[game_key]

    def _parse_cf_result(self, raw):
        if raw is None:
            return {}
        if isinstance(raw, dict):
            if raw.get("roomId") or raw.get("roomCode") or raw.get("id"):
                return raw
            if raw.get("errMsg") and not raw.get("result"):
                return raw
            if "result" in raw:
                return self._parse_cf_result(raw["result"])
            data = raw.get("data") if isinstance(raw.get("data"), dict) else None
            if data:
                ret = data.get("RetMsg") or data.get("retMsg")
                if isinstance(ret, str) and ret.strip():
                    try:
                        parsed = json.loads(ret)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        return {"raw": ret}
        return raw if isinstance(raw, dict) else {}

    def fetch_view(self, game_key, room_id):
        service = self.service_for(game_key)
        return self._parse_cf_result(
            self.call_function(
                service,
                {"action": "getView", "roomId": room_id, "_test": True},
            )
        )

    def count_players_in_view(self, view):
        if not isinstance(view, dict):
            return 0
        if isinstance(view.get("view"), dict):
            inner = view["view"]
            pc = inner.get("playerCount")
            if pc is not None:
                return int(pc)
            view = inner
        pc = view.get("playerCount")
        if pc is not None:
            return int(pc)
        for key in ("players", "memberList", "publicPlayers"):
            arr = view.get(key)
            if isinstance(arr, list):
                return len(arr)
        pub = view.get("pub")
        if isinstance(pub, dict):
            for key in ("members", "players", "memberList"):
                arr = pub.get(key)
                if isinstance(arr, list):
                    return len(arr)
        return 0

    def push_view_to_page(self, page_obj, game_key, room_id):
        if not self.enabled or not room_id:
            return {}
        view = self.fetch_view(game_key, room_id)
        if not view or view.get("errMsg"):
            return view
        snap = view.get("view") if isinstance(view.get("view"), dict) else view
        try:
            if game_key in ("drawGuess", "headband", "werewolf"):
                page_obj.try_call_page_method("applyTestSyncSnapshot", snap)
        except Exception as exc:
            self.log(f"push_view_to_page({game_key}) skipped: {exc}")
        page_obj.sleep(1.2)
        return view

    def sync_truth_dare_page(self, page_obj, room_code):
        if not self.enabled or not room_code:
            return {}
        data = self._parse_cf_result(
            self.call_function(
                self.service_for("truthDareRoom"),
                {"action": "syncState", "roomCode": room_code, "_test": True},
            )
        )
        if data.get("room") or data.get("td"):
            page_obj.try_call_page_method(
                "applyTestRoomSync",
                {
                    "room": data.get("room"),
                    "myOpenId": data.get("myOpenId") or "",
                    "td": data.get("td"),
                },
            )
        page_obj.sleep(1.2)
        return data

    def create_room(self, game_key, difficulty="新手", nickname="Minium组长"):
        service = self.service_for(game_key)
        raw = self.call_function(
            service,
            {
                "action": "create",
                "difficulty": difficulty,
                "nickName": nickname,
                "avatar": "",
                "_test": True,
            },
        )
        return self._parse_cf_result(raw)

    def seed_players(
        self, game_key, room_id=None, room_code=None, count=2, start_index=1
    ):
        if not self.enabled:
            self.log(f"skip seed_players({game_key}, count={count}); use_cloud_test_hooks=false")
            return {"skipped": True}
        service = self.service_for(game_key)
        base = int(start_index)
        players = [
            {
                "openId": f"minium_test_{game_key}_{base + i}",
                "nickName": f"{self.settings.get('virtual_player_prefix', 'Minium玩家')}{base + i}",
                "avatarUrl": "",
                "profileReady": True,
            }
            for i in range(count)
        ]
        raw = self.call_function(
            service,
            {
                "action": "__testSeedPlayers",
                "roomId": room_id,
                "roomCode": room_code,
                "players": players,
                "_test": True,
            },
        )
        return self._parse_cf_result(raw)

    def advance(self, game_key, room_id=None, room_code=None, phase=None, extra=None):
        if not self.enabled:
            self.log(f"skip advance({game_key}, phase={phase}); use_cloud_test_hooks=false")
            return {"skipped": True}
        service = self.service_for(game_key)
        data = {
            "action": "__testAdvanceRound",
            "roomId": room_id,
            "roomCode": room_code,
            "phase": phase,
            "_test": True,
        }
        if extra:
            data.update(extra)
        return self._parse_cf_result(self.call_function(service, data))

    def start_game(self, game_key, room_id, difficulty="新手"):
        """mysteryReason 专用 __testStartGame。"""
        service = self.service_for(game_key)
        return self._parse_cf_result(
            self.call_function(
                service,
                {
                    "action": "__testStartGame",
                    "roomId": room_id,
                    "difficulty": difficulty,
                    "_test": True,
                },
            )
        )

    def start_game_cloud(self, game_key, room_id=None, room_code=None):
        """各玩法云端开局（Minium 无 wx.cloud 时走 tcb invoke）。"""
        service = self.service_for(game_key)
        if game_key == "werewolf":
            action = "start"
        elif game_key == "truthDareRoom":
            action = "tdStart"
        elif game_key == "drinkParty":
            action = "startRound"
        else:
            action = "startGame"
        data = {"action": action, "_test": True}
        if game_key == "truthDareRoom":
            data["roomCode"] = room_code
        else:
            data["roomId"] = room_id
        return self._parse_cf_result(self.call_function(service, data))

    def start_blocked_cloud(self, game_key, room_id=None, room_code=None):
        """人数不足时云端开局应失败，返回 errMsg 视为已拦截。"""
        if not room_id and game_key != "truthDareRoom":
            return False
        if game_key == "truthDareRoom" and not room_code:
            return False
        try:
            res = self.start_game_cloud(
                game_key, room_id=room_id, room_code=room_code
            )
        except Exception as exc:
            return True
        if res.get("ok") is True and not res.get("errMsg"):
            return False
        err = str(res.get("errMsg") or res.get("error") or res.get("raw") or "")
        if err:
            return True
        text = json.dumps(res, ensure_ascii=False)
        return "至少" in text or "不足" in text or "仅" in text

    def sync_snapshot(self, game_key, room_id):
        service = self.service_for(game_key)
        return self._parse_cf_result(
            self.call_function(
                service,
                {"action": "__testSyncSnapshot", "roomId": room_id, "_test": True},
            )
        )

    def mark_all_ready(self, game_key, room_id=None, room_code=None):
        if not self.enabled:
            self.log(f"skip mark_all_ready({game_key}); use_cloud_test_hooks=false")
            return {"skipped": True}
        service = self.service_for(game_key)
        return self._parse_cf_result(
            self.call_function(
                service,
                {
                    "action": "__testMarkAllReady",
                    "roomId": room_id,
                    "roomCode": room_code,
                    "_test": True,
                },
            )
        )

    def assert_cloud_available(self, game_key):
        service = self.service_for(game_key)
        try:
            return self._parse_cf_result(
                self.call_function(service, {"action": "ping", "_test": True})
            )
        except Exception as exc:
            self.log(f"cloud availability check failed for {service}: {exc}")
            return {"ok": False, "error": str(exc)}

    def wait_for_cloud_settle(self, seconds=1):
        time.sleep(seconds)

    def _mystery(self, game_key, payload):
        service = self.service_for(game_key)
        data = dict(payload or {})
        data.setdefault("_test", True)
        return self._parse_cf_result(self.call_function(service, data))

    def force_set_phase(self, room_id, phase, game_key="mysteryReason"):
        return self.advance(game_key, room_id=room_id, phase=phase)

    def force_next_phase(self, room_id, game_key="mysteryReason"):
        return self.advance(game_key, room_id=room_id)

    def submit_vote(self, room_id, target_id, game_key="mysteryReason"):
        return self._mystery(
            game_key,
            {
                "action": "submitVote",
                "roomId": room_id,
                "targetId": target_id,
            },
        )

    def unlock_review(self, room_id, verify=True, game_key="mysteryReason"):
        return self._mystery(
            game_key,
            {
                "action": "unlockReview",
                "roomId": room_id,
                "shareVerify": bool(verify),
            },
        )

    def restart_game(self, room_id, game_key="mysteryReason"):
        return self._mystery(
            game_key, {"action": "restartGame", "roomId": room_id}
        )

    def trigger_evidence(self, room_id, round_num, game_key="mysteryReason"):
        return self._mystery(
            game_key,
            {
                "action": "refreshEvidence",
                "roomId": room_id,
                "round": int(round_num),
            },
        )

    def trigger_all_evidence(self, room_id, game_key="mysteryReason"):
        snap = self.sync_snapshot(game_key, room_id)
        phase = (snap.get("state") or {}).get("phase")
        if phase != "get_evidence":
            self.force_set_phase(room_id, "get_evidence", game_key=game_key)
        return self.advance(game_key, room_id=room_id, phase="analyze_clue")

    def batch_vote_tie(self, room_id, game_key="mysteryReason"):
        return self._mystery(
            game_key,
            {"action": "__testBatchVoteTie", "roomId": room_id},
        )

    def get_my_script(self, room_id, open_id=None, game_key="mysteryReason"):
        if open_id:
            return self._mystery(
                game_key,
                {
                    "action": "__testGetMyScript",
                    "roomId": room_id,
                    "_testOpenId": open_id,
                },
            )
        return self._mystery(
            game_key,
            {"action": "getMyScript", "roomId": room_id},
        )

    def advance_to_ai_review(self, room_id, game_key="mysteryReason"):
        """测试环境直接推进到 AI 复盘（写入 reviewContent）。"""
        return self.advance(game_key, room_id=room_id, phase="ai_review")

    def kick_extra_players(self, room_id, target_count, game_key="mysteryReason"):
        return self._mystery(
            game_key,
            {
                "action": "__testKickExtraPlayers",
                "roomId": room_id,
                "targetCount": int(target_count),
            },
        )
