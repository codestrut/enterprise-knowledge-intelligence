from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SECTION = re.compile(r"^===== (.*?) =====\s*$", re.M)
META = re.compile(r"^(START|END|DURATION_SECONDS|EXIT_CODE)=(.*)$", re.M)

SCENARIOS = {
    "B-01": "platform tenant directory loads synthetic lifecycle states through the loopback proxy",
    "B-02": "platform operator can create a pending registration, search a user, and assign a role",
    "B-03": "platform operator can approve, recover, and retry without activating tenants",
}

ENV_KEYS = (
    "ENVIRONMENT_RESULT", "ENVIRONMENT_EXIT_CODE", "NODE_ENGINE_COMPATIBILITY",
    "PLAYWRIGHT_CLI", "PLAYWRIGHT_BROWSER_CACHE", "PORT_5174", "PORT_8003",
    "REPORT_SAVED",
)


def clean(value: str) -> str:
    return ANSI.sub("", value).replace("\r", "")


def parse_sections(log: str) -> list[dict]:
    matches = list(SECTION.finditer(log))
    result = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(log)
        block = log[match.end():end]
        fields = {key: value.strip() for key, value in META.findall(block)}
        command_match = re.search(r"^COMMAND=(.*)$", block, re.M)
        output = re.sub(r"^(START|END|DURATION_SECONDS|EXIT_CODE|COMMAND)=.*$", "", block, flags=re.M)
        result.append({
            "label": match.group(1).strip(),
            "fields": fields,
            "command": command_match.group(1).strip() if command_match else "NOT CAPTURED",
            "output": clean(output).strip(),
        })
    return result


def field(section: dict | None, name: str, default: str = "NOT CAPTURED") -> str:
    return section.get("fields", {}).get(name, default) if section else default


def status(section: dict | None) -> str:
    if section is None:
        return "NOT CAPTURED"
    code = field(section, "EXIT_CODE")
    if code == "0":
        return "PASS"
    if code == "2":
        return "BLOCKED"
    if code.isdigit():
        return "FAIL"
    return "NOT CAPTURED"


def find_section(sections: list[dict], *needles: str) -> dict | None:
    found = [
        item for item in sections
        if all(needle.lower() in item["label"].lower() for needle in needles)
    ]
    return found[-1] if found else None


def parse_scenario(output: str, phrase: str) -> str:
    for line in output.splitlines():
        if phrase.lower() not in line.lower():
            continue
        if re.search(r"[✓✔]", line):
            return "PASS"
        if re.search(r"[✘×]", line):
            return "FAIL"
        if re.search(r"(?:^|\s)(?:-|○|skipped)(?:\s|$)", line, re.I):
            return "SKIPPED"
        if re.search(r"\bpassed\b", line, re.I):
            return "PASS"
        if re.search(r"\bfailed\b", line, re.I):
            return "FAIL"
    return "NOT PARSED"


def parse_summary_line(output: str) -> str:
    for line in reversed(output.splitlines()):
        if re.search(r"\b\d+\s+(?:passed|failed|skipped)\b", line, re.I):
            return line.strip()
    return "NOT CAPTURED"


