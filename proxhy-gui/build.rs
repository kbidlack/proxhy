use std::path::PathBuf;
use std::{env, fs};

fn main() {
    let src = if let Ok(p) = env::var("PYAPP_BINARY_PATH") {
        PathBuf::from(p)
    } else {
        PathBuf::from("../pyapp-src/target/release/pyapp")
    };

    // Write directly into src/ so main.rs can include it with a normal path
    let dest = PathBuf::from("src/proxhy_inner");
    if src.exists() {
        fs::copy(&src, &dest).expect("Failed to copy pyapp binary");
        println!("cargo:rerun-if-changed={}", src.display());
    } else {
        fs::write(&dest, b"").unwrap();
        eprintln!("cargo:warning=pyapp binary not found; GUI will not be functional");
    }
}
