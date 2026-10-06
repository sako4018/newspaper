// Съветник за инсталиране на „Сутрешен вестник“ (класически Mac инсталатор: стъпки вляво,
// „Назад“ и „Продължи“ долу). Програмата на вестника е в Contents/Resources/payload и се копира в
// ~/Library/Application Support/Сутрешен вестник. Същото приложение после служи за смяна на настройките.
// Строи се от installer/build.sh.
//
// Тих режим (за проверките в GitHub Actions), без прозорец; започва от досегашния избор:
//   Installer --silent [--version lite|claude] [--topics bg,world] [--city Пловдив] [--time 06:30] [--print 0|1]
//   Installer --silent --uninstall

import AppKit

let fm = FileManager.default
let home = fm.homeDirectoryForCurrentUser
let installDir = home.appendingPathComponent("Library/Application Support/Сутрешен вестник")
let settingsApp = home.appendingPathComponent("Applications/Сутрешен вестник – настройки.app")
// Псевдоним (alias) на Desktop към приложението за настройки; ако не му трябва, човек просто го трие.
let desktopIcon = home.appendingPathComponent("Desktop/Сутрешен вестник – настройки")
let venvPython = installDir.appendingPathComponent(".venv/bin/python")
let resources = Bundle.main.resourceURL!

struct Topic: Decodable {
    let id: String
    let name: String
    let about: String
}

struct City {
    let name: String
    let lat: Double
    let lon: Double
}

// Изборът на потребителя
class Choices {
    var version = "lite"
    var topics: [String] = []
    var city: City? = nil
    var cityName: String? = nil   // само име (тих режим); търси се от app/apply_settings.py
    var storiesPerTopic = 4
    var maxStories = 17
    var hour = 6
    var minute = 0
    var print = false
}

// ---------- Помощни функции ----------

/// Пуска програма и връща кода и целия изход. onLine получава всеки нов ред (за напредъка).
@discardableResult
func run(_ path: String, _ args: [String], cwd: URL? = nil, onLine: ((String) -> Void)? = nil) -> (Int32, String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: path)
    p.arguments = args
    if let cwd = cwd { p.currentDirectoryURL = cwd }
    var env = ProcessInfo.processInfo.environment
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
    env["PYTHONIOENCODING"] = "utf-8"
    p.environment = env
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    var output = ""
    let lock = NSLock()
    pipe.fileHandleForReading.readabilityHandler = { h in
        let data = h.availableData
        if data.isEmpty { return }
        let text = String(decoding: data, as: UTF8.self)
        lock.lock(); output += text; lock.unlock()
        for line in text.split(separator: "\n") {
            let s = line.trimmingCharacters(in: .whitespaces)
            if !s.isEmpty { onLine?(s) }
        }
    }
    do {
        try p.run()
    } catch {
        return (-1, "Не мога да пусна \(path): \(error.localizedDescription)")
    }
    p.waitUntilExit()
    pipe.fileHandleForReading.readabilityHandler = nil
    let rest = pipe.fileHandleForReading.readDataToEndOfFile()
    lock.lock(); output += String(decoding: rest, as: UTF8.self); lock.unlock()
    return (p.terminationStatus, output)
}

/// Намира Python 3.9 или по-нов. /usr/bin/python3 се ползва само ако инструментите на Apple са инсталирани
/// (иначе macOS показва прозорец за инсталирането им).
func findPython() -> String? {
    var candidates: [String] = []
    if run("/usr/bin/xcode-select", ["-p"]).0 == 0 {
        candidates.append("/usr/bin/python3")
    }
    candidates += ["/opt/homebrew/bin/python3", "/usr/local/bin/python3",
                   "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"]
    for path in candidates where fm.isExecutableFile(atPath: path) {
        if run(path, ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"]).0 == 0 {
            return path
        }
    }
    return nil
}

func claudeInstalled() -> Bool {
    let paths = [".local/bin/claude", ".claude/local/claude"].map { home.appendingPathComponent($0).path }
        + ["/usr/local/bin/claude", "/opt/homebrew/bin/claude"]
    return paths.contains { fm.isExecutableFile(atPath: $0) }
}

func isInstalled() -> Bool {
    return fm.isExecutableFile(atPath: venvPython.path)
}

func label(_ text: String, size: CGFloat = 13, bold: Bool = false, color: NSColor = .labelColor) -> NSTextField {
    let l = NSTextField(wrappingLabelWithString: text)
    l.font = bold ? NSFont.boldSystemFont(ofSize: size) : NSFont.systemFont(ofSize: size)
    l.textColor = color
    return l
}

