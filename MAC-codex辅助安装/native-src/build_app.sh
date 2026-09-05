#!/bin/bash
# 构建原生无终端 GUI .app（Swift 外壳 + Python 本地后端 + WKWebView UI）
set -euo pipefail
MACDIR="$(cd "$(dirname "$0")/.." && pwd)"
SRCDIR="$(cd "$(dirname "$0")" && pwd)"
APP="$MACDIR/Codex Setup.app"                       # 覆盖旧的、会跳终端的 AppleScript 版
CONT="$APP/Contents"; RES="$CONT/Resources"; MACOS="$CONT/MacOS"

rm -rf "$APP"
mkdir -p "$RES" "$MACOS"

# 1) 逻辑层 + 本地后端 + 网页 UI
cp "$SRCDIR/codex_setup_gui.py" "$RES/"
cp "$SRCDIR/server.py"          "$RES/"

# 2) relay / gateway 二进制（已解出；也支持从同目录 codex-*.bin）
cp /tmp/relaytest/codex-relay   "$RES/codex-relay"
cp /tmp/relaytest/relay-gateway "$RES/relay-gateway"
chmod 755 "$RES/codex-relay" "$RES/relay-gateway"

# 2.5) App 图标 + 状态栏 template 图标
cp "$SRCDIR/assets/CodexSetup.icns" "$RES/CodexSetup.icns"
cp "$SRCDIR/assets/menu_icon.png"   "$RES/menu_icon.png"
cp "$SRCDIR/assets/menu_icon@2x.png" "$RES/menu_icon@2x.png"

# 3) Swift 原生外壳 → 真二进制（双击不会进终端）
/usr/bin/swiftc "$SRCDIR/main.swift" -o "$MACOS/CodexSetup" \
    -framework Cocoa -framework WebKit
chmod 755 "$MACOS/CodexSetup"

# 4) Info.plist —— 允许访问 127.0.0.1 本地 http
cat > "$CONT/Info.plist" <<'PL'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Codex Setup</string>
  <key>CFBundleDisplayName</key><string>Codex 助手</string>
  <key>CFBundleIdentifier</key><string>com.codex.setup.desktop</string>
  <key>CFBundleExecutable</key><string>CodexSetup</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleShortVersionString</key><string>2.0</string>
  <key>CFBundleVersion</key><string>2</string>
  <key>CFBundleIconFile</key><string>CodexSetup</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSUIElement</key><false/>
  <key>NSAppleEventsUsageDescription</key>
  <string>用于读取/写入 Codex 配置以切换国产大模型。</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key><true/>
    <key>NSExceptionDomains</key>
    <dict>
      <key>127.0.0.1</key>
      <dict><key>NSExceptionAllowsInsecureHTTPLoads</key><true/></dict>
      <key>localhost</key>
      <dict><key>NSExceptionAllowsInsecureHTTPLoads</key><true/></dict>
    </dict>
  </dict>
</dict>
</plist>
PL
printf 'APPL????' > "$CONT/PkgInfo"

echo "BUILT: $APP"
find "$APP" -type f | sort
