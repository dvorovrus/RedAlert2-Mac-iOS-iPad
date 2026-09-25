import UIKit
import WebKit

final class GameViewController: UIViewController, WKNavigationDelegate {
    private enum LaunchMode {
        case redAlert2
        case yurisRevenge
        case scorchedEarth

        var title: String {
            switch self {
            case .redAlert2: return "Red Alert 2"
            case .yurisRevenge: return "Yuri's Revenge"
            case .scorchedEarth: return "Scorched Earth"
            }
        }

        var subtitle: String {
            switch self {
            case .redAlert2: return "Classic RA2"
            case .yurisRevenge: return "Expansion"
            case .scorchedEarth: return "RA2 Mod"
            }
        }

        var engine: String {
            switch self {
            case .redAlert2, .scorchedEarth: return "ra2"
            case .yurisRevenge: return "yr"
            }
        }

        var modId: String? {
            switch self {
            case .scorchedEarth: return "scorched-earth"
            case .redAlert2, .yurisRevenge: return nil
            }
        }
    }

    private var webView: WKWebView!
    private var launcherView: UIView?
    private var activeLaunchMode: LaunchMode?
    private var contentProcessCrashCount = 0
    /// Monotonic clock, so a device-clock change cannot confuse the loop check.
    private var lastCrashTime: CFTimeInterval = 0
    private var crashNotice: UILabel?
    private var thermalObserver: NSObjectProtocol?
    private var lowPowerObserver: NSObjectProtocol?

    /// A jetsam kill during the 750MB first-launch seed is deterministic, so an
    /// uncapped reload is an infinite zero-progress loop. Retry a few times
    /// with backoff, then stop and say so.
    private static let maxAutoRecoveries = 3
    /// A crash this long after the previous one is a fresh incident, not a loop.
    private static let crashLoopWindow: CFTimeInterval = 300