/// Изглед, в който y расте надолу (по-лесно се подреждат редове отгоре надолу).
class FlippedView: NSView {
    override var isFlipped: Bool { return true }
}

// ---------- Съветникът ----------

class Wizard: NSObject, NSWindowDelegate {
    let steps = ["Въведение", "Версия", "Теми", "Настройки", "Обобщение", "Инсталиране", "Готово"]
    let window: NSWindow
    let content = FlippedView()
    let titleLabel = label("", size: 15, bold: true)
    let backButton = NSButton(title: "Назад", target: nil, action: nil)
    let nextButton = NSButton(title: "Продължи", target: nil, action: nil)
    var stepDots: [NSTextField] = []
    var stepNames: [NSTextField] = []
    var step = 0
    var installing = false

    let choices = Choices()
    var topics: [Topic] = []
    let wasInstalled = isInstalled()
    let silent: Bool

    // елементи, чиито стойности се четат
    var topicBoxes: [NSButton] = []
    var cityField = NSTextField()
    var cityPopup = NSPopUpButton()
    var cityResults: [City] = []
    var countStepper = NSStepper()
    var countLabel = NSTextField()
    var timePicker = NSDatePicker()
    var printBox = NSButton()
    var progress = NSProgressIndicator()
    var statusLabel = NSTextField()
    var detailLabel = NSTextField()

