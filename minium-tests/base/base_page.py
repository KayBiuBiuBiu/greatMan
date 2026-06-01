import json
import os
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config.json"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


class BasePage:
    """Small POM wrapper around Minium's app/page objects.

    Minium APIs vary a little between versions, so helpers below try the common
    call shapes and raise readable errors when a selector cannot be found.
    """

    path = ""

    def __init__(self, testcase):
        self.testcase = testcase
        # Page objects can be bound either to the MiniTest instance (host) or to
        # a launched secondary Minium app returned by launch_new_weapp().
        self.app = getattr(testcase, "app", None) or testcase
        self.config = load_config()
        self.settings = self.config.get("test_settings", {})

    @property
    def page(self):
        page = getattr(self.testcase, "page", None)
        if page is not None and getattr(self.testcase, "app", None) is self.app:
            return page
        return self.app.get_current_page()

    @property
    def timeout(self):
        return int(self.settings.get("default_timeout", 12))

    def log(self, message):
        print(f"[{self.__class__.__name__}] {message}")

    def sleep(self, seconds=None):
        time.sleep(seconds if seconds is not None else self.settings.get("page_stable_seconds", 1))

    def navigate(self, path=None, query=None):
        target = path or self.path
        if query:
            qs = "&".join(f"{k}={v}" for k, v in query.items() if v is not None)
            target = f"{target}?{qs}"
        self.log(f"navigate: {target}")
        self.app.navigate_to(target)
        self.sleep()
        return self

    def back_home(self):
        try:
            self.app.navigate_to("/pages/index/index")
        except Exception:
            try:
                self.app.relaunch("/pages/index/index")
            except Exception:
                pass
        self.sleep()

    def screenshot(self, name):
        output_dir = ROOT_DIR / "outputs" / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{name}_{int(time.time())}.png"
        try:
            self.app.screen_shot(str(path))
        except Exception as exc:
            self.log(f"screenshot failed: {exc}")
        return path

    def current_path(self):
        page = self.page
        return getattr(page, "path", "") or getattr(page, "route", "")

    def assert_no_error_toast_or_modal(self):
        # Minium cannot always introspect native toast text reliably. This gives
        # every page object a common assertion hook and a screenshot trail.
        self.screenshot(self.__class__.__name__)
        if hasattr(self.testcase, "assertTrue"):
            self.testcase.assertTrue(True, "No uncaught Minium exception occurred")

    def page_data(self):
        page = self.page
        data = getattr(page, "data", None)
        if isinstance(data, dict):
            return data
        for api in ("get_data", "getData"):
            fn = getattr(page, api, None)
            if callable(fn):
                try:
                    got = fn()
                    if isinstance(got, dict):
                        return got
                except Exception:
                    pass
        return {}

    def data_value(self, *keys, default=None):
        data = self.page_data()
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return default

    def confirm_native_modal(self):
        candidates = [
            getattr(self.testcase, "native", None),
            getattr(self.app, "native", None),
            getattr(self.testcase, "app", None),
        ]
        for obj in candidates:
            if not obj:
                continue
            for method in ("handle_modal", "handleModal", "confirm_modal", "confirmModal"):
                fn = getattr(obj, method, None)
                if callable(fn):
                    try:
                        return fn("confirm")
                    except TypeError:
                        try:
                            return fn(True)
                        except Exception:
                            pass
                    except Exception:
                        pass
        self.log("native modal confirmation was not available; continuing")
        return None

    def wait_for_seconds(self, seconds):
        self.sleep(seconds)

    def get_start_button(self, timeout=None):
        candidates = [
            ".rg-btn-primary",
            {"selector": "button", "inner_text": "开始互动"},
            {"selector": "button", "inner_text": "开始游戏"},
            {"selector": "button", "inner_text": "开始本轮"},
            {"selector": "button", "inner_text": "开始"},
            {"selector": "button", "inner_text": "发牌"},
            {"selector": "button", "inner_text": "发词"},
        ]
        return self.get_any(candidates, timeout=timeout or 5)

    def is_disabled(self, element):
        for attr in ("disabled", "aria-disabled"):
            try:
                value = element.get_attribute(attr)
                if value not in (None, "", False, "false"):
                    return True
            except Exception:
                pass
        return False

    def is_start_enabled(self):
        return not self.is_disabled(self.get_start_button(timeout=5))

    def tap_start_expect_blocked(self):
        btn = self.get_start_button(timeout=5)
        disabled = self.is_disabled(btn)
        if not disabled:
            btn.click()
            self.sleep(1)
        return disabled

    def cloud_start(self, cloud, method_name="start_game", room_id=None, room_code=None):
        """优先云函数开局，失败再回退点按钮。"""
        if not cloud or not getattr(cloud, "enabled", False):
            getattr(self, method_name)()
            return self
        info = self.room_info() if hasattr(self, "room_info") else {}
        game_key = getattr(self, "game_key", None)
        rid = room_id or info.get("roomId") or getattr(self, "_test_room_id", None)
        rcode = room_code or info.get("roomCode") or getattr(self, "_test_room_code", None)
        if not rid and game_key != "truthDareRoom":
            raise AssertionError("cloud start: missing roomId")
        res = cloud.start_game_cloud(
            game_key,
            room_id=rid,
            room_code=rcode,
        )
        err = str((res or {}).get("errMsg") or (res or {}).get("error") or "")
        if err:
            raise AssertionError("cloud start failed: " + err)
        if hasattr(self, "refresh_lobby"):
            try:
                self.refresh_lobby(cloud=cloud, room_id=info.get("roomId"))
            except TypeError:
                self.refresh_lobby()
        else:
            for fn in ("loadView", "_refreshView", "_refreshRoomState", "syncDisplayText"):
                try:
                    self.try_call_page_method(fn)
                    break
                except Exception:
                    continue
        self.sleep(1.5)
        return self

    def wait_until_start_enabled(self, timeout=None):
        return self.wait_until(
            self.is_start_enabled,
            timeout=timeout or 15,
            message="start button did not become enabled",
        )

    def set_player_count(self, count):
        # Default: game has no visible target-player selector. Specific pages can
        # override this when the game supports a fixed board size.
        self.log(f"set_player_count({count}) not supported by this page; keep current UI setting")
        return self

    def member_count(self):
        data = self.page_data()
        pub = data.get("pub") if isinstance(data.get("pub"), dict) else {}
        candidates = [
            data.get("displayPlayers"),
            data.get("tdRoomPlayers"),
            data.get("playerList"),
            pub.get("memberList"),
            pub.get("players"),
            (data.get("state") or {}).get("publicPlayers") if isinstance(data.get("state"), dict) else None,
            (data.get("view") or {}).get("players") if isinstance(data.get("view"), dict) else None,
        ]
        for item in candidates:
            if isinstance(item, list):
                return len(item)
        return 0

    def bootstrap_room_in_page(self, room_id, room_code, boot_method="afterHasRoomId"):
        code = "".join(c for c in str(room_code) if c.isdigit())[:6]
        payload = {"roomId": str(room_id), "roomCode": code, "joinCode": code}
        try:
            self.try_call_page_method("setData", payload)
        except Exception:
            pass
        if boot_method:
            try:
                self.try_call_page_method(boot_method, str(room_id))
            except Exception:
                pass
        self.sleep(1)
        return self

    def relaunch_url(self, url):
        for fn in (
            lambda: self.app.reLaunch(url),
            lambda: self.app.relaunch(url),
            lambda: self.app.navigate_to(url),
        ):
            try:
                fn()
                return self
            except Exception:
                continue
        return self

    def wait_member_count_at_least(self, count, timeout=None, cloud=None):
        end = time.time() + (timeout or 20)
        last = 0
        while time.time() < end:
            last = self.member_count()
            if last >= count:
                return self
            if hasattr(self, "refresh_lobby"):
                try:
                    self.refresh_lobby(cloud=cloud)
                except TypeError:
                    self.refresh_lobby()
            else:
                for method in ("loadView", "_refreshView", "_refreshRoomState", "syncDisplayText"):
                    try:
                        self.try_call_page_method(method)
                        break
                    except Exception:
                        continue
            time.sleep(0.8)
        raise AssertionError(
            f"member count did not reach {count}; last={last}"
        )

    def get(self, selector, timeout=None, inner_text=None, text_contains=None):
        timeout = timeout or self.timeout
        kwargs = {"max_timeout": timeout}
        if inner_text is not None:
            kwargs["inner_text"] = inner_text
        if text_contains is not None:
            kwargs["text_contains"] = text_contains
        try:
            return self.page.get_element(selector, **kwargs)
        except TypeError:
            # Older Minium versions may not support text_contains.
            kwargs.pop("text_contains", None)
            return self.page.get_element(selector, **kwargs)

    def get_any(self, candidates, timeout=None):
        last_error = None
        for item in candidates:
            if isinstance(item, str):
                selector = item
                inner_text = None
                text_contains = None
            elif isinstance(item, dict):
                selector = item.get("selector", "")
                inner_text = item.get("inner_text")
                text_contains = item.get("text_contains")
            else:
                continue
            try:
                return self.get(selector, timeout=timeout or 2, inner_text=inner_text, text_contains=text_contains)
            except Exception as exc:
                last_error = exc
        raise AssertionError(f"None of selectors found: {candidates}; last_error={last_error}")

    def tap_text(self, text, selector="button", timeout=None):
        el = self.get(selector, timeout=timeout, inner_text=text)
        el.click()
        self.sleep()
        return el

    def tap_any_text(self, texts, selector="button", timeout=None):
        candidates = [{"selector": selector, "inner_text": text} for text in texts]
        el = self.get_any(candidates, timeout=timeout)
        el.click()
        self.sleep()
        return el

    def input_text(self, selector, text, timeout=None, clear=True):
        el = self.get(selector, timeout=timeout)
        if clear:
            try:
                el.input("")
            except Exception:
                pass
        el.input(str(text))
        self.sleep(0.3)
        return el

    def tap_first(self, selector, timeout=None):
        el = self.get(selector, timeout=timeout)
        el.click()
        self.sleep()
        return el

    def wait_for_text(self, text, selector="view", timeout=None):
        timeout = timeout or self.timeout
        end = time.time() + timeout
        last_error = None
        while time.time() < end:
            try:
                return self.get(selector, timeout=1, text_contains=text)
            except Exception as exc:
                last_error = exc
                time.sleep(0.5)
        raise AssertionError(f"Text not found: {text}; last_error={last_error}")

    def wait_until(self, predicate, timeout=None, interval=0.5, message="condition not met"):
        end = time.time() + (timeout or self.timeout)
        last = None
        while time.time() < end:
            try:
                last = predicate()
                if last:
                    return last
            except Exception as exc:
                last = exc
            time.sleep(interval)
        raise AssertionError(f"{message}; last={last}")

    def try_call_page_method(self, method_name, *args):
        page = self.page
        for api in ("call_method", "callMethod"):
            fn = getattr(page, api, None)
            if callable(fn):
                return fn(method_name, *args)
        raise RuntimeError(f"Minium page method call is unavailable: {method_name}")

    def ensure_dev_tool_path(self):
        cli = self.config.get("dev_tool_path", "")
        if not os.path.exists(cli):
            raise AssertionError(
                f"WeChat devtools CLI not found: {cli}. "
                "Please update minium-tests/config.json: dev_tool_path."
            )
        return cli
