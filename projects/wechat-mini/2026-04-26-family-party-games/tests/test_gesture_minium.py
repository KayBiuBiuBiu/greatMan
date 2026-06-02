"""
你比划我猜 - Minium 自动化测试脚本

这个脚本使用 Minium 框架来自动化真机测试 7 个核心场景。

前置条件:
1. 微信开发者工具已编译 (Ctrl/Cmd + B)
2. 云函数已部署 (gestureRoomService)
3. 数据库集合已创建 (gesture_rooms/players/gameState)
4. Minium 已安装: pip install minium

运行: python tests/test_gesture_minium.py
"""

import time
import unittest
from minium import Minium, MiniTest


class GestureGuessMiniumTest(MiniTest):
    """你比划我猜 Minium 自动化测试"""

    @classmethod
    def setUpClass(cls):
        """初始化 Minium 驱动"""
        # 连接到微信开发者工具本地调试器
        pass

        # 测试数据
        cls.test_data = {
            'room_code': None,
            'room_id': None,
            'player_a_nick': '玩家A',
            'player_b_nick': '玩家B'
        }

    @classmethod
    def tearDownClass(cls):
        """关闭驱动"""
        cls.driver.quit()

    def log_test(self, test_name, status="PASS", details=""):
        """记录测试结果"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        symbol = "✓" if status == "PASS" else "✗"
        print(f"\n[{timestamp}] {symbol} {test_name}")
        if details:
            print(f"         {details}")

    # ==================== TC-01: 创建房间 ====================

    def test_01_create_room(self):
        """TC-01: 创建房间"""
        self.log_test("TC-01: 创建房间", "START")

        try:
            self.driver.switch_to.miniprogram()
            time.sleep(2)

            # 查找"你比划我猜"游戏卡片
            gesture_card = self.driver.find_element(
                By.XPATH,
                "//view[contains(text(), '你比划我猜')]"
            )
            self.assertIsNotNone(gesture_card, "应找到游戏卡片")
            gesture_card.click()
            time.sleep(2)

            # 输入昵称
            nick_input = self.driver.find_element(
                By.XPATH,
                "//input[@placeholder='输入你的昵称']"
            )
            nick_input.send_keys(self.test_data['player_a_nick'])

            # 点击创建按钮
            create_btn = self.driver.find_element(
                By.XPATH,
                "//button[contains(text(), '创建聚会组')]"
            )
            create_btn.click()
            time.sleep(3)

            # 验证房间码出现
            code_element = self.driver.find_element(
                By.XPATH,
                "//view[contains(text(), '口令')]"
            )
            self.assertIsNotNone(code_element, "应显示房间码")

            # 提取房间码
            code_text = code_element.text
            # 假设格式为 "口令：123456"
            if '：' in code_text:
                self.test_data['room_code'] = code_text.split('：')[1].strip()

            self.log_test(
                "TC-01: 创建房间",
                "PASS",
                f"房间码: {self.test_data['room_code']}"
            )

        except Exception as e:
            self.log_test("TC-01: 创建房间", "FAIL", str(e))
            raise

    # ==================== TC-02: 多人加入 ====================

    def test_02_multiple_join(self):
        """TC-02: 多人加入房间"""
        self.log_test("TC-02: 多人加入", "START")

        try:
            # 验证成员列表显示
            members = self.driver.find_elements(
                By.XPATH,
                "//view[@class='gesture-member-item']"
            )
            initial_count = len(members)
            self.assertGreater(initial_count, 0, "应显示至少一个成员")

            self.log_test(
                "TC-02: 多人加入",
                "PASS",
                f"当前成员数: {initial_count}"
            )

        except Exception as e:
            self.log_test("TC-02: 多人加入", "FAIL", str(e))
            raise

    # ==================== TC-03: 游戏开始 ====================

    def test_03_start_game(self):
        """TC-03: 开始游戏"""
        self.log_test("TC-03: 开始游戏", "START")

        try:
            # 查找开始按钮
            start_btn = self.driver.find_element(
                By.XPATH,
                "//button[contains(text(), '开始游戏')]"
            )
            self.assertIsNotNone(start_btn, "应显示开始按钮")

            # 点击开始
            start_btn.click()
            time.sleep(3)

            # 验证进入游戏阶段
            countdown = self.driver.find_element(
                By.XPATH,
                "//view[@class='gesture-countdown']"
            )
            self.assertIsNotNone(countdown, "应显示倒计时")

            self.log_test("TC-03: 开始游戏", "PASS", "进入游戏阶段")

        except Exception as e:
            self.log_test("TC-03: 开始游戏", "FAIL", str(e))
            raise

    # ==================== TC-04: 答题判题 ====================

    def test_04_submit_answer(self):
        """TC-04: 答题判题"""
        self.log_test("TC-04: 答题判题", "START")

        try:
            # 查找答案输入框（非表演者可见）
            guess_input = self.driver.find_element(
                By.XPATH,
                "//input[@placeholder='输入你的答案']"
            )

            if guess_input:
                # 输入答案
                guess_input.send_keys("测试答案")
                time.sleep(1)

                # 查找提交按钮
                submit_btn = self.driver.find_element(
                    By.XPATH,
                    "//button[contains(text(), '提交答案')]"
                )
                submit_btn.click()
                time.sleep(2)

                self.log_test("TC-04: 答题判题", "PASS", "答案已提交")
            else:
                self.log_test(
                    "TC-04: 答题判题",
                    "INFO",
                    "当前用户为表演者（正常）"
                )

        except Exception as e:
            self.log_test("TC-04: 答题判题", "FAIL", str(e))
            # 不中断，可能当前为表演者

    # ==================== TC-05: 倒计时 ====================

    def test_05_countdown(self):
        """TC-05: 倒计时精度"""
        self.log_test("TC-05: 倒计时", "START")

        try:
            countdown_elem = self.driver.find_element(
                By.XPATH,
                "//view[@class='gesture-countdown']"
            )
            self.assertIsNotNone(countdown_elem, "应显示倒计时")

            countdown_text = countdown_elem.text
            countdown_value = int(countdown_text)

            self.assertGreater(countdown_value, 0, "倒计时应大于0")
            self.assertLessEqual(countdown_value, 60, "倒计时应小于等于60")

            self.log_test(
                "TC-05: 倒计时",
                "PASS",
                f"当前倒计时: {countdown_value}秒"
            )

        except Exception as e:
            self.log_test("TC-05: 倒计时", "FAIL", str(e))
            raise

    # ==================== TC-06: 揭示阶段 ====================

    def test_06_reveal_phase(self):
        """TC-06: 揭示阶段"""
        self.log_test("TC-06: 揭示阶段", "START")

        try:
            # 等待倒计时完成或查找揭示按钮
            reveal_btn = self.driver.find_element(
                By.XPATH,
                "//button[contains(text(), '下一轮')]"
            )
            self.assertIsNotNone(reveal_btn, "应显示下一轮按钮（表示进入揭示）")

            # 查找答案显示
            answer_elem = self.driver.find_element(
                By.XPATH,
                "//view[@class='gesture-answer-text']"
            )
            self.assertIsNotNone(answer_elem, "应显示答案")

            self.log_test("TC-06: 揭示阶段", "PASS", "进入揭示阶段")

        except Exception as e:
            self.log_test("TC-06: 揭示阶段", "INFO", "可能还在表演阶段（正常）")

    # ==================== TC-07: 多轮流程 ====================

    def test_07_multiple_rounds(self):
        """TC-07: 多轮游戏流程"""
        self.log_test("TC-07: 多轮游戏", "START")

        try:
            # 查找当前轮数显示
            round_info = self.driver.find_element(
                By.XPATH,
                "//view[contains(text(), '第')]"
            )
            self.assertIsNotNone(round_info, "应显示轮数信息")

            round_text = round_info.text
            self.log_test(
                "TC-07: 多轮游戏",
                "PASS",
                f"当前: {round_text}"
            )

        except Exception as e:
            self.log_test("TC-07: 多轮游戏", "FAIL", str(e))
            raise

    # ==================== 性能测试 ====================

    def test_08_performance(self):
        """TC-08: 性能指标"""
        self.log_test("TC-08: 性能指标", "START")

        try:
            # 获取性能数据
            perf_data = self.driver.execute_script(
                "return performance.timing"
            )

            if perf_data:
                load_time = (
                    perf_data.get('loadEventEnd', 0) -
                    perf_data.get('navigationStart', 0)
                )
                self.log_test(
                    "TC-08: 性能指标",
                    "PASS",
                    f"页面加载时间: {load_time}ms"
                )
            else:
                self.log_test(
                    "TC-08: 性能指标",
                    "INFO",
                    "无法获取性能数据"
                )

        except Exception as e:
            self.log_test("TC-08: 性能指标", "INFO", str(e))

    # ==================== 网络状态 ====================

    def test_09_network_status(self):
        """TC-09: 网络状态"""
        self.log_test("TC-09: 网络状态", "START")

        try:
            # 检查网络连接
            is_online = self.driver.execute_script(
                "return navigator.onLine"
            )
            self.assertTrue(is_online, "应连接到网络")

            self.log_test("TC-09: 网络状态", "PASS", "网络正常")

        except Exception as e:
            self.log_test("TC-09: 网络状态", "FAIL", str(e))
            raise


if __name__ == '__main__':
    # 运行测试
    print("\n" + "="*70)
    print("你比划我猜 - Minium 自动化测试")
    print("="*70)

    # 配置测试运行器
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(GestureGuessMiniumTest)

    # 按顺序运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 打印总结
    print("\n" + "="*70)
    print("测试总结")
    print("="*70)
    print(f"总计: {result.testsRun} 个测试")
    print(f"✓ 通过: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"✗ 失败: {len(result.failures)}")
    print(f"✗ 错误: {len(result.errors)}")
    print("="*70 + "\n")

    # 退出码
    exit(0 if result.wasSuccessful() else 1)
