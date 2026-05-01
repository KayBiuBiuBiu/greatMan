# macOS 用 launchd 保活 run_alert

1. 复制并重命名 plist（不要使用 `.example` 后缀才能 load）：
   ```bash
   cd /ABS/PATH/stock-price-alert/macos
   sed 's|/ABS/PATH/stock-price-alert|'"$(cd .. && pwd)"'|g' launchd-stock-price-alert.plist.example > com.local.stock-price-alert.plist
   ```
2. 安装并启动：
   ```bash
   mkdir -p ~/Library/LaunchAgents
   cp com.local.stock-price-alert.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.local.stock-price-alert.plist
   ```
3. 停止：
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.local.stock-price-alert.plist
   ```

`KeepAlive` 会在进程崩溃后由系统自动拉起。**日志**在未替换路径前请核对 `logs/launchd_*.log` 是否可读。
