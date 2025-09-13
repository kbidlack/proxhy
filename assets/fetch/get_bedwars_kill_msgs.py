import argparse, json, re
from pathlib import Path

# Placeholders we'll replace with regex fragments
SENTINELS = {
    "<player1>": "\u0000P1\u0000",
    "<player2>": "\u0000P2\u0000",
    "<Color> Bed": "\u0000CLR_BED\u0000",
    "#<#>": "\u0000NUM\u0000",
}


def make_regex(line: str, mode: str) -> str:
    s = line.strip()
    if not s:
        return ""

    # Mark placeholders with sentinels so we can safely handle text
    for raw, sent in SENTINELS.items():
        s = s.replace(raw, sent)

    # We no longer escape periods or spaces at all
    # Everything stays as-is except placeholders

    # Replace placeholders with regex fragments
    if mode == "placeholder":
        replacements = {
            "\u0000P1\u0000": r".+?",
            "\u0000P2\u0000": r"{}",
            "\u0000CLR_BED\u0000": r".+? Bed",
            "\u0000NUM\u0000": r"\d+",
        }
    else:  # capture mode
        replacements = {
            "\u0000P1\u0000": r"(?P<player1>.+?)",
            "\u0000P2\u0000": r"(?P<player2>.+?)",
            "\u0000CLR_BED\u0000": r"(?P<color>.+?) Bed",
            "\u0000NUM\u0000": r"(?P<num>\d+)",
        }

    for sent, rep in replacements.items():
        s = s.replace(sent, rep)

    # Add start and end anchors
    return f"^{s}$"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_txt", type=Path, help="Path to messages.txt")
    ap.add_argument("output_json", type=Path, help="Path to output JSON")
    ap.add_argument("--mode", choices=["capture", "placeholder"], default="capture")
    args = ap.parse_args()

    lines = args.input_txt.read_text(encoding="utf-8").splitlines()

    kill_msgs, bed_msgs = [], []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        regex = make_regex(line, args.mode)
        if "<Color> Bed" in line:
            bed_msgs.append(regex)
        else:
            kill_msgs.append(regex)

    result = {"kill_messages": kill_msgs, "bed_break_messages": bed_msgs}

    args.output_json.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"Wrote {len(kill_msgs)} kill and {len(bed_msgs)} bed break regexes to {args.output_json}"
    )


if __name__ == "__main__":
    main()
