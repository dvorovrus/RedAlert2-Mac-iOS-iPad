import UIKit
import WebKit

final class GameViewController: UIViewController, WKNavigationDelegate {
    private var webView: WKWebView!
    private var lastRecoverableURL: URL?
    private var contentProcessCrashCount = 0
    /// Monotonic clock, so a device-clock change cannot confuse the loop check.
    private var lastCrashTime: CFTimeInterval = 0
    private var crashNotice: UILabel?
    private var thermalObserver: NSObjectProtocol?
    private var lowPowerObserver: NSObjectProtocol?

    /// A jetsam kill during the large first-launch seed is deterministic, so an
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
        configureWebView()
        observeThermalState()
        loadLauncher()
    }

    private func configureWebView() {
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(BundleSchemeHandler(), forURLScheme: BundleSchemeHandler.scheme)
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.preferences.isElementFullscreenEnabled = true

        // Marker the web app uses to detect it is running inside the native shell.
        let bootstrap = WKUserScript(
            source: """
            window.__RA2_SHELL__ = { platform: 'ios', version: '0.3.0', \
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

        view.addSubview(webView)
        webView.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: view.topAnchor),
            webView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
    }

    private func loadLauncher() {
        guard let url = URL(string: "\(BundleSchemeHandler.scheme)://app/launcher.html") else {
            return
        }
        lastRecoverableURL = url
        webView.load(URLRequest(url: url))
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

    private func pushThermalState() {
        let info = ProcessInfo.processInfo
        let name = Self.thermalStateName(info.thermalState)
        let lowPower = info.isLowPowerModeEnabled

        webView.evaluateJavaScript(
            """
            window.__RA2_SHELL__ && (window.__RA2_SHELL__.thermalState = '\(name)');
            window.__RA2_POWER__ && window.__RA2_POWER__({thermal:'\(name)',lowPower:\(lowPower)});
            """,
            completionHandler: nil
        )
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let url = webView.url {
            lastRecoverableURL = url
            NSLog("[RA2] Loaded %@", url.absoluteString)
        }
        pushThermalState()
    }

    deinit {
        let center = NotificationCenter.default
        if let thermalObserver { center.removeObserver(thermalObserver) }
        if let lowPowerObserver { center.removeObserver(lowPowerObserver) }
    }

    private func recoveryURL() -> URL? {
        guard let current = lastRecoverableURL else {
            return URL(string: "\(BundleSchemeHandler.scheme)://app/launcher.html")
        }

        guard current.path.hasSuffix("/index.html") else {
            return current
        }

        guard var parts = URLComponents(url: current, resolvingAgainstBaseURL: false) else {
            return current
        }

        var items = parts.queryItems ?? []
        items.removeAll { $0.name == "crashRecovery" }
        items.append(URLQueryItem(name: "crashRecovery", value: String(contentProcessCrashCount)))
        parts.queryItems = items
        return parts.url ?? current
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        let now = CACurrentMediaTime()
        if now - lastCrashTime > Self.crashLoopWindow {
            contentProcessCrashCount = 0
        }
        lastCrashTime = now
        contentProcessCrashCount += 1

        NSLog("[RA2] Web content process terminated (count=%d)", contentProcessCrashCount)

        guard contentProcessCrashCount <= Self.maxAutoRecoveries else {
            showUnrecoverableNotice()
            return
        }

        let delay = pow(2.0, Double(contentProcessCrashCount - 1))
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self, let url = self.recoveryURL() else { return }
            self.webView.load(URLRequest(url: url))
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
