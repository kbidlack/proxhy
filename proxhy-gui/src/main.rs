#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

use eframe::egui;
use std::collections::VecDeque;
use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;

const MAX_LOG_LINES: usize = 1000;

#[derive(Clone, Debug, PartialEq)]
enum LogLevel {
    Info,
    Warn,
    Error,
    Debug,
    Trace,
    Gui,
    Unknown,
}

#[derive(Clone, Debug)]
struct LogLine {
    level: LogLevel,
    text: String,
}

// Embedded pyapp binary (baked in at compile time)
const PYAPP_BYTES: &[u8] = include_bytes!("proxhy_inner");

#[derive(Default, Clone)]
struct UpdateState {
    available: Option<String>, // Some("v1.2.3") if update found
    installing: bool,
    error: Option<String>,
}

// Call this once from main(), before eframe::run_native
fn spawn_update_check(update_state: Arc<Mutex<UpdateState>>) {
    std::thread::spawn(move || {
        let result = self_update::backends::github::Update::configure()
            .repo_owner("kbidlack")
            .repo_name("proxhy")
            .bin_name("proxhy-gui")
            .current_version(env!("CARGO_PKG_VERSION"))
            .no_confirm(true)
            .build();

        match result {
            Ok(updater) => {
                // Just check — don't update yet
                match updater.get_latest_release() {
                    Ok(release) if release.version != env!("CARGO_PKG_VERSION") => {
                        let mut s = update_state.lock().unwrap();
                        s.available = Some(release.version);
                    }
                    _ => {}
                }
            }
            Err(e) => {
                let mut s = update_state.lock().unwrap();
                s.error = Some(e.to_string());
            }
        }
    });
}

fn apply_update(update_state: Arc<Mutex<UpdateState>>) {
    std::thread::spawn(move || {
        {
            let mut s = update_state.lock().unwrap();
            s.installing = true;
        }

        let result = self_update::backends::github::Update::configure()
            .repo_owner("kbidlack")
            .repo_name("proxhy")
            .bin_name("proxhy-gui")
            .current_version(env!("CARGO_PKG_VERSION"))
            .no_confirm(true)
            .build()
            .and_then(|u| u.update());

        let mut s = update_state.lock().unwrap();
        s.installing = false;
        match result {
            Ok(_) => s.available = None, // updated; prompt restart
            Err(e) => s.error = Some(e.to_string()),
        }
    });
}

fn extract_pyapp() -> std::path::PathBuf {
    // On macOS, the binary lives next to the GUI in the .app bundle —
    // no extraction needed, just return the sibling path.
    #[cfg(not(target_os = "windows"))]
    {
        let mut path = std::env::current_exe().unwrap();
        path.pop();
        path.push("proxhy");
        return path;
    }

    // On Windows, extract to %APPDATA%\proxhy\ so it persists between runs
    // (avoids re-extracting every launch and keeps Defender happy).
    #[cfg(target_os = "windows")]
    {
        let base = dirs::data_dir()
            .unwrap_or_else(|| std::env::temp_dir())
            .join("proxhy");
        std::fs::create_dir_all(&base).unwrap();
        let dest = base.join("proxhy.exe");

        // Only write if the file doesn't exist or is a different size
        // (cheap freshness check — good enough for our purposes).
        let needs_write = dest
            .metadata()
            .map(|m| m.len() != PYAPP_BYTES.len() as u64)
            .unwrap_or(true);

        if needs_write {
            std::fs::write(&dest, PYAPP_BYTES).expect("Failed to extract proxhy binary");
        }
        dest
    }
}

impl LogLine {
    fn parse(raw: &str) -> Self {
        // Match Python logging format: "2026-06-03 12:08:30,884 [INFO] proxhy: ..."
        // Also match plain level prefixes: "[INFO]", "[WARN]", "[ERROR]", "[DEBUG]"
        // and warnings like "CryptographyDeprecationWarning:"
        let upper = raw.to_uppercase();

        let level = if raw.starts_with("[gui]") {
            LogLevel::Gui
        } else if upper.contains("[ERROR]")
            || upper.contains("ERROR:")
            || upper.contains("EXCEPTION")
            || upper.contains("TRACEBACK")
        {
            LogLevel::Error
        } else if upper.contains("[WARN]")
            || upper.contains("WARNING:")
            || upper.contains("DEPRECATIONWARNING")
            || upper.contains("WARNING,")
        {
            LogLevel::Warn
        } else if upper.contains("[DEBUG]") {
            LogLevel::Debug
        } else if upper.contains("[TRACE]") {
            LogLevel::Trace
        } else if upper.contains("[INFO]") {
            LogLevel::Info
        } else {
            LogLevel::Unknown
        };

        Self {
            level,
            text: raw.to_string(),
        }
    }

