from urllib.parse import quote

from base.base_page import BasePage


class IndexPage(BasePage):
    path = "/pages/index/index"

    SCREEN_BY_GAME = {
        "drinkParty": ("趣味抽签", "drinkParty"),
        "undercover": ("谁是卧底", "undercover"),
        "drawGuess": ("你画我猜", "drawGuess"),
        "songGuess": ("猜歌", "songGuess"),
        "werewolf": ("身份推理", "werewolf"),
        "headband": ("贴头猜词", "headband"),
    }

    def open(self):
        return self.navigate(self.path)

    def goto_setup(self, game_key):
        title, screen = self.SCREEN_BY_GAME[game_key]
        url = f"/pages/setup/setup?title={quote(title)}&screen={quote(screen)}"
        return self.navigate(url)

    def join_by_code(self, code):
        self.open()
        self.tap_any_text(["输入口令", "加入互动组", "加入"], selector="button", timeout=5)
        self.log(f"Native editable modal should receive room code manually if Minium cannot type: {code}")
        return self
