import Cocoa
import WebKit

/// Codex 助手 —— 原生无终端外壳。
/// 启动时拉起同目录 Resources/server.py（本地 HTTP），
/// 再用 WKWebView 载入其网页 UI。整个生命周期不打开任何 Terminal。
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var server: Process?
    var port: String = ""
    let resDir: String
    var statusItem: NSStatusItem?
    var statusTimer: Timer?
    var statusHeader: NSMenuItem?
    var modelName: String = ""
    var relayUp: Bool = false
    var gatewayUp: Bool = false
    var aggMode: Bool = false
    // 供状态栏菜单展示的更丰富字段（来自 /api/status_panel）
    var menuInfo: [NSMenuItem] = []
    var provider: String = ""
    var account: String = ""
    var keyVar: String = ""
    var keySet: Bool = false
    var cfgOk: Bool = false
    var cfgModel: String = ""
    var modeText: String = ""
    var portTxt: String = ""
    var gwportTxt: String = ""
    var codeTxt: String = ""

    override init() {
        resDir = Bundle.main.resourcePath ?? ""
        super.init()
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildMainMenu()
        buildWindow()
        startServer()
        buildStatusItem()
    }

    func buildWindow() {
        let rect = NSRect(x: 0, y: 0, width: 1080, height: 780)
        window = NSWindow(contentRect: rect,
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Codex 助手"
        window.minSize = NSSize(width: 900, height: 620)
        window.center()
        window.setFrameAutosaveName("CodexSetupWindow")
        // 让窗口内容被 WindowServer 识别为不透明、可被捕获的 layer，
        // 否则台前调度/调度中心的窗口缩略图会是一片空白。
        window.isOpaque = true
        window.backgroundColor = .windowBackgroundColor
        window.contentView?.wantsLayer = true
        window.contentView?.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor

        let config = WKWebViewConfiguration()
        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.autoresizingMask = [.width, .height]
        window.contentView!.addSubview(webView)

        window.makeKeyAndOrderFront(nil)
        window.delegate = self
        NSApp.activate(ignoringOtherApps: true)
    }

    func startServer() {
        let py = "/usr/bin/python3"
        let script = (resDir as NSString).appendingPathComponent("server.py")
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = ["-E", script]
        p.currentDirectoryURL = URL(fileURLWithPath: resDir)

        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        var buffer = Data()

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { return }
            buffer.append(data)
            guard let self else { return }
            if self.port.isEmpty, let s = String(data: buffer, encoding: .utf8),
               let rng = s.range(of: "READY ") {
                let rest = s[rng.upperBound...]
                let portStr = String(rest.prefix { $0.isNumber })
                if !portStr.isEmpty {
                    self.port = portStr
                    DispatchQueue.main.async { self.loadUI() }
                }
            }
        }

        do {
            try p.run()
            server = p
        } catch {
            NSLog("无法启动后端: %@", error.localizedDescription)
        }
    }

    func loadUI() {
        guard let url = URL(string: "http://127.0.0.1:" + port + "/") else { return }
        webView.load(URLRequest(url: url))
    }

    // ── 顶部状态栏 ────────────────────────────────────────────
    func buildStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem = item
        if let btn = item.button {
            btn.target = self
            btn.action = #selector(statusClicked)
            btn.sendAction(on: [.leftMouseUp, .rightMouseUp])
            // 只保留闪电 logo（template，深浅色菜单栏自适应），不占文字宽度
            let icon = NSImage(named: "menu_icon")
            if let icon {
                icon.isTemplate = true
                // 顶部状态栏 logo 显式调小一点（默认会自动拉到整条栏高）
                icon.size = NSSize(width: 14, height: 14)
                btn.image = icon
                btn.imagePosition = .imageOnly
                btn.imageScaling = .scaleProportionallyUpOrDown
            }
        }
        rebuildMenu()
        statusTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { [weak self] _ in
            self?.refreshStatus()
        }
        refreshStatus()
    }

    func rebuildMenu() {
        let menu = NSMenu()
        let header = NSMenuItem(title: "Codex 助手", action: nil, keyEquivalent: "")
        header.isEnabled = false
        statusHeader = header
        menu.addItem(header)
        // 4 行只读服务信息（由 updateStatusBar 填充）
        menuInfo.removeAll()
        let placeholders = ["relay 服务：读取中…",
                            "运行模式：读取中…",
                            "当前模型：读取中…",
                            "API Key：读取中…"]
        for txt in placeholders {
            let it = NSMenuItem(title: txt, action: nil, keyEquivalent: "")
            it.isEnabled = false
            menuInfo.append(it)
            menu.addItem(it)
        }
        menu.addItem(.separator())
        let show = NSMenuItem(title: "显示主窗口", action: #selector(showWindow), keyEquivalent: "1")
        let panel = NSMenuItem(title: "打开服务状态面板", action: #selector(openStatusPanel), keyEquivalent: "")
        let refresh = NSMenuItem(title: "立即刷新", action: #selector(refreshNow), keyEquivalent: "r")
        let quit = NSMenuItem(title: "退出 Codex 助手", action: #selector(quitApp), keyEquivalent: "q")
        for it in [show, panel, refresh, quit] {
            it.target = self
        }
        menu.addItem(show)
        menu.addItem(panel)
        menu.addItem(refresh)
        menu.addItem(.separator())
        menu.addItem(quit)
        statusItem?.menu = menu
    }

    @objc func statusClicked() {
        statusItem?.button?.performClick(nil)
    }

    @objc func showWindow() {
        NSApp.setActivationPolicy(.regular)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func refreshNow() {
        refreshStatus()
    }

    @objc func quitApp() {
        NSApp.terminate(nil)
    }

    func refreshStatus() {
        guard !port.isEmpty else { return }
        guard let url = URL(string: "http://127.0.0.1:" + port + "/api/status_panel") else { return }
        let task = URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let self, let data = data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            let model = obj["model"] as? String ?? ""
            let code = obj["code"] as? String ?? ""
            let agg = obj["agg"] as? Bool ?? false
            let relay = obj["relay"] as? Bool ?? false
            let gw = obj["gateway"] as? Bool ?? false
            let provider = obj["provider"] as? String ?? ""
            let account = obj["account"] as? String ?? ""
            let keyVar = obj["key_var"] as? String ?? ""
            let keySet = obj["key_set"] as? Bool ?? false
            let cfg = obj["cfg"] as? Bool ?? false
            let cfgModel = obj["cfg_model"] as? String ?? ""
            let modeText = obj["mode"] as? String ?? ""
            let portTxt = String(obj["port"] as? Int ?? 4446)
            let gwTxt = String(obj["gwport"] as? Int ?? 4447)
            DispatchQueue.main.async {
                self.modelName = model
                self.codeTxt = code
                self.aggMode = agg
                self.relayUp = relay
                self.gatewayUp = gw
                self.provider = provider
                self.account = account
                self.keyVar = keyVar
                self.keySet = keySet
                self.cfgOk = cfg
                self.cfgModel = cfgModel
                self.modeText = modeText
                self.portTxt = portTxt
                self.gwportTxt = gwTxt
                self.updateStatusBar()
            }
        }
        task.resume()
    }

    func updateStatusBar() {
        let running = relayUp && (!aggMode || gatewayUp)
        // 状态栏按钮只显示 logo，不再占文字
        statusItem?.button?.title = ""

        let modeLine = aggMode ? "汇聚模式（7 厂商一个端口）" : "普通模式（单厂商直连）"
        let modelLabel = modelName.isEmpty ? "尚未设置"
                        : (provider.isEmpty ? modelName : provider + " · " + modelName)
        let cfgTxt = cfgOk ? (cfgModel.isEmpty ? "已写入" : "已写入（" + cfgModel + "）") : "尚未写入"
        let relayTxt = relayUp ? "运行中" : "未启动"
        let gwTxt = gatewayUp ? "运行中" : "未运行"

        // 逐行刷新只读信息
        if menuInfo.count >= 1 {
            menuInfo[0].title = aggMode
                ? "relay(\(portTxt))：\(relayTxt) · 网关(\(gwportTxt))：\(gwTxt)"
                : "relay(\(portTxt))：\(relayTxt)（普通模式直连）"
        }
        if menuInfo.count >= 2 { menuInfo[1].title = "运行模式：" + modeLine }
        if menuInfo.count >= 3 { menuInfo[2].title = "当前模型：" + modelLabel + (codeTxt.isEmpty ? "" : " [" + codeTxt + "]") }
        if menuInfo.count >= 4 { menuInfo[3].title = "API Key（\(keyVar)）：" + (keySet ? "已设置" : "未设置") + " · 配置" + cfgTxt }

        statusHeader?.title = (running ? "● 服务运行中" : "○ 服务未启动") + " · " + (modelName.isEmpty ? "Codex" : modelLabel)

        var summary = "模式: \(modeLine)\nrelay(\(portTxt)): \(relayTxt)"
        if aggMode { summary += "\n网关(\(gwportTxt)): \(gwTxt)" }
        summary += "\n当前模型: " + (modelName.isEmpty ? "还没设置" : modelLabel)
        summary += "\n账号: " + (account.isEmpty ? "-" : account)
        summary += "\nAPI Key(\(keyVar)): " + (keySet ? "已设置" : "未设置") + " · 配置" + cfgTxt
        statusItem?.button?.toolTip = summary
    }

    // 打开主窗口并在其中弹出完整的服务状态面板（配合 ⌘ 快捷键）
    @objc func openStatusPanel() {
        showWindow()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
            self?.webView?.evaluateJavaScript("if(typeof openStatus==='function')openStatus()", completionHandler: nil)
        }
    }

    // 主菜单：让网页里的 ⌘C/V/X/A、以及 ⌘R/⌘1 等真正可用
    func buildMainMenu() {
        let main = NSMenu()
        let appName = "Codex 助手"

        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu(title: appName)
        appItem.submenu = appMenu
        appMenu.addItem(NSMenuItem(title: "关于 " + appName,
                                   action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
                                   keyEquivalent: ""))
        appMenu.addItem(.separator())
        appMenu.addItem(NSMenuItem(title: "隐藏 " + appName,
                                   action: #selector(NSApplication.hide(_:)),
                                   keyEquivalent: "h"))
        appMenu.addItem(.separator())
        appMenu.addItem(NSMenuItem(title: "退出 " + appName,
                                   action: #selector(NSApplication.terminate(_:)),
                                   keyEquivalent: "q"))

        // 编辑菜单：WKWebView 文本输入依赖它接收 ⌘C/V/X/A/Z
        let editItem = NSMenuItem(title: "编辑", action: nil, keyEquivalent: "")
        main.addItem(editItem)
        let editMenu = NSMenu(title: "编辑")
        editItem.submenu = editMenu
        editMenu.addItem(_edit("撤销", Selector(("undo:")), "z"))
        let redo = _edit("重做", Selector(("redo:")), "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(redo)
        editMenu.addItem(.separator())
        editMenu.addItem(_edit("剪切", #selector(NSText.cut(_:)), "x"))
        editMenu.addItem(_edit("拷贝", #selector(NSText.copy(_:)), "c"))
        editMenu.addItem(_edit("粘贴", #selector(NSText.paste(_:)), "v"))
        editMenu.addItem(_edit("全选", #selector(NSText.selectAll(_:)), "a"))

        // 操作菜单
        let actItem = NSMenuItem(title: "操作", action: nil, keyEquivalent: "")
        main.addItem(actItem)
        let actMenu = NSMenu(title: "操作")
        actItem.submenu = actMenu
        let show = NSMenuItem(title: "显示主窗口", action: #selector(showWindow), keyEquivalent: "1")
        let panel = NSMenuItem(title: "打开服务状态面板", action: #selector(openStatusPanel), keyEquivalent: "")
        let refresh = NSMenuItem(title: "立即刷新服务状态", action: #selector(refreshNow), keyEquivalent: "r")
        for it in [show, panel, refresh] { it.target = self }
        actMenu.addItem(show)
        actMenu.addItem(panel)
        actMenu.addItem(refresh)

        NSApp.mainMenu = main
    }

    private func _edit(_ title: String, _ sel: Selector, _ key: String) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        it.target = nil   // 交给第一响应链（WKWebView 文本框）处理
        return it
    }

    // 非本机地址一律交给系统默认浏览器，避免在 WebView 里离开本地界面。
    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url,
           let host = url.host,
           host != "127.0.0.1", host != "localhost" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    // 让 JS 的 confirm() 弹出真正的原生确认框（否则 WKWebView 静默返回 false）
    func webView(_ webView: WKWebView,
                 runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.informativeText = "此操作会清空所有 API Key 并恢复默认配置。"
        alert.addButton(withTitle: "确定")
        alert.addButton(withTitle: "取消")
        alert.alertStyle = .warning
        let resp = alert.runModal()
        completionHandler(resp == .alertFirstButtonReturn)
    }

    func webView(_ webView: WKWebView,
                 runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "好")
        alert.runModal()
        completionHandler()
    }

    func applicationWillTerminate(_ note: Notification) {
        if let s = server, s.isRunning {
            s.terminate()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