    fn color(&self) -> egui::Color32 {
        match self.level {
            LogLevel::Error => egui::Color32::from_rgb(255, 85, 85),
            LogLevel::Warn => egui::Color32::from_rgb(255, 184, 76),
            LogLevel::Info => egui::Color32::from_rgb(100, 220, 140),
            LogLevel::Debug => egui::Color32::from_rgb(130, 160, 255),
            LogLevel::Trace => egui::Color32::from_rgb(160, 130, 200),
            LogLevel::Gui => egui::Color32::from_rgb(100, 160, 255),
            LogLevel::Unknown => egui::Color32::from_rgb(180, 180, 180),
        }
    }

    fn badge_text(&self) -> Option<&'static str> {
        match self.level {
            LogLevel::Error => Some("ERR"),
            LogLevel::Warn => Some("WRN"),
            LogLevel::Info => Some("INF"),
            LogLevel::Debug => Some("DBG"),
            LogLevel::Trace => Some("TRC"),
            LogLevel::Gui => Some("GUI"),
            LogLevel::Unknown => None,
        }
    }
}

fn push_line(log: &Arc<Mutex<VecDeque<LogLine>>>, raw: &str) {
    let mut l = log.lock().unwrap();
    if l.len() >= MAX_LOG_LINES {
        l.pop_front();
    }
    l.push_back(LogLine::parse(raw));
}

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Proxhy")
            .with_inner_size([800.0, 500.0]),
        ..Default::default()
    };
    eframe::run_native(
        "Proxhy",
        options,
        Box::new(|_cc| Ok(Box::new(App::default()))),
    )
}

struct App {
    log: Arc<Mutex<VecDeque<LogLine>>>,
    child: Option<Child>,
    running: bool,
    auto_scroll: bool,
    filter: LogFilter,
    update_state: Arc<Mutex<UpdateState>>,
}

#[derive(PartialEq, Clone, Copy)]
enum LogFilter {
    All,
    InfoAndAbove,
    WarnAndAbove,
    ErrorOnly,
}

impl Default for App {
    fn default() -> Self {
        Self {
            log: Arc::new(Mutex::new(VecDeque::with_capacity(MAX_LOG_LINES))),
            child: None,
            running: false,
            auto_scroll: true,
            filter: LogFilter::All,
            update_state: Arc::new(Mutex::new(UpdateState::default())),
        }
    }
}

impl App {
    fn start(&mut self) {
        let binary = extract_pyapp();

        push_line(
            &self.log,
            &format!("[gui] Starting {}...", binary.display()),
        );

        match Command::new(&binary)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(mut child) => {
                self.running = true;

                // stdout
                if let Some(stdout) = child.stdout.take() {
                    let log = Arc::clone(&self.log);
                    thread::spawn(move || {
                        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                            push_line(&log, &line);
                        }
                    });
                }

                // stderr — NOT treated as errors; proxhy's logger writes to stderr
                if let Some(stderr) = child.stderr.take() {
                    let log = Arc::clone(&self.log);
                    thread::spawn(move || {
                        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                            push_line(&log, &line);
                        }
                    });
                }