def locate_environment_report(run_dir: Path, log: str) -> Path | None:
    candidates: list[Path] = [run_dir / "environment-report.txt"]

    # run_dir is docs/task-06/live-runs/<run-id>; the environment report is
    # docs/task-06/environment-check-<stamp>/environment-report.txt.
    task06_dir = run_dir.parent.parent
    candidates.extend(sorted(
        task06_dir.glob("environment-check-*/environment-report.txt"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ))

    # Also honor an explicit REPORT_SAVED path in the run log, if present.
    for raw in re.findall(r"^REPORT_SAVED=(.*)$", log, re.M):
        raw = raw.strip()
        if raw:
            path = Path(raw).expanduser()
            candidates.insert(0, path if path.is_absolute() else run_dir / path)

    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def read_environment(path: Path | None) -> tuple[dict, str]:
    """Parse both machine-readable fields and the sectioned environment-check report."""
    if path is None:
        return {}, "NOT CAPTURED"

    content = clean(path.read_text(errors="replace"))
    values: dict[str, str] = {}

    # Support KEY=value reports when a future checker emits them.
    for key in ENV_KEYS:
        matches = re.findall(rf"^{re.escape(key)}=(.*)$", content, re.M)
        if matches:
            values[key] = matches[-1].strip()

    def capture(pattern: str, default: str = "NOT CAPTURED") -> str:
        match = re.search(pattern, content, re.I | re.M)
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else default

    # This checker emits a human-readable, sectioned report rather than KEY=value.
    details = {
        "OS": capture(r"^\s*ProductName:\s*(.+)$"),
        "OS_VERSION": capture(r"^\s*ProductVersion:\s*(.+)$"),
        "GIT": capture(r"^\s*git version\s+(.+)$"),
        "NODE": capture(r"^\s*(v\d+\.\d+\.\d+)\s*$"),
        "NPM": capture(r"^\s*(\d+\.\d+\.\d+)\s*$"),
        "PYTHON": capture(r"^\s*Python\s+(\d+\.\d+\.\d+)\s*$"),
        "PLAYWRIGHT_CLI": capture(r"^\s*Version\s+(\d+\.\d+\.\d+)\s*$"),
        "PLAYWRIGHT_BROWSER_CACHE": capture(r"^\s*(/Users/.*/ms-playwright/chromium-[^\s]+)\s*$"),
        "PYTHON_REQUIREMENTS": capture(r"^\s*(No broken requirements found\.)\s*$"),
        "PORT_5174": capture(r"^\s*\[OK\]\s+Port 5174 is (free|in use)\s*$"),
        "PORT_8003": capture(r"^\s*\[OK\]\s+Port 8003 is (free|in use)\s*$"),
        "BACKEND_DIRECTORY_REVIEW": capture(r"^\s*\[REVIEW\]\s+(.+)$"),
    }

    # Avoid confusing the npm version line with Node or pip versions by anchoring
    # extraction to the tool's section and executable markers.
    node_block = re.search(
        r"\[OK\]\s+node:.*?\n\s*(v\d+\.\d+\.\d+)", content, re.S
    )
    npm_block = re.search(
        r"\[OK\]\s+npm:.*?\n\s*(\d+\.\d+\.\d+)", content, re.S
    )
    if node_block:
        details["NODE"] = node_block.group(1)
    if npm_block:
        details["NPM"] = npm_block.group(1)

    # Use the first Python version reported by the selected virtual environment.
    python_block = re.search(
        r"\[OK\]\s+python3:.*?\n\s*Python\s+(\d+\.\d+\.\d+)", content, re.S
    )
    if python_block:
        details["PYTHON"] = python_block.group(1)

    # Keep only meaningful, actually observed values.
    for key, value in details.items():
        if value != "NOT CAPTURED":
            values[key] = value

    # The report has no overall exit-code field. Derive a readiness label only
    # from explicit report markers; do not fabricate an exit code.
    has_failure = bool(re.search(r"^\s*\[(?:FAIL|BLOCKED)\]", content, re.I | re.M))
    has_review = bool(re.search(r"^\s*\[REVIEW\]", content, re.I | re.M))
    if "ENVIRONMENT_RESULT" not in values:
        if has_failure:
            values["ENVIRONMENT_RESULT"] = "FAIL"
        elif has_review:
            values["ENVIRONMENT_RESULT"] = "PASS WITH REVIEW"
        elif "[OK]" in content:
            values["ENVIRONMENT_RESULT"] = "PASS"
        else:
            values["ENVIRONMENT_RESULT"] = "NOT CAPTURED"

    values.setdefault("ENVIRONMENT_EXIT_CODE", "NOT RECORDED")
    return values, content


def compact_output(value: str, max_lines: int = 18) -> str:
    rows = [line.rstrip() for line in value.splitlines() if line.strip()]
    if len(rows) > max_lines:
        rows = rows[:max_lines] + [f"... {len(rows) - max_lines} more lines; see terminal.log"]
    return "\n".join(rows) if rows else "(no captured output)"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate chronological EKIP Task 06 live-run results.")
    parser.add_argument("--run-dir", default=os.environ.get("TASK06_RUN_DIR"))
    args = parser.parse_args()
    if not args.run_dir:
        parser.error("pass --run-dir or set TASK06_RUN_DIR")

    run_dir = Path(args.run_dir).expanduser().resolve()
    log_path = run_dir / "terminal.log"
    if not log_path.is_file():
        raise SystemExit(f"BLOCKED: terminal.log not found: {log_path}")

    log = clean(log_path.read_text(errors="replace"))
    sections = parse_sections(log)
    env_path = locate_environment_report(run_dir, log)
    env, _ = read_environment(env_path)

    stages = [
        ("01 REPOSITORY IDENTITY", ("repository identity",)),
        ("02 MOCK API SYNTAX", ("python mock api syntax",)),
        ("03 PYTEST INVENTORY", ("pytest inventory",)),
        ("04 PYTEST COLLECTION", ("pytest collection",)),
        ("05 PYTEST BASELINE EXECUTION", ("pytest execution",)),
        ("06 ENVIRONMENT PREFLIGHT", ("environment preflight",)),
        ("07 PLAYWRIGHT DISCOVERY", ("browser-smoke discovery",)),
        ("08 PLAYWRIGHT SMOKE EXECUTION", ("all three task 06 browser smoke tests",)),
        ("10 POST-RUN VERIFICATION", ("post-run git status",)),
    ]

    chosen = []
    for title, needles in stages:
        section = find_section(sections, *needles)
        if section is None and title == "04 PYTEST COLLECTION":
            section = find_section(sections, "pytest", "collection")
        if section is None and title == "05 PYTEST BASELINE EXECUTION":
            section = find_section(sections, "pytest", "execution")
        chosen.append((title, section))

    browser = find_section(sections, "all three task 06 browser smoke tests")
    discovery = find_section(sections, "browser-smoke discovery")
    targeted = [s for s in sections if "targeted" in s["label"].lower() or "retest" in s["label"].lower()]
    browser_output = browser["output"] if browser else ""
    initial = {key: parse_scenario(browser_output, phrase) for key, phrase in SCENARIOS.items()}
    retests = {}
    final = {}
    for key, phrase in SCENARIOS.items():
        matches = [s for s in targeted if phrase.lower() in (s["command"] + "\n" + s["output"]).lower()]
        retests[key] = parse_scenario(matches[-1]["output"], phrase) if matches else "NOT RUN"
        if initial[key] == "FAIL" and retests[key] == "PASS":
            final[key] = "PASS AFTER RETEST"
        elif retests[key] == "FAIL":
            final[key] = "FAIL ON RETEST"
        elif initial[key] == "NOT PARSED" and retests[key] == "PASS":
            final[key] = "PASS ON RETEST"
        else:
            final[key] = initial[key]

    discovered = sum(
        phrase.lower() in (discovery["output"].lower() if discovery else "")
        for phrase in SCENARIOS.values()
    )
    pytest = find_section(sections, "pytest execution") or find_section(sections, "pytest", "execution")
    pytest_summary = parse_summary_line(pytest["output"]) if pytest else "NOT CAPTURED"
    playwright_summary = parse_summary_line(browser_output) if browser else "NOT CAPTURED"

    env_result = env.get("ENVIRONMENT_RESULT", "NOT CAPTURED")
    env_exit = env.get("ENVIRONMENT_EXIT_CODE", "NOT CAPTURED")
    env_detail_keys = (
        "OS", "OS_VERSION", "GIT", "NODE", "NPM", "PYTHON",
        "PLAYWRIGHT_CLI", "PLAYWRIGHT_BROWSER_CACHE",
        "PYTHON_REQUIREMENTS", "PORT_5174", "PORT_8003",
        "BACKEND_DIRECTORY_REVIEW",
    )
    env_details = [f"{key}={env[key]}" for key in env_detail_keys if key in env]

    lines = [
        "# EKIP Task 06 — Live terminal summary", "",
        f"RUN DIRECTORY: `{run_dir}`",
        f"TERMINAL LOG: `{log_path}`",
        f"ENVIRONMENT REPORT: `{env_path}`" if env_path else "ENVIRONMENT REPORT: NOT CAPTURED",
        "",
    ]

    for title, section in chosen:
        lines += [f"## {title}", ""]
        if section is None:
            lines += ["STATUS: NOT CAPTURED", ""]
            continue
        lines += [
            f"COMMAND: `{section['command']}`",
            f"STATUS: {status(section)}",
            f"EXIT CODE: {field(section, 'EXIT_CODE')}",
            f"DURATION: {field(section, 'DURATION_SECONDS')} seconds",
            "OUTPUT:", "```text", compact_output(section["output"]), "```", "",
        ]

    lines += ["## 09 FIXES AND TARGETED RETESTS", ""]
    if not targeted:
        lines += ["STATUS: NO TARGETED RETESTS RECORDED", ""]
    else:
        for section in targeted:
            lines += [
                f"### {section['label']}",
                f"COMMAND: `{section['command']}`",
                f"STATUS: {status(section)}",
                f"EXIT CODE: {field(section, 'EXIT_CODE')}",
                f"DURATION: {field(section, 'DURATION_SECONDS')} seconds",
                "OUTPUT:", "```text", compact_output(section["output"]), "```", "",
            ]

    lines += ["## ENVIRONMENT REPORT", "", f"RESULT: {env_result}", f"EXIT CODE: {env_exit}"]
    lines.extend(env_details or ["DETAILS: See the environment report file."])
    lines += ["", "## BROWSER SCENARIO RESULTS", ""]
    for key in SCENARIOS:
        lines.append(f"{key}: {final[key]} (initial: {initial[key]}; retest: {retests[key]})")
    lines += [
        f"DISCOVERED: {discovered}/3",
        f"PYTEST: {pytest_summary}",
        f"PLAYWRIGHT: {playwright_summary}", "",
    ]

    baseline_sections = [
        find_section(sections, "python mock api syntax"),
        find_section(sections, "pytest inventory"),
        find_section(sections, "pytest collection") or find_section(sections, "pytest", "collection"),
        pytest,
    ]
    baseline_ok = all(status(item) == "PASS" for item in baseline_sections)
    browser_ok = (
        browser is not None and status(browser) == "PASS" and discovered == 3
        and all(value in ("PASS", "PASS AFTER RETEST", "PASS ON RETEST") for value in final.values())
    )
    environment_ok = env_result.upper().startswith(("READY", "PASS"))
    post = find_section(sections, "post-run git status")
    post_ok = status(post) == "PASS"

    if any(value.startswith("FAIL") for value in final.values()) or status(browser) == "FAIL":
        readiness = "FAIL"
    elif status(browser) == "BLOCKED":
        readiness = "BLOCKED"
    elif baseline_ok and browser_ok and environment_ok and post_ok:
        readiness = "PASS — ISOLATED MOCK-BACKED BROWSER SMOKE"
    elif browser_ok and baseline_ok:
        readiness = "PASS WITH ENVIRONMENT/POST-RUN REVIEW"
    else:
        readiness = "INCOMPLETE — REVIEW CAPTURED STAGES"

    lines += ["## FINAL READINESS", "", f"RESULT: {readiness}", ""]
    output_path = run_dir / "live-summary.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"SUMMARY_SAVED={output_path}")
    for key in SCENARIOS:
        print(f"{key}={final[key]}")
    print(f"PYTEST={pytest_summary}")
    print(f"PLAYWRIGHT={playwright_summary}")
    print(f"ENVIRONMENT={env_result}")
    print(f"ENVIRONMENT_REPORT={env_path or 'NOT FOUND'}")
    print(f"FINAL_READINESS={readiness}")


if __name__ == "__main__":
    main()