    init(silent: Bool = false) {
        self.silent = silent
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 450),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        super.init()
        if silent {
            loadTopics()
            loadSavedChoices()
            return
        }
        window.title = wasInstalled ? "Настройки на „Сутрешен вестник“" : "Инсталиране на „Сутрешен вестник“"
        window.delegate = self
        loadTopics()
        loadSavedChoices()
        buildFrame()
        show(0)
        window.center()
        window.makeKeyAndOrderFront(nil)
    }

    func loadTopics() {
        if let data = try? Data(contentsOf: resources.appendingPathComponent("topics.json")),
           let list = try? JSONDecoder().decode([Topic].self, from: data) {
            topics = list
        }
    }

    /// При смяна на настройки съветникът започва с това, което вече е в профила.
    func loadSavedChoices() {
        guard wasInstalled else { return }
        let (code, out) = run(venvPython.path, [installDir.appendingPathComponent("app/apply_settings.py").path, "--dump"])
        guard code == 0, let data = out.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        if let v = json["version"] as? String, v == "claude" || v == "lite" { choices.version = v }
        if let t = json["topics"] as? [String] { choices.topics = t }
        if let c = json["city"] as? [String: Any], let n = c["name"] as? String,
           let lat = c["lat"] as? Double, let lon = c["lon"] as? Double {
            choices.city = City(name: n, lat: lat, lon: lon)
        }
        if let n = json["stories_per_topic"] as? Int { choices.storiesPerTopic = n }
        if let n = json["max_stories"] as? Int { choices.maxStories = n }
        if let t = json["schedule_time"] as? String {
            let parts = t.split(separator: ":").compactMap { Int($0) }
            if parts.count == 2 { choices.hour = parts[0]; choices.minute = parts[1] }
        }
        if let p = json["print"] as? Bool { choices.print = p }
    }

    // Рамката: стъпки вляво, заглавие и съдържание вдясно, бутони долу
    func buildFrame() {
        let root = window.contentView!

        let side = NSView(frame: NSRect(x: 0, y: 0, width: 180, height: 450))
        side.wantsLayer = true
        side.layer?.backgroundColor = NSColor.underPageBackgroundColor.cgColor
        root.addSubview(side)

        let paper = label("📰", size: 90)
        paper.alphaValue = 0.18
        paper.frame = NSRect(x: 20, y: 20, width: 140, height: 110)
        side.addSubview(paper)

        for (i, name) in steps.enumerated() {
            let y = CGFloat(400 - i * 30)
            let dot = label("●", size: 11, color: .tertiaryLabelColor)
            dot.frame = NSRect(x: 22, y: y, width: 16, height: 18)
            let text = label(name, size: 13, color: .secondaryLabelColor)
            text.frame = NSRect(x: 40, y: y, width: 135, height: 18)
            side.addSubview(dot)
            side.addSubview(text)
            stepDots.append(dot)
            stepNames.append(text)
        }

        titleLabel.frame = NSRect(x: 200, y: 400, width: 420, height: 22)
        root.addSubview(titleLabel)

        let box = NSBox(frame: NSRect(x: 196, y: 58, width: 428, height: 332))
        box.boxType = .custom
        box.borderColor = .separatorColor
        box.borderWidth = 1
        box.cornerRadius = 4
        box.fillColor = .textBackgroundColor
        root.addSubview(box)
        content.frame = NSRect(x: 0, y: 0, width: 428, height: 332)
        box.contentView = content

        nextButton.frame = NSRect(x: 510, y: 14, width: 116, height: 32)
        nextButton.bezelStyle = .rounded
        nextButton.keyEquivalent = "\r"
        nextButton.target = self
        nextButton.action = #selector(goNext)
        backButton.frame = NSRect(x: 396, y: 14, width: 110, height: 32)
        backButton.bezelStyle = .rounded
        backButton.target = self
        backButton.action = #selector(goBack)
        root.addSubview(nextButton)
        root.addSubview(backButton)
    }

    func show(_ index: Int) {
        step = index
        for (i, dot) in stepDots.enumerated() {
            dot.textColor = i <= step ? .controlAccentColor : .tertiaryLabelColor
            stepNames[i].textColor = i == step ? .labelColor : .secondaryLabelColor
            stepNames[i].font = i == step ? NSFont.boldSystemFont(ofSize: 13) : NSFont.systemFont(ofSize: 13)
        }
        content.subviews.forEach { $0.removeFromSuperview() }
        backButton.isHidden = step == 0 || step >= 5
        backButton.isEnabled = true
        nextButton.isEnabled = true
        nextButton.title = "Продължи"
        switch step {
        case 0: pageIntro()
        case 1: pageVersion()
        case 2: pageTopics()
        case 3: pageOptions()
        case 4: pageSummary()
        case 5: pageInstall()
        default: pageDone()
        }
    }

    /// Подрежда изгледите един под друг в съдържанието.
    func stack(_ views: [NSView], spacing: CGFloat = 12) {
        var y: CGFloat = 20
        for v in views {
            let height = v is NSTextField ? (v as! NSTextField).sizeThatFits(NSSize(width: 388, height: 1000)).height : v.frame.height
            v.frame = NSRect(x: 20, y: y, width: v.frame.width > 0 && !(v is NSTextField) ? v.frame.width : 388, height: height)
            content.addSubview(v)
            y += height + spacing
        }
    }

    // ---------- Страници ----------

    func pageIntro() {
        titleLabel.stringValue = wasInstalled ? "Смяна на настройките" : "Добре дошли"
        var views: [NSView] = []
        if wasInstalled {
            views.append(label("„Сутрешен вестник“ вече е инсталиран на този Mac.\n\nПродължи, за да смениш версията, темите, града, часа или печата. Новите настройки важат от следващия брой."))
            let remove = NSButton(title: "Деинсталирай…", target: self, action: #selector(uninstall))
            remove.bezelStyle = .rounded
            remove.frame = NSRect(x: 0, y: 0, width: 150, height: 30)
            views.append(remove)
        } else {
            views.append(label("Този съветник ще инсталира „Сутрешен вестник“ на твоя Mac."))
            views.append(label("Всяка сутрин програмата събира новини от БТА, Дневник, BBC, Guardian и още около 80 източника и ги подрежда в Word документ (.docx) в папка „Сутрешен вестник“ на Desktop."))
            views.append(label("Ще избереш:\n   •  версия (Claude или Lite)\n   •  теми\n   •  град за времето и час за всеки ден\n   •  дали да се печата"))
            views.append(label("Трябва ти интернет и около 1 ГБ свободно място. Инсталирането отнема няколко минути.", size: 12, color: .secondaryLabelColor))
        }
        stack(views)
    }

    func pageVersion() {
        titleLabel.stringValue = "Избери версия"
        let lite = NSButton(radioButtonWithTitle: "Lite", target: self, action: #selector(versionChanged(_:)))
        lite.identifier = NSUserInterfaceItemIdentifier("lite")
        lite.font = NSFont.boldSystemFont(ofSize: 13)
        let liteText = label("Без изкуствен интелект. Подбира новините по правила и превежда чуждите на български без интернет. Излизат повече новини на няколко страници.", size: 12, color: .secondaryLabelColor)
        let claude = NSButton(radioButtonWithTitle: "Claude", target: self, action: #selector(versionChanged(_:)))
        claude.identifier = NSUserInterfaceItemIdentifier("claude")
        claude.font = NSFont.boldSystemFont(ofSize: 13)
        var claudeNote = "Claude обобщава, оценява и подрежда новините. Излиза една страница A4 с около 17 истории. Трае до половин час и ползва от твоя Claude план."
        if !claudeInstalled() {
            claudeNote += "\n⚠️ На този Mac няма Claude Code (командата claude). Инсталирай го от claude.com/claude-code, иначе избери Lite."
        }
        let claudeText = label(claudeNote, size: 12, color: .secondaryLabelColor)
        lite.state = choices.version == "lite" ? .on : .off
        claude.state = choices.version == "claude" ? .on : .off
        for b in [lite, claude] { b.frame = NSRect(x: 0, y: 0, width: 300, height: 20) }
        stack([lite, liteText, claude, claudeText], spacing: 8)
        liteText.frame.origin.x = 40; liteText.frame.size.width = 368
        claudeText.frame.origin.x = 40; claudeText.frame.size.width = 368
        claude.frame.origin.y += 12; claudeText.frame.origin.y += 12
    }

    @objc func versionChanged(_ sender: NSButton) {
        choices.version = sender.identifier?.rawValue ?? "lite"
    }

    func pageTopics() {
        titleLabel.stringValue = "Избери теми"
        let hint = label("Отметни темите, които искаш да има във вестника.", size: 12, color: .secondaryLabelColor)
        hint.frame = NSRect(x: 20, y: 14, width: 250, height: 32)
        content.addSubview(hint)
        let all = NSButton(title: "Всички", target: self, action: #selector(selectAll))
        let none = NSButton(title: "Нито една", target: self, action: #selector(selectNone))
        all.frame = NSRect(x: 270, y: 12, width: 66, height: 26)
        none.frame = NSRect(x: 336, y: 12, width: 80, height: 26)
        for b in [all, none] { b.bezelStyle = .rounded; b.controlSize = .small; content.addSubview(b) }

        let scroll = NSScrollView(frame: NSRect(x: 10, y: 50, width: 408, height: 272))
        scroll.hasVerticalScroller = true
        scroll.drawsBackground = false
        let list = FlippedView()
        topicBoxes = []
        let rows = (topics.count + 1) / 2
        for (i, t) in topics.enumerated() {
            let box = NSButton(checkboxWithTitle: t.name, target: nil, action: nil)
            box.identifier = NSUserInterfaceItemIdentifier(t.id)
            box.toolTip = t.about
            box.state = choices.topics.contains(t.id) ? .on : .off
            let column = i / rows
            let row = i % rows
            box.frame = NSRect(x: 12 + column * 195, y: 4 + row * 28, width: 190, height: 22)
            list.addSubview(box)
            topicBoxes.append(box)
        }
        list.frame = NSRect(x: 0, y: 0, width: 390, height: max(270, rows * 28 + 8))
        scroll.documentView = list
        content.addSubview(scroll)
    }

    @objc func selectAll() { topicBoxes.forEach { $0.state = .on } }
    @objc func selectNone() { topicBoxes.forEach { $0.state = .off } }

    func pageOptions() {
        titleLabel.stringValue = "Настройки"

        let cityTitle = label("Град за времето (по желание):", bold: true)
        cityTitle.frame = NSRect(x: 20, y: 16, width: 388, height: 18)
        cityField = NSTextField(frame: NSRect(x: 20, y: 40, width: 220, height: 24))
        cityField.placeholderString = "напр. Пловдив"
        let search = NSButton(title: "Търси", target: self, action: #selector(searchCity))
        search.bezelStyle = .rounded
        search.frame = NSRect(x: 246, y: 38, width: 80, height: 28)
        cityPopup = NSPopUpButton(frame: NSRect(x: 18, y: 72, width: 392, height: 26))
        cityPopup.target = self
        cityPopup.action = #selector(cityPicked)
        cityResults = []
        cityPopup.removeAllItems()
        cityPopup.addItem(withTitle: "Без град")
        if let c = choices.city {
            cityResults = [c]
            cityPopup.addItem(withTitle: c.name)
            cityPopup.selectItem(at: 1)
        }

        let isClaude = choices.version == "claude"
        let countTitle = label(isClaude ? "Общо истории във вестника:" : "Истории на тема:", bold: true)
        countTitle.frame = NSRect(x: 20, y: 118, width: 230, height: 18)
        countStepper = NSStepper(frame: NSRect(x: 290, y: 115, width: 20, height: 26))
        countStepper.minValue = isClaude ? 5 : 1
        countStepper.maxValue = isClaude ? 25 : 10
        countStepper.integerValue = isClaude ? choices.maxStories : choices.storiesPerTopic
        countStepper.target = self
        countStepper.action = #selector(countChanged)
        countLabel = label("\(countStepper.integerValue)", bold: true)
        countLabel.alignment = .right
        countLabel.frame = NSRect(x: 250, y: 118, width: 34, height: 18)

        let timeTitle = label("Всеки ден в:", bold: true)
        timeTitle.frame = NSRect(x: 20, y: 160, width: 230, height: 18)
        timePicker = NSDatePicker(frame: NSRect(x: 250, y: 156, width: 80, height: 26))
        timePicker.datePickerStyle = .textFieldAndStepper
        timePicker.datePickerElements = .hourMinute
        timePicker.locale = Locale(identifier: "bg_BG")
        var parts = DateComponents()
        parts.hour = choices.hour
        parts.minute = choices.minute
        timePicker.dateValue = Calendar.current.date(from: parts) ?? Date()
        let timeNote = label("Ако Mac-ът спи в този час, вестникът се прави, щом се събуди.", size: 11, color: .secondaryLabelColor)
        timeNote.frame = NSRect(x: 20, y: 184, width: 388, height: 16)

        printBox = NSButton(checkboxWithTitle: "Печатай вестника на принтера всяка сутрин", target: nil, action: nil)
        printBox.state = choices.print ? .on : .off
        printBox.frame = NSRect(x: 18, y: 222, width: 390, height: 20)
        let printNote = label("Включи го, когато имаш принтер, добавен в System Settings → Printers & Scanners. Нужен е и Google Chrome.", size: 11, color: .secondaryLabelColor)
        printNote.frame = NSRect(x: 38, y: 246, width: 370, height: 30)

        for v in [cityTitle, cityField, search, cityPopup, countTitle, countLabel, countStepper,
                  timeTitle, timePicker, timeNote, printBox, printNote] {
            content.addSubview(v)
        }
    }

    @objc func countChanged() {
        countLabel.stringValue = "\(countStepper.integerValue)"
    }

    @objc func searchCity() {
        let name = cityField.stringValue.trimmingCharacters(in: .whitespaces)
        guard name.count >= 2,
              let q = name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
              let url = URL(string: "https://geocoding-api.open-meteo.com/v1/search?name=\(q)&count=6&language=bg") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            var found: [City] = []
            if let data = data,
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let results = json["results"] as? [[String: Any]] {
                for r in results {
                    guard let n = r["name"] as? String, let lat = r["latitude"] as? Double,
                          let lon = r["longitude"] as? Double else { continue }
                    let country = r["country"] as? String
                    found.append(City(name: country != nil ? "\(n), \(country!)" : n, lat: lat, lon: lon))
                }
            }
            DispatchQueue.main.async {
                self.cityResults = found
                self.cityPopup.removeAllItems()
                self.cityPopup.addItem(withTitle: "Без град")
                if found.isEmpty {
                    self.cityPopup.addItem(withTitle: "Няма намерен град „\(name)“")
                    self.cityPopup.lastItem?.isEnabled = false
                    self.cityPopup.autoenablesItems = false
                    self.cityPopup.selectItem(at: 0)
                } else {
                    for c in found { self.cityPopup.addItem(withTitle: c.name) }
                    self.cityPopup.selectItem(at: 1)
                }
            }
        }.resume()
    }

    @objc func cityPicked() {}

    func pageSummary() {
        titleLabel.stringValue = "Обобщение"
        let names = topics.filter { choices.topics.contains($0.id) }.map { $0.name }
        let count = choices.version == "claude" ? "общо \(choices.maxStories) истории" : "\(choices.storiesPerTopic) истории на тема"
        let time = String(format: "%02d:%02d", choices.hour, choices.minute)
        let text = """
        Версия:  \(choices.version == "claude" ? "Claude" : "Lite") (\(count))
        Теми:  \(names.joined(separator: ", "))
        Град:  \(choices.city?.name ?? "без град")
        Всеки ден в:  \(time)
        Печат:  \(choices.print ? "да" : "не")
        """
        let where_ = wasInstalled
            ? "Натисни „Запази“, за да се приложат настройките."
            : "Натисни „Инсталирай“. Програмата отива в ~/Library/Application Support/Сутрешен вестник, а в Applications се появява „Сутрешен вестник – настройки“ за смяна на избора после."
        stack([label(text), label(where_, size: 12, color: .secondaryLabelColor)], spacing: 18)
        nextButton.title = wasInstalled ? "Запази" : "Инсталирай"
    }

    func pageInstall() {
        titleLabel.stringValue = wasInstalled ? "Записване" : "Инсталиране"
        statusLabel = label("Подготовка…", bold: true)
        statusLabel.frame = NSRect(x: 20, y: 110, width: 388, height: 18)
        progress = NSProgressIndicator(frame: NSRect(x: 20, y: 136, width: 388, height: 20))
        progress.style = .bar
        progress.isIndeterminate = false
        progress.minValue = 0
        progress.maxValue = 5
        detailLabel = label("", size: 11, color: .secondaryLabelColor)
        detailLabel.frame = NSRect(x: 20, y: 164, width: 388, height: 120)
        detailLabel.maximumNumberOfLines = 8
        for v in [statusLabel, progress, detailLabel] { content.addSubview(v) }
        backButton.isHidden = true
        nextButton.isEnabled = false
        installing = true
        let c = choices
        DispatchQueue.global().async { self.install(c) }
    }

    func pageDone() {
        titleLabel.stringValue = "Готово"
        let time = String(format: "%02d:%02d", choices.hour, choices.minute)
        stack([
            label("✅  Готово!", size: 22, bold: true),
            label("Всеки ден в \(time) вестникът се прави сам. Всеки брой се пази на Desktop в папка „Сутрешен вестник“ с име като „05.10.2026 06.30.docx“."),
            label("Първият брой се прави още сега. Първия път macOS може да попита дали „Сутрешен вестник“ може да ползва папката Desktop. Отговори Allow."),
            label("Настройките сменяш от иконката „Сутрешен вестник – настройки“ на Desktop (ако не ти трябва, изтрий я; приложението остава в Applications). Там е и деинсталирането.", size: 12, color: .secondaryLabelColor),
        ])
        nextButton.title = "Затвори"
    }

    // ---------- Навигация ----------

    @objc func goNext() {
        if !saveCurrentPage() { return }
        if step == 2 && choices.topics.isEmpty {
            let a = NSAlert()
            a.messageText = "Избери поне една тема."
            a.runModal()
            return
        }
        if step == 6 { NSApp.terminate(nil); return }
        if step == 5 { show(5); return }   // „Опитай пак“ след грешка
        show(step + 1)
    }

    @objc func goBack() {
        _ = saveCurrentPage()
        show(step - 1)
    }

    /// Взима стойностите от страницата. Връща false, ако нещо липсва.
    func saveCurrentPage() -> Bool {
        switch step {
        case 2:
            choices.topics = topicBoxes.filter { $0.state == .on }.compactMap { $0.identifier?.rawValue }
        case 3:
            let i = cityPopup.indexOfSelectedItem
            choices.city = i >= 1 && i - 1 < cityResults.count ? cityResults[i - 1] : nil
            if choices.version == "claude" { choices.maxStories = countStepper.integerValue }
            else { choices.storiesPerTopic = countStepper.integerValue }
            let parts = Calendar.current.dateComponents([.hour, .minute], from: timePicker.dateValue)
            choices.hour = parts.hour ?? 6
            choices.minute = parts.minute ?? 0
            choices.print = printBox.state == .on
        default:
            break
        }
        return true
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if installing {
            let a = NSAlert()
            a.messageText = "Инсталирането още не е свършило."
            a.informativeText = "Изчакай да завърши. Ако го спреш сега, пусни съветника пак после."
            a.addButton(withTitle: "Изчакай")
            a.addButton(withTitle: "Спри")
            return a.runModal() == .alertSecondButtonReturn
        }
        return true
    }

    // ---------- Инсталиране (върви във фонов поток) ----------

    func status(_ text: String, _ value: Double) {
        if silent { print(text); return }
        DispatchQueue.main.async {
            self.statusLabel.stringValue = text
            self.progress.doubleValue = value
            self.detailLabel.stringValue = ""
        }
    }

    func detail(_ text: String) {
        if silent { print("   " + text); return }
        DispatchQueue.main.async { self.detailLabel.stringValue = String(text.prefix(300)) }
    }

    func install(_ c: Choices) {
        let error = installSteps(c)
        DispatchQueue.main.async {
            self.installing = false
            if let error = error {
                self.statusLabel.stringValue = "Не успях."
                self.detailLabel.stringValue = error
                self.detailLabel.textColor = .systemRed
                self.backButton.isHidden = false
                self.nextButton.isEnabled = true
                self.nextButton.title = "Опитай пак"
                if error.contains("Python") { self.offerCommandLineTools() }
            } else {
                self.progress.doubleValue = 5
                self.show(6)
            }
        }
    }

    /// Връща nil при успех или текст на грешката.
    func installSteps(_ c: Choices) -> String? {
        status("Търся Python…", 0)
        guard let python = findPython() else {
            return "Няма Python 3.9 или по-нов. Инсталирай инструментите на Apple за команден ред (бутонът в прозореца) и пусни съветника пак."
        }

        status("Копирам файловете…", 1)
        try? fm.createDirectory(at: installDir, withIntermediateDirectories: true)
        let payload = resources.appendingPathComponent("payload").path
        let (copyCode, copyOut) = run("/usr/bin/ditto", [payload, installDir.path])
        if copyCode != 0 { return "Копирането не успя:\n" + copyOut }

        status("Подготвям Python и пакетите (първия път отнема няколко минути)…", 2)
        let ready = fm.isExecutableFile(atPath: venvPython.path)
            && run(venvPython.path, ["-c", "import yaml, feedparser, docx, argostranslate"]).0 == 0
        if !ready {
            if !fm.isExecutableFile(atPath: venvPython.path) {
                detail("Създавам виртуална среда…")
                let (code, out) = run(python, ["-m", "venv", installDir.appendingPathComponent(".venv").path])
                if code != 0 { return "Не успях да направя виртуалната среда:\n" + out }
            }
            run(venvPython.path, ["-m", "pip", "install", "-q", "--upgrade", "pip"], onLine: detail)
            let reqs = ["claude/requirements.txt", "lite/requirements.txt"].flatMap {
                ["-r", installDir.appendingPathComponent($0).path]
            }
            let (code, out) = run(venvPython.path, ["-m", "pip", "install", "--progress-bar", "off"] + reqs, onLine: detail)
            if code != 0 {
                return "Инсталирането на пакетите не успя. Провери интернет връзката и опитай пак.\n" + String(out.suffix(400))
            }
        }

        status("Записвам настройките…", 3)
        var settings: [String: Any] = [
            "version": c.version,
            "topics": topics.map { $0.id }.filter { c.topics.contains($0) },
            "stories_per_topic": c.storiesPerTopic,
            "max_stories": c.maxStories,
            "schedule_time": String(format: "%02d:%02d", c.hour, c.minute),
            "print": c.print,
        ]
        if let name = c.cityName {
            settings["city_name"] = name
        } else if let city = c.city {
            settings["city"] = ["name": city.name, "lat": city.lat, "lon": city.lon]
        } else {
            settings["city"] = NSNull()
        }
        let tmp = fm.temporaryDirectory.appendingPathComponent("vestnik-settings.json")
        do {
            try JSONSerialization.data(withJSONObject: settings).write(to: tmp)
        } catch {
            return "Не мога да запиша настройките: \(error.localizedDescription)"
        }
        let (saveCode, saveOut) = run(venvPython.path, [installDir.appendingPathComponent("app/apply_settings.py").path, tmp.path])
        try? fm.removeItem(at: tmp)
        if saveCode != 0 { return "Не мога да запиша профила:\n" + saveOut }

        status("Включвам ежедневното пускане…", 4)
        let (schedCode, schedOut) = run("/bin/bash", [installDir.appendingPathComponent("claude/install.sh").path])
        if schedCode != 0 { return "Не успях да включа графика:\n" + schedOut }

        // Копие на съветника в Applications, за да се сменят настройките после
        if Bundle.main.bundleURL.standardizedFileURL.path != settingsApp.standardizedFileURL.path {
            status("Слагам „Сутрешен вестник – настройки“ в Applications…", 4.5)
            try? fm.createDirectory(at: settingsApp.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? fm.removeItem(at: settingsApp)
            run("/usr/bin/ditto", [Bundle.main.bundlePath, settingsApp.path])
            run("/usr/bin/xattr", ["-dr", "com.apple.quarantine", settingsApp.path])
            // Иконка на Desktop само при първото инсталиране: при смяна на настройките не се връща, ако е изтрита.
            if let data = try? settingsApp.bookmarkData(options: .suitableForBookmarkFile,
                                                       includingResourceValuesForKeys: nil, relativeTo: nil) {
                try? fm.removeItem(at: desktopIcon)
                try? URL.writeBookmarkData(data, to: desktopIcon)
            }
        }
        return nil
    }

    func offerCommandLineTools() {
        let a = NSAlert()
        a.messageText = "Нужен е Python"
        a.informativeText = "macOS има Python в „инструментите за команден ред“ на Apple. Натисни „Инсталирай“ и следвай прозореца на Apple (няколко минути). После пусни този съветник пак."
        a.addButton(withTitle: "Инсталирай")
        a.addButton(withTitle: "Отказ")
        if a.runModal() == .alertFirstButtonReturn {
            run("/usr/bin/xcode-select", ["--install"])
        }
    }

    // ---------- Деинсталиране ----------

    func removeEverything() {
        run("/bin/bash", [installDir.appendingPathComponent("claude/uninstall.sh").path])
        try? fm.removeItem(at: installDir)
        try? fm.removeItem(at: settingsApp)
        try? fm.removeItem(at: desktopIcon)
    }

    // ---------- Тих режим ----------

    /// Чете аргументите, инсталира (или деинсталира) без прозорец и връща кода на изход.
    func runSilent(_ args: [String]) -> Int32 {
        var i = 0
        func value() -> String? { i += 1; return i < args.count ? args[i] : nil }
        var uninstall = false
        while i < args.count {
            switch args[i] {
            case "--silent": break
            case "--uninstall": uninstall = true
            case "--version":
                guard let v = value(), v == "lite" || v == "claude" else { print("--version е lite или claude"); return 2 }
                choices.version = v
            case "--topics":
                guard let v = value() else { return 2 }
                choices.topics = v.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }
            case "--city":
                guard let v = value() else { return 2 }
                choices.cityName = v
            case "--time":
                let parts = (value() ?? "").split(separator: ":").compactMap { Int($0) }
                guard parts.count == 2, (0...23).contains(parts[0]), (0...59).contains(parts[1]) else {
                    print("--time е ЧЧ:ММ"); return 2
                }
                choices.hour = parts[0]; choices.minute = parts[1]
            case "--print": choices.print = value() == "1"
            default:
                print("Непознат аргумент: \(args[i])"); return 2
            }
            i += 1
        }
        if uninstall {
            removeEverything()
            print("Деинсталирано.")
            return 0
        }
        let known = Set(topics.map { $0.id })
        choices.topics = choices.topics.filter { known.contains($0) }
        if choices.topics.isEmpty { print("Няма избрани теми (--topics)."); return 2 }
        if let error = installSteps(choices) {
            print("ГРЕШКА: " + error)
            return 1
        }
        print(wasInstalled ? "Настройките са записани." : "Инсталирано.")
        return 0
    }

    @objc func uninstall() {
        let a = NSAlert()
        a.messageText = "Да деинсталирам ли „Сутрешен вестник“?"
        a.informativeText = "Спира ежедневното пускане и изтрива програмата, настройките и старите броеве в нея. Папката с броевете на Desktop остава."
        a.alertStyle = .warning
        a.addButton(withTitle: "Деинсталирай")
        a.addButton(withTitle: "Отказ")
        guard a.runModal() == .alertFirstButtonReturn else { return }
        removeEverything()
        let done = NSAlert()
        done.messageText = "„Сутрешен вестник“ е деинсталиран."
        done.runModal()
        NSApp.terminate(nil)
    }
}

// ---------- Приложението ----------

class AppDelegate: NSObject, NSApplicationDelegate {
    var wizard: Wizard?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let args = Array(CommandLine.arguments.dropFirst())
        if args.contains("--silent") {
            NSApp.setActivationPolicy(.prohibited)
            setvbuf(stdout, nil, _IOLBF, 0)   // редовете излизат веднага в лога на проверката
            exit(Wizard(silent: true).runSilent(args))
        }
        buildMenu()
        wizard = Wizard()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }

    // Меню с „Изход“ (⌘Q) и „Редактиране“ (⌘C / ⌘V в полето за град)
    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Изход", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Редактиране")
        edit.addItem(withTitle: "Изрежи", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Копирай", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Постави", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Избери всичко", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
