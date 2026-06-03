use std::path::PathBuf;
use std::{env, fs};

fn main() {
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let dest = out_dir.join("proxhy-inner");

    // In CI, PYAPP_BINARY_PATH is set by the workflow.
    // Locally, fall back to the expected cargo output path.
    let src = if let Ok(p) = env::var("PYAPP_BINARY_PATH") {
        PathBuf::from(p)
    } else {
        // Adjust this path to wherever you build pyapp locally
        PathBuf::from("../pyapp-src/target/release/pyapp")
    };

    if src.exists() {
        fs::copy(&src, &dest).expect("Failed to copy pyapp binary");
        // Tell cargo to re-run this script if the source binary changes
        println!("cargo:rerun-if-changed={}", src.display());
    } else {
        // Create a placeholder so the build doesn't fail when pyapp
        // isn't built yet. The resulting GUI won't be functional but
        // it will compile.
        fs::write(&dest, b"").unwrap();
        eprintln!(
            "cargo:warning=pyapp binary not found at {}; GUI will not be functional",
            src.display()
        );
    }
}