                self.child = Some(child);
            }
            Err(e) => {
                push_line(&self.log, &format!("[gui] Failed to start proxhy: {e}"));
            }
        }
    }

    fn stop(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        self.running = false;
        push_line(&self.log, "[gui] Stopped.");
    }

    fn line_passes_filter(&self, line: &LogLine) -> bool {
        match self.filter {
            LogFilter::All => true,
            LogFilter::InfoAndAbove => !matches!(
                line.level,
                LogLevel::Debug | LogLevel::Trace | LogLevel::Unknown
            ),
            LogFilter::WarnAndAbove => {
                matches!(line.level, LogLevel::Warn | LogLevel::Error | LogLevel::Gui)
            }
            LogFilter::ErrorOnly => matches!(line.level, LogLevel::Error),
        }
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Poll child exit
        if self.running {
            if let Some(child) = &mut self.child {
                if let Ok(Some(status)) = child.try_wait() {
                    self.running = false;
                    push_line(&self.log, &format!("[gui] Process exited ({status})"));
                    self.child = None;
                }
            }
            ctx.request_repaint_after(std::time::Duration::from_millis(100));
        }

        // Toolbar
        let update_state = self.update_state.lock().unwrap().clone();
        if let Some(ref version) = update_state.available {
            egui::TopBottomPanel::top("update_banner").show(ctx, |ui| {
                ui.horizontal(|ui| {
                    ui.colored_label(
                        egui::Color32::from_rgb(255, 200, 50),
                        format!("⬆ Update available: {}", version),
                    );
                    if update_state.installing {
                        ui.spinner();
                        ui.label("Installing...");
                    } else if ui.button("Update & Restart").clicked() {
                        let state = Arc::clone(&self.update_state);
                        apply_update(state);
                    }
                    if let Some(ref err) = update_state.error {
                        ui.colored_label(egui::Color32::RED, err);
                    }
                });
            });
        }
        egui::TopBottomPanel::top("controls")
            .min_height(40.0)
            .show(ctx, |ui| {
                ui.horizontal_centered(|ui| {
                    ui.heading("Proxhy");
                    ui.separator();

                    if self.running {
                        if ui.button("⏹ Stop").clicked() {
                            self.stop();
                        }
                        ui.colored_label(egui::Color32::from_rgb(100, 220, 140), "● Running");
                    } else {
                        if ui.button("▶ Start").clicked() {
                            self.start();
                        }
                        ui.colored_label(egui::Color32::GRAY, "● Stopped");
                    }

                    ui.separator();

                    // Filter buttons
                    ui.label("Filter:");
                    ui.selectable_value(&mut self.filter, LogFilter::All, "All");
                    ui.selectable_value(&mut self.filter, LogFilter::InfoAndAbove, "Info+");
                    ui.selectable_value(&mut self.filter, LogFilter::WarnAndAbove, "Warn+");
                    ui.selectable_value(&mut self.filter, LogFilter::ErrorOnly, "Errors");

                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui.button("Clear").clicked() {
                            self.log.lock().unwrap().clear();
                        }
                        ui.checkbox(&mut self.auto_scroll, "Auto-scroll");
                    });
                });
            });

        // Log panel
        egui::CentralPanel::default().show(ctx, |ui| {
            let text_height = ui.text_style_height(&egui::TextStyle::Monospace);

            egui::ScrollArea::vertical()
                .auto_shrink(false)
                .stick_to_bottom(self.auto_scroll)
                .show(ui, |ui| {
                    let log = self.log.lock().unwrap();
                    for line in log.iter().filter(|l| self.line_passes_filter(l)) {
                        ui.horizontal_wrapped(|ui| {
                            ui.spacing_mut().item_spacing.x = 4.0;

                            // Colored level badge
                            if let Some(badge) = line.badge_text() {
                                let badge_color = line.color();
                                let dark_bg = egui::Color32::from_rgba_unmultiplied(
                                    badge_color.r() / 6,
                                    badge_color.g() / 6,
                                    badge_color.b() / 6,
                                    180,
                                );
                                egui::Frame::NONE
                                    .fill(dark_bg)
                                    .inner_margin(egui::Margin::symmetric(4, 1))
                                    .corner_radius(3)
                                    .show(ui, |ui| {
                                        ui.add(
                                            egui::Label::new(
                                                egui::RichText::new(badge)
                                                    .monospace()
                                                    .size(10.0)
                                                    .color(badge_color),
                                            )
                                            .selectable(false),
                                        );
                                    });
                            } else {
                                // Spacer to align unknown lines with badged ones
                                ui.add_space(30.0);
                            }

                            ui.add(
                                egui::Label::new(
                                    egui::RichText::new(&line.text)
                                        .monospace()
                                        .size(12.0)
                                        .color(line.color()),
                                )
                                .wrap(),
                            );
                        });
                        ui.add_space(1.0);
                    }

                    // Keep scroll area tall enough to scroll even when few lines
                    ui.add_space(text_height);
                });
        });
    }
}