    override var prefersHomeIndicatorAutoHidden: Bool { true }
    override var prefersStatusBarHidden: Bool { true }
    override var preferredScreenEdgesDeferringSystemGestures: UIRectEdge { .all }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        showLauncher()
    }

    private func showLauncher() {
        launcherView?.removeFromSuperview()

        let container = UIView()
        container.translatesAutoresizingMaskIntoConstraints = false
        container.backgroundColor = UIColor(red: 0.035, green: 0.035, blue: 0.04, alpha: 1.0)
        view.addSubview(container)
        NSLayoutConstraint.activate([
            container.topAnchor.constraint(equalTo: view.topAnchor),
            container.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            container.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            container.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
        launcherView = container

        let eyebrow = UILabel()
        eyebrow.text = "COMMAND & CONQUER"
        eyebrow.textColor = UIColor(white: 0.58, alpha: 1)
        eyebrow.font = .systemFont(ofSize: 13, weight: .semibold)
        eyebrow.textAlignment = .center

        let title = UILabel()
        title.text = "RED ALERT 2"
        title.textColor = .white
        title.font = .systemFont(ofSize: 34, weight: .black)
        title.textAlignment = .center

        let subtitle = UILabel()
        subtitle.text = "Choose game"
        subtitle.textColor = UIColor(white: 0.68, alpha: 1)
        subtitle.font = .systemFont(ofSize: 15, weight: .regular)
        subtitle.textAlignment = .center

        let header = UIStackView(arrangedSubviews: [eyebrow, title, subtitle])
        header.axis = .vertical
        header.alignment = .fill
        header.spacing = 6

        let buttons = UIStackView()
        buttons.axis = .vertical
        buttons.alignment = .fill
        buttons.spacing = 12

        for mode in [LaunchMode.redAlert2, .yurisRevenge, .scorchedEarth] {
            buttons.addArrangedSubview(makeLauncherButton(for: mode))
        }

        let footnote = UILabel()
        footnote.text = "One app · one sideload slot"
        footnote.textColor = UIColor(white: 0.42, alpha: 1)
        footnote.font = .systemFont(ofSize: 12, weight: .regular)
        footnote.textAlignment = .center

        let stack = UIStackView(arrangedSubviews: [header, buttons, footnote])
        stack.axis = .vertical
        stack.alignment = .fill
        stack.spacing = 24
        stack.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(stack)

        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: container.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: container.centerYAnchor),
            stack.widthAnchor.constraint(equalTo: container.widthAnchor, multiplier: 0.48),
            stack.widthAnchor.constraint(lessThanOrEqualToConstant: 520),
        ])
    }

    private func makeLauncherButton(for mode: LaunchMode) -> UIButton {
        var config = UIButton.Configuration.filled()
        config.title = mode.title
        config.subtitle = mode.subtitle
        config.baseForegroundColor = .white
        config.baseBackgroundColor = UIColor(red: 0.44, green: 0.06, blue: 0.07, alpha: 1.0)
        config.cornerStyle = .medium
        config.contentInsets = NSDirectionalEdgeInsets(top: 14, leading: 18, bottom: 14, trailing: 18)
        config.titleTextAttributesTransformer = UIConfigurationTextAttributesTransformer { incoming in
            var outgoing = incoming
            outgoing.font = .systemFont(ofSize: 18, weight: .bold)
            return outgoing
        }
        config.subtitleTextAttributesTransformer = UIConfigurationTextAttributesTransformer { incoming in
            var outgoing = incoming
            outgoing.font = .systemFont(ofSize: 12, weight: .medium)
            outgoing.foregroundColor = UIColor(white: 0.82, alpha: 1)
            return outgoing
        }

        let button = UIButton(configuration: config, primaryAction: UIAction { [weak self] _ in
            self?.startGame(mode)
        })
        button.heightAnchor.constraint(greaterThanOrEqualToConstant: 64).isActive = true
        return button
    }

    private func startGame(_ mode: LaunchMode) {
        activeLaunchMode = mode
        contentProcessCrashCount = 0
        crashNotice?.removeFromSuperview()
        crashNotice = nil
        launcherView?.removeFromSuperview()
        launcherView = nil

        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(BundleSchemeHandler(), forURLScheme: BundleSchemeHandler.scheme)
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.preferences.isElementFullscreenEnabled = true

        // Marker the web app uses to detect it is running inside the native shell.
        let bootstrap = WKUserScript(
            source: """
            window.__RA2_SHELL__ = { platform: 'ios', version: '0.2.0', \
            thermalState: '\(Self.thermalStateName(ProcessInfo.processInfo.thermalState))' };
            """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        config.userContentController.addUserScript(bootstrap)

        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.isOpaque = true
        webView.backgroundColor = .black
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.scrollView.pinchGestureRecognizer?.isEnabled = false
        #if DEBUG
        if #available(iOS 16.4, *) {
            webView.isInspectable = true
        }
        #endif

        view.insertSubview(webView, at: 0)
        webView.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: view.topAnchor),
            webView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])

        observeThermalState()
        loadApp()
    }

    private static func thermalStateName(_ state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }

    /// Fires only on thermal / power-mode transitions — a handful of times per
    /// hour at worst — so it adds no polling and no wakeup source of its own.
    private func observeThermalState() {
        guard thermalObserver == nil, lowPowerObserver == nil else { return }

        let center = NotificationCenter.default
        thermalObserver = center.addObserver(
            forName: ProcessInfo.thermalStateDidChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.pushThermalState()
        }
        lowPowerObserver = center.addObserver(
            forName: .NSProcessInfoPowerStateDidChange,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.pushThermalState()
        }
    }

    /// The document-start script carries the state as of viewDidLoad, so a later
    /// reload (crash recovery, or the post-seed reload) would otherwise see a
    /// stale — and optimistically low — value: no transition fires at reload time.
    private func pushThermalState() {
        guard webView != nil else { return }

        let info = ProcessInfo.processInfo
        let name = Self.thermalStateName(info.thermalState)
        let lowPower = info.isLowPowerModeEnabled
        NSLog("[RA2] thermalState=%@ lowPower=%@", name, lowPower ? "yes" : "no")
        webView.evaluateJavaScript(
            """
            window.__RA2_SHELL__ && (window.__RA2_SHELL__.thermalState = '\(name)');
            window.__RA2_POWER__ && window.__RA2_POWER__({thermal:'\(name)',lowPower:\(lowPower)});
            """,
            completionHandler: nil
        )
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        pushThermalState()
    }

    deinit {
        let center = NotificationCenter.default
        if let thermalObserver { center.removeObserver(thermalObserver) }
        if let lowPowerObserver { center.removeObserver(lowPowerObserver) }
    }

    private func loadApp(crashed: Bool = false) {
        guard let mode = activeLaunchMode else {
            showLauncher()
            return
        }

        var components = URLComponents()
        components.scheme = BundleSchemeHandler.scheme
        components.host = "app"
        components.path = "/index.html"

        var queryItems = [
            URLQueryItem(name: "engine", value: mode.engine),
        ]
        if let modId = mode.modId {
            queryItems.append(URLQueryItem(name: "mod", value: modId))
        }
        if crashed {
            queryItems.append(
                URLQueryItem(name: "crashRecovery", value: String(contentProcessCrashCount))
            )
        }
        components.queryItems = queryItems

        guard let url = components.url else {
            NSLog("[RA2] Failed to construct launcher URL for %@", mode.title)
            return
        }
        NSLog("[RA2] Launching %@: %@", mode.title, url.absoluteString)
        webView.load(URLRequest(url: url))
    }

    // The web content process was killed (almost always jetsam memory pressure
    // during game load). Without this handler the view goes blank/limbo; with a
    // plain reload the user silently loses their session.
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        let now = CACurrentMediaTime()
        if now - lastCrashTime > Self.crashLoopWindow { contentProcessCrashCount = 0 }
        lastCrashTime = now
        contentProcessCrashCount += 1
        NSLog("[RA2] Web content process terminated (count=%d)", contentProcessCrashCount)

        guard contentProcessCrashCount <= Self.maxAutoRecoveries else {
            NSLog("[RA2] Giving up after %d consecutive terminations", contentProcessCrashCount)
            showUnrecoverableNotice()
            return
        }

        let delay = pow(2.0, Double(contentProcessCrashCount - 1))
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.loadApp(crashed: true)
        }
    }

    private func showUnrecoverableNotice() {
        guard crashNotice == nil else { return }
        let label = UILabel()
        label.numberOfLines = 0
        label.textAlignment = .center
        label.textColor = .white
        label.font = .monospacedSystemFont(ofSize: 15, weight: .regular)
        label.text = """
        Red Alert 2 ran out of memory and could not recover.

        Close other apps, restart the device, and launch again.
        """
        label.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(label)
        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            label.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            label.widthAnchor.constraint(lessThanOrEqualTo: view.widthAnchor, multiplier: 0.8),
        ])
        crashNotice = label
    }
}
