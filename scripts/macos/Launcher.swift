import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
guard let launcher = Bundle.main.url(forResource: "启动拾页", withExtension: "command"),
      NSWorkspace.shared.open(launcher) else {
    app.activate(ignoringOtherApps: true)
    let alert = NSAlert()
    alert.messageText = "无法启动拾页"
    alert.informativeText = "请将拾页复制到「应用程序」后重新打开。"
    alert.runModal()
    exit(1)
}
