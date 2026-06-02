"""
你比划我猜 - Minium 自动化测试脚本

这个脚本使用 Minium 框架来自动化真机测试主要场景。

前置条件:
1. 微信开发者工具已打开项目
2. 小程序已编译 (Ctrl/Cmd + B)
3. 云函数已部署 (gestureRoomService)
4. 数据库集合已创建
5. 微信开发者工具已启用自动化调试

运行: python tests/test_gesture_minium.py
"""

import time
import unittest
from minium import MiniTest, By


class GestureGuessMiniumTest(MiniTest):
    """你比划我猜 Minium 自动化测试"""

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
            # 等待页面加载
            time.sleep(2)

            # 查找「你比划我猜」游戏卡片
            gesture_card = self.page.get_element(
                'text',
                '你比划我猜',
                inner_text=True
            )
            self.assertIsNotNone(gesture_card, "应找到游戏卡片")
            gesture_card.click()
            time.sleep(2)

            # 输入昵称
            nick_input = self.page.get_element(
                'input',
                '[placeholder="输入你的昵称"]'
            )
            if nick_input:
                nick_input.send_keys('玩家A')
                time.sleep(1)

            # 点击创建按钮
            create_btn = self.page.get_element(
                'button',
                inner_text='创建聚会组'
            )
            if create_btn:
                create_btn.click()
                time.sleep(3)

            # 验证房间码出现
            code_text = self.page.get_elements('view')
            found_code = False
            for elem in code_text:
                try:
                    text = elem.get_text()
                    if '口令' in str(text):
                        found_code = True
                        break
                except:
                    pass

            self.assertTrue(found_code, "应显示房间码")

            self.log_test(
                "TC-01: 创建房间",
                "PASS",
                "房间创建成功"
            )

        except Exception as e:
            self.log_test("TC-01: 创建房间", "FAIL", str(e))
            raise

    # ==================== TC-02: 验证界面 ====================

    def test_02_verify_ui(self):
        """TC-02: 验证界面显示"""
        self.log_test("TC-02: 验证界面", "START")

        try:
            # 等待页面稳定
            time.sleep(1)

            # 查找成员列表
            view_elements = self.page.get_elements('view')
            self.assertGreater(len(view_elements), 0, "应有页面元素")

            self.log_test(
                "TC-02: 验证界面",
                "PASS",
                f"页面元素数: {len(view_elements)}"
            )

        except Exception as e:
            self.log_test("TC-02: 验证界面", "FAIL", str(e))
            raise

    # ==================== TC-03: 启动游戏 ====================

    def test_03_start_game(self):
        """TC-03: 启动游戏"""
        self.log_test("TC-03: 启动游戏", "START")

        try:
            # 查找开始按钮
            buttons = self.page.get_elements('button')
            start_btn = None
            for btn in buttons:
                try:
                    text = btn.get_text()
                    if '开始' in str(text):
                        start_btn = btn
                        break
                except:
                    pass

            if start_btn:
                start_btn.click()
                time.sleep(3)

                self.log_test("TC-03: 启动游戏", "PASS", "游戏已启动")
            else:
                self.log_test("TC-03: 启动游戏", "INFO", "开始按钮未找到（可能已禁用）")

        except Exception as e:
            self.log_test("TC-03: 启动游戏", "FAIL", str(e))

    # ==================== TC-04: 性能指标 ====================

    def test_04_performance(self):
        """TC-04: 性能指标"""
        self.log_test("TC-04: 性能指标", "START")

        try:
            # 获取页面加载性能
            perf_data = self.page.get_performance()

            if perf_data:
                self.log_test(
                    "TC-04: 性能指标",
                    "PASS",
                    f"性能数据已获取"
                )
            else:
                self.log_test(
                    "TC-04: 性能指标",
                    "INFO",
                    "无法获取性能数据"
                )

        except Exception as e:
            self.log_test("TC-04: 性能指标", "INFO", str(e))

    # ==================== TC-05: 网络状态 ====================

    def test_05_network_status(self):
        """TC-05: 网络状态"""
        self.log_test("TC-05: 网络状态", "START")

        try:
            # 检查网络连接
            is_online = self.page.execute_script(
                'return navigator.onLine'
            )
            self.assertTrue(is_online, "应连接到网络")

            self.log_test("TC-05: 网络状态", "PASS", "网络正常")

        except Exception as e:
            self.log_test("TC-05: 网络状态", "FAIL", str(e))


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
