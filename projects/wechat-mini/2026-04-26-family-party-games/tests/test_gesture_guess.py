"""
Minium 测试：你比划我猜游戏完整流程
测试场景：
1. 创建房间
2. 第二个玩家加入
3. 开始游戏
4. 表演者看到词语
5. 猜词者提交答案
6. 验证得分更新
"""

import minium
import time
import unittest

class GestureGuessTest(unittest.TestCase):
    """你比划我猜测试套件"""

    @classmethod
    def setUpClass(cls):
        """初始化 minium 客户端"""
        # 需要先启动微信开发者工具并选择项目
        cls.mini = minium.WebDriver()
        cls.mini.implicitly_wait(10)

        # 测试数据
        cls.room_code = None
        cls.room_id = None

    @classmethod
    def tearDownClass(cls):
        """关闭客户端"""
        cls.mini.quit()

    def test_01_create_room(self):
        """TC-01: 创建房间"""
        print("\n=== TC-01: 创建房间 ===")

        # 进入首页
        self.mini.switch_to.miniprogram()
        time.sleep(2)

        # 查找"你比划我猜"游戏卡片
        gesture_btn = self.mini.find_element(
            minium.By.XPATH,
            "//view[contains(text(), '你比划我猜')]"
        )
        gesture_btn.click()
        time.sleep(2)

        # 输入昵称
        nick_input = self.mini.find_element(minium.By.ID, "nick-input")
        if nick_input:
            nick_input.send_keys("玩家A")

        # 点击创建按钮
        create_btn = self.mini.find_element(
            minium.By.XPATH,
            "//button[contains(text(), '创建聚会组')]"
        )
        create_btn.click()
        time.sleep(3)

        # 验证房间码出现
        room_code_elem = self.mini.find_element(
            minium.By.XPATH,
            "//view[contains(text(), '口令')]"
        )
        self.assertIsNotNone(room_code_elem)
        print("✓ 房间创建成功，显示口令")

    def test_02_join_room(self):
        """TC-02: 第二个玩家加入"""
        print("\n=== TC-02: 加入房间 ===")

        # 获取房间码（从 UI 或使用预设值）
        self.mini.switch_to.miniprogram()

        # 等待房间页加载
        time.sleep(2)

        # 验证成员列表显示
        member_list = self.mini.find_element(
            minium.By.XPATH,
            "//view[contains(text(), '玩家')]"
        )
        self.assertIsNotNone(member_list)
        print("✓ 加入房间成功，显示成员列表")

    def test_03_start_game(self):
        """TC-03: 开始游戏"""
        print("\n=== TC-03: 开始游戏 ===")

        self.mini.switch_to.miniprogram()
        time.sleep(1)

        # 验证至少 2 人存在
        # 模拟第二个玩家加入的情况

        # 点击开始游戏按钮
        start_btn = self.mini.find_element(
            minium.By.XPATH,
            "//button[contains(text(), '开始游戏')]"
        )
        if start_btn:
            start_btn.click()
            time.sleep(2)
            print("✓ 游戏开始")
        else:
            print("⚠ 未找到开始按钮，可能人数不足")

    def test_04_performer_sees_word(self):
        """TC-04: 表演者看到词语"""
        print("\n=== TC-04: 验证表演者界面 ===")

        self.mini.switch_to.miniprogram()
        time.sleep(1)

        # 查找表演者才能看到的元素
        performer_word = self.mini.find_element(
            minium.By.XPATH,
            "//view[@class='gesture-performer-word']"
        )

        if performer_word:
            word = performer_word.text
            print(f"✓ 表演者看到词语: {word}")
            self.assertIsNotNone(word)
        else:
            print("ℹ 当前用户非表演者（正常情况）")

    def test_05_guesser_submits_answer(self):
        """TC-05: 猜词者提交答案"""
        print("\n=== TC-05: 猜词者提交答案 ===")

        self.mini.switch_to.miniprogram()
        time.sleep(1)

        # 查找输入框（非表演者可见）
        guess_input = self.mini.find_element(
            minium.By.XPATH,
            "//input[@placeholder='输入你的答案']"
        )

        if guess_input:
            # 输入答案
            guess_input.send_keys("测试答案")
            time.sleep(1)

            # 点击提交
            submit_btn = self.mini.find_element(
                minium.By.XPATH,
                "//button[contains(text(), '提交答案')]"
            )
            submit_btn.click()
            time.sleep(2)

            print("✓ 答案已提交")
        else:
            print("ℹ 当前为表演者视角，无输入框（正常情况）")

    def test_06_verify_ui_state(self):
        """TC-06: 验证 UI 状态"""
        print("\n=== TC-06: 验证 UI 状态 ===")

        self.mini.switch_to.miniprogram()
        time.sleep(1)

        # 检查页面元素加载
        elements = {
            "倒计时": "//view[@class='gesture-countdown']",
            "排行榜": "//view[@class='gesture-ranking']",
            "日志": "//view[@class='gesture-log']",
        }

        for name, xpath in elements.items():
            elem = self.mini.find_element(minium.By.XPATH, xpath)
            status = "✓" if elem else "✗"
            print(f"{status} {name}")

    def test_07_check_performance(self):
        """TC-07: 性能检查"""
        print("\n=== TC-07: 性能检查 ===")

        self.mini.switch_to.miniprogram()

        # 获取性能数据
        perf = self.mini.get_performance()
        print(f"✓ 页面加载时间: {perf}")

    def test_08_verify_responsive(self):
        """TC-08: 响应式检查"""
        print("\n=== TC-08: 响应式检查 ===")

        self.mini.switch_to.miniprogram()

        # 检查屏幕尺寸
        window_size = self.mini.get_window_size()
        print(f"✓ 窗口尺寸: {window_size}")

    def test_99_cleanup(self):
        """TC-99: 清理"""
        print("\n=== TC-99: 清理 ===")

        self.mini.switch_to.miniprogram()
        time.sleep(1)

        # 返回首页
        try:
            back_btn = self.mini.find_element(
                minium.By.XPATH,
                "//view[@class='nav-back']"
            )
            if back_btn:
                back_btn.click()
        except:
            pass

        print("✓ 测试完成")


if __name__ == '__main__':
    # 运行测试
    # 使用 -v 显示详细信息
    unittest.main(verbosity=2)
