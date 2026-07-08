"""
Brightspace Assignment Grouper
===============================
Interactive, colourful recreation of "Brightspace assignment grouper.ps1".

Unzips every .zip file in a chosen folder and organizes the extracted
submissions into "<student or group name>/<assignment name>/" -- one
folder per student or group, with one subfolder inside it per assignment.
The assignment name is taken from each zip file's own name (each zip is
one assignment's bulk download).

Brightspace lets each institution customise how submission folders are
named (the d2l.Tools.Dropbox.FilenameFormat* config variables), so instead
of assuming one fixed format, this tool looks at a real folder name from
your zips and asks you which part is the student/group name. It
remembers your answer for next time.

Run with:  python "Brightspace assignment grouper.py"
"""

import os
import re
import sys
import json
import shutil
import zipfile
from pathlib import Path
from datetime import datetime


# --------------------------------------------------------------------------
# Colour handling
# --------------------------------------------------------------------------

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


def _enable_windows_ansi():
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            kernel32.SetConsoleMode(handle, 7)  # enable VT100 processing
        except Exception:
            pass


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    print(f"{C.CYAN}{C.BOLD}")
    print("+---------------------------------------------------------+")
    print("|            BRIGHTSPACE ASSIGNMENT GROUPER               |")
    print("+---------------------------------------------------------+")
    print(f"{C.RESET}")


def log(message, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    colors = {
        "INFO": C.GREEN,
        "WARN": C.YELLOW,
        "ERROR": C.RED,
        "OK": C.BOLD + C.CYAN,
    }
    color = colors.get(level, C.WHITE)
    print(f"{C.DIM}[{ts}]{C.RESET} {color}{level:<5}{C.RESET} {message}")


def pause(msg="Press Enter to continue..."):
    input(f"\n{C.DIM}{msg}{C.RESET}")


# --------------------------------------------------------------------------
# Instructions
# --------------------------------------------------------------------------

INSTRUCTIONS = f"""
{C.BOLD}{C.CYAN}WHAT THIS TOOL DOES{C.RESET}
  1. Looks in a folder you choose for every ".zip" file (e.g. bulk
     downloads exported from Brightspace/D2L) -- each zip should be one
     assignment's bulk download (e.g. "Essay 1.zip", "Essay 2.zip").
  2. Peeks inside your zips at a real submission folder name and asks
     you which part is the {C.YELLOW}student name / group name{C.RESET} -- see
     FORMAT DETECTION below.
  3. Extracts each zip into a temporary folder called
     "Extracted_Parent_Zips", keeping each zip's contents separate.
  4. Creates one folder per student/group, and inside it one subfolder
     per assignment (named after the zip file it came from) -- so a
     student with 4 assignment zips ends up with 4 subfolders inside
     their one main folder.
  5. Moves each matching submission folder into the right
     student/assignment subfolder.
  6. Deletes the temporary extraction folder when finished.

{C.BOLD}{C.CYAN}FORMAT DETECTION{C.RESET}
  Brightspace admins can customise how submission folders are named
  (the d2l.Tools.Dropbox.FilenameFormat* settings), so the folder name
  layout differs between institutions. A typical example looks like:

    {C.YELLOW}36275-10937 - 0010087 Student 22 - 07 December 2023 0931{C.RESET}

  The first time you run this tool (or whenever you reset the format)
  it shows you one real folder name split into every individual word
  and number (e.g. "36275", "10937", "0010087", "Student", "22", ...)
  and asks which part number(s) are the {C.YELLOW}student name / group name{C.RESET}
  -- folders are grouped and named by this. Combine more than one part
  by separating the numbers with a space, dash, or underscore (e.g.
  "4-5"). A sensible suggestion is pre-filled (press Enter to accept
  it) and an example of the combined result is shown immediately after
  you pick. It then tests the result against every folder name it can
  find and shows you a preview of the resulting group folders before
  you continue. Your answer is remembered in your user profile so you
  won't be asked again next time, unless you choose "Reset saved
  naming format" from the main menu.

{C.BOLD}{C.CYAN}RESULT{C.RESET}
  All submissions for student/group "Student 22" end up nested inside
  one folder, with a subfolder per assignment zip:

    {C.YELLOW}Student 22/{C.RESET}
    {C.YELLOW}  Essay 1/{C.RESET}
    {C.YELLOW}  Essay 2/{C.RESET}

  right alongside your original zip files.

{C.BOLD}{C.CYAN}BEFORE YOU START{C.RESET}
  - Put (or point this tool at) the folder containing your .zip files.
  - Name each zip after its assignment (e.g. "Essay 1.zip") -- that
    name becomes the assignment subfolder name.
  - Nothing outside that folder is touched.
  - The temporary extraction folder is cleaned up automatically, even
    if some individual files fail (errors are logged, not fatal).

{C.BOLD}{C.CYAN}NAVIGATION{C.RESET}
  - At most prompts you can type {C.YELLOW}b{C.RESET} to go back a step.
  - Type {C.YELLOW}q{C.RESET} at any prompt to quit the program.
"""


def print_instructions():
    clear()
    banner()
    print(INSTRUCTIONS)


# --------------------------------------------------------------------------
# Folder selection
# --------------------------------------------------------------------------

def browse_for_folder(initial_dir: Path):
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return "unavailable"

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            initialdir=str(initial_dir),
            title="Select the folder containing your Brightspace zip files",
        )
        root.destroy()
    except Exception:
        return "unavailable"

    return Path(selected) if selected else None


def choose_directory():
    default_dir = Path.cwd()
    browsing_available = True
    while True:
        clear()
        banner()
        print(f"{C.BOLD}Step 1: Choose the folder containing your .zip files{C.RESET}\n")
        print(f"  Current directory: {C.YELLOW}{default_dir}{C.RESET}")
        print(f"  Press {C.CYAN}Enter{C.RESET} to use it, type a different path,")
        if browsing_available:
            print(f"  {C.CYAN}v{C.RESET} to browse for a folder,")
        print(f"  {C.CYAN}b{C.RESET} to go back, or {C.CYAN}q{C.RESET} to quit.\n")

        choice = input(f"{C.BOLD}> {C.RESET}").strip()

        if choice.lower() == "q":
            confirm_quit()
            continue
        if choice.lower() == "b":
            return None
        if choice == "":
            return default_dir
        if choice.lower() == "v" and browsing_available:
            picked = browse_for_folder(default_dir)
            if picked == "unavailable":
                log("Folder browser isn't available on this system. Type a path instead.", "WARN")
                browsing_available = False
                pause()
                continue
            if picked is None:
                continue  # dialog was cancelled
            return picked

        path = Path(choice).expanduser()
        if path.is_dir():
            return path

        log(f"'{choice}' is not a valid folder.", "ERROR")
        pause()


# --------------------------------------------------------------------------
# Preview + confirmation
# --------------------------------------------------------------------------

def find_zips(directory: Path):
    return sorted(p for p in directory.glob("*.zip") if p.is_file())


def preview_and_confirm(directory: Path, zips):
    clear()
    banner()
    print(f"{C.BOLD}Step 2: Confirm{C.RESET}\n")
    print(f"  Folder: {C.YELLOW}{directory}{C.RESET}\n")

    print(f"  Found {C.CYAN}{len(zips)}{C.RESET} zip file(s):")
    for z in zips:
        size_kb = z.stat().st_size / 1024
        print(f"    - {z.name} ({size_kb:,.0f} KB)")

    print(f"\n  Type {C.GREEN}y{C.RESET} to continue, "
          f"{C.CYAN}b{C.RESET} to pick a different folder, "
          f"or {C.CYAN}q{C.RESET} to quit.\n")

    while True:
        choice = input(f"{C.BOLD}> {C.RESET}").strip().lower()
        if choice == "y":
            return "proceed"
        if choice == "b":
            return "back"
        if choice == "q":
            confirm_quit()
            continue
        log("Please type y, b, or q.", "WARN")


def confirm_quit():
    choice = input(f"{C.YELLOW}Quit the program? [y/N] {C.RESET}").strip().lower()
    if choice == "y":
        print(f"\n{C.CYAN}Goodbye!{C.RESET}")
        sys.exit(0)


# --------------------------------------------------------------------------
# Naming-format detection
# --------------------------------------------------------------------------

FORMAT_CONFIG_PATH = Path.home() / ".brightspace_grouper_format.json"
SEGMENT_DELIMITER = " - "
ATOM_SPLIT = re.compile(r"[-\s]+")
DATE_HINT = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|am|pm|\d{4})\b", re.I
)


def atomize(text: str):
    """Split a folder name into every individual word/number, e.g.
    "36275-10937 - 0010087 Student 22 - ..." becomes
    ["36275", "10937", "0010087", "Student", "22", ...].
    """
    return [a for a in ATOM_SPLIT.split(text.strip()) if a]


def load_saved_format():
    if not FORMAT_CONFIG_PATH.exists():
        return None
    try:
        with open(FORMAT_CONFIG_PATH, "r", encoding="utf-8") as f:
            fmt = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if "key_indices" not in fmt:
        return None  # saved by an older version of this tool
    return fmt


def save_format(fmt):
    try:
        with open(FORMAT_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(fmt, f, indent=2)
        return True
    except OSError as e:
        log(f"Could not save the naming format: {e}", "ERROR")
        return False


def reset_saved_format():
    if FORMAT_CONFIG_PATH.exists():
        try:
            FORMAT_CONFIG_PATH.unlink()
            log("Saved naming format cleared.", "OK")
        except OSError as e:
            log(f"Could not clear the saved format: {e}", "ERROR")
    else:
        log("No saved naming format to clear.", "WARN")
    pause()


def peek_top_level_names(zip_path: Path):
    names = set()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for entry in zf.namelist():
                entry = entry.replace("\\", "/").strip("/")
                if not entry:
                    continue
                top = entry.split("/", 1)[0]
                names.add(top)
    except (zipfile.BadZipFile, OSError):
        pass
    return sorted(names)


def gather_entries(zip_files):
    """Returns [(assignment name, submission folder name), ...] across all
    zips. The assignment name comes from the zip file itself (each zip is
    one assignment's bulk download), not from parsing the folder name.
    """
    entries = []
    for z in zip_files:
        for name in peek_top_level_names(z):
            entries.append((z.stem, name))
    return entries


def match_key(name: str, fmt: dict):
    atoms = atomize(name)
    key_indices = fmt["key_indices"]
    if not key_indices or max(key_indices) >= len(atoms):
        return None
    key = " ".join(atoms[i] for i in key_indices).strip()
    return key or None


def preview_groups(entries, fmt):
    """Returns {student/group name: {assignment name: submission count}}."""
    groups = {}
    unmatched = []
    for assignment_name, folder_name in sorted(entries, key=lambda e: e[1]):
        key = match_key(folder_name, fmt)
        if key is None:
            unmatched.append(folder_name)
            continue
        assignments = groups.setdefault(key, {})
        assignments[assignment_name] = assignments.get(assignment_name, 0) + 1
    return groups, unmatched


def print_group_preview(groups, unmatched, limit=6, assignment_limit=4):
    print(f"\n  This would create {C.CYAN}{len(groups)}{C.RESET} student/group "
          f"folder(s), each containing one subfolder per assignment:\n")
    for key in list(groups)[:limit]:
        assignments = groups[key]
        print(f"    {C.YELLOW}{key}/{C.RESET}")
        for assignment_name, count in list(assignments.items())[:assignment_limit]:
            suffix = f" {C.DIM}(x{count}){C.RESET}" if count > 1 else ""
            print(f"      {C.DIM}└──{C.RESET} {assignment_name}{suffix}")
        if len(assignments) > assignment_limit:
            print(f"      {C.DIM}... and {len(assignments) - assignment_limit} more{C.RESET}")
    if len(groups) > limit:
        print(f"    {C.DIM}... and {len(groups) - limit} more{C.RESET}")

    if unmatched:
        log(f"{len(unmatched)} folder name(s) did not match and will be skipped:", "WARN")
        for n in unmatched[:3]:
            print(f"    - {n}")
        if len(unmatched) > 3:
            print(f"    {C.DIM}... and {len(unmatched) - 3} more{C.RESET}")


def select_atoms(atoms, label, suggested):
    """Ask which fully-split word/number(s) make up a named field. More
    than one can be combined by separating the numbers with a space,
    dash, or underscore. Returns a list of atom indices, or "back".
    """
    print(f"\n  Which part number is the {C.YELLOW}{label}{C.RESET}?")
    print("  Parts:\n")
    for i, atom in enumerate(atoms, start=1):
        print(f"    {C.CYAN}{i}{C.RESET}) {atom}")
    print(f"\n  Type one part number, or combine more than one by separating "
          f"them with a space, dash, or underscore (e.g. {C.CYAN}2{C.RESET}, "
          f"{C.CYAN}1-2{C.RESET}, or {C.CYAN}1_2{C.RESET}).")
    if suggested:
        print(f"  Suggested: {C.CYAN}{'-'.join(str(i + 1) for i in suggested)}{C.RESET} "
              f"-- press Enter to accept.")
    print(f"  Type {C.CYAN}b{C.RESET} to go back.\n")

    while True:
        raw = input(f"{C.BOLD}> {C.RESET}").strip().lower()
        if raw == "b":
            return "back"
        if raw == "" and suggested:
            indices = suggested
            break
        pieces = [p for p in re.split(r"[\s_-]+", raw) if p]
        if pieces and all(p.isdigit() for p in pieces):
            picked = [int(p) - 1 for p in pieces]
            if all(0 <= p < len(atoms) for p in picked):
                indices = picked
                break
        log("Please enter part number(s) separated by space, dash, or "
            "underscore, Enter, or b.", "WARN")

    example = " ".join(atoms[i] for i in indices)
    print(f"\n  {C.DIM}Example:{C.RESET} {C.YELLOW}{example}{C.RESET}")

    return indices


def _segment_default(segment_atoms, prefer):
    """Pick a sensible default sub-selection within one ' - ' segment's
    atoms: drop a leading ID-style number for names, or keep only the
    leading number for IDs.
    """
    if len(segment_atoms) <= 1:
        return segment_atoms
    if prefer == "drop_leading_number" and segment_atoms[0].isdigit():
        return segment_atoms[1:]
    if prefer == "leading_number" and segment_atoms[0].isdigit():
        return segment_atoms[:1]
    return segment_atoms


def run_format_wizard(zip_files):
    while True:
        clear()
        banner()
        print(f"{C.BOLD}Naming format detection{C.RESET}\n")

        sample = None
        for z in zip_files:
            names = peek_top_level_names(z)
            if names:
                sample = names[0]
                break

        if sample is None:
            log("Could not read any folder names out of your zip files.", "ERROR")
            pause()
            return None

        segments = sample.split(SEGMENT_DELIMITER)
        segment_atoms = [atomize(seg) for seg in segments]
        atoms = [a for seg in segment_atoms for a in seg]

        offsets = []
        running = 0
        for seg in segment_atoms:
            offsets.append(running)
            running += len(seg)

        print("  Here is a real folder name found inside your zips:\n")
        print(f"    {C.YELLOW}{sample}{C.RESET}\n")

        if len(atoms) < 2:
            log("That name doesn't split into multiple parts, so this tool", "WARN")
            log("can't detect the naming format automatically.", "WARN")
            pause()
            return None

        key_seg = next(
            (i for i, seg in enumerate(segments)
             if re.search(r"[A-Za-z]", seg) and not DATE_HINT.search(seg)),
            None,
        )
        key_suggested = []
        if key_seg is not None:
            default = _segment_default(segment_atoms[key_seg], "drop_leading_number")
            start = offsets[key_seg] + (len(segment_atoms[key_seg]) - len(default))
            key_suggested = list(range(start, start + len(default)))

        key_indices = select_atoms(
            atoms,
            "STUDENT NAME or GROUP NAME (folders are grouped and named by this)",
            key_suggested,
        )
        if key_indices == "back":
            return None

        fmt = {
            "key_indices": key_indices,
            "sample": sample,
            "detected_at": datetime.now().isoformat(timespec="seconds"),
        }

        entries = gather_entries(zip_files)
        groups, unmatched = preview_groups(entries, fmt)
        print_group_preview(groups, unmatched)

        print(f"\n  Type {C.GREEN}y{C.RESET} to save this format and continue, "
              f"{C.CYAN}r{C.RESET} to redo, or {C.CYAN}b{C.RESET} to go back.\n")

        while True:
            choice = input(f"{C.BOLD}> {C.RESET}").strip().lower()
            if choice == "y":
                if save_format(fmt):
                    log("Naming format saved for next time.", "OK")
                pause()
                return fmt
            if choice == "r":
                break
            if choice == "b":
                return None
            log("Please type y, r, or b.", "WARN")


def determine_format(zip_files):
    saved = load_saved_format()
    if saved is None:
        return run_format_wizard(zip_files)

    while True:
        clear()
        banner()
        print(f"{C.BOLD}Naming format{C.RESET}\n")
        print("  A previously saved naming format was found:\n")
        print(f"    Example: {C.YELLOW}{saved.get('sample', '?')}{C.RESET}")
        print(f"    Saved:   {C.DIM}{saved.get('detected_at', '?')}{C.RESET}")

        entries = gather_entries(zip_files)
        groups, unmatched = preview_groups(entries, saved)
        print_group_preview(groups, unmatched)

        print(f"\n  Type {C.GREEN}y{C.RESET} to use it, "
              f"{C.CYAN}n{C.RESET} to detect a new format, "
              f"or {C.CYAN}b{C.RESET} to go back.\n")

        choice = input(f"{C.BOLD}> {C.RESET}").strip().lower()
        if choice == "y":
            return saved
        if choice == "n":
            return run_format_wizard(zip_files)
        if choice == "b":
            return None
        log("Please type y, n, or b.", "WARN")


# --------------------------------------------------------------------------
# Core organizing logic
# --------------------------------------------------------------------------

def run_organizer(directory: Path, fmt: dict):
    clear()
    banner()
    print(f"{C.BOLD}Step 3: Organizing...{C.RESET}\n")

    temp_extract_path = directory / "Extracted_Parent_Zips"

    if not temp_extract_path.exists():
        try:
            temp_extract_path.mkdir(parents=True)
            log(f"Created temporary extraction folder: {temp_extract_path.name}")
        except OSError as e:
            log(f"Failed to create temporary extraction folder: {e}", "ERROR")
            return
    else:
        log(f"Temporary extraction folder already exists: {temp_extract_path.name}", "WARN")

    zip_files = find_zips(directory)
    if not zip_files:
        log("No ZIP files found in the current directory.", "ERROR")
        return

    log(f"Found {len(zip_files)} ZIP file(s). Starting extraction...")

    extracted = []  # (assignment_name, folder_path)
    for zip_path in zip_files:
        assignment_name = zip_path.stem
        zip_temp_dir = temp_extract_path / assignment_name
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(zip_temp_dir)
            log(f"Extracted: {zip_path.name} (assignment: {assignment_name})")
        except (zipfile.BadZipFile, OSError) as e:
            log(f"Failed to extract '{zip_path.name}': {e}", "ERROR")
            continue

        for folder in zip_temp_dir.iterdir():
            if folder.is_dir():
                extracted.append((assignment_name, folder))

    if not extracted:
        log("No folders found after extracting ZIP files.", "ERROR")
        try:
            shutil.rmtree(temp_extract_path)
            log(f"Removed empty temporary extraction folder: {temp_extract_path.name}")
        except OSError as e:
            log(f"Failed to remove temporary extraction folder: {e}", "ERROR")
        return

    log(f"Found {len(extracted)} extracted folder(s) across {len(zip_files)} assignment(s). Processing...")

    student_keys = set()
    moved = 0
    skipped = 0
    move_errors = 0

    for assignment_name, folder in extracted:
        key = match_key(folder.name, fmt)
        if key is None:
            log(f"Folder name '{folder.name}' does not match the expected format. Skipping.", "ERROR")
            skipped += 1
            continue

        student_folder = directory / key
        assignment_folder = student_folder / assignment_name

        if not student_folder.exists():
            try:
                student_folder.mkdir(parents=True)
                log(f"Created student/group folder: {key}")
            except OSError as e:
                log(f"Failed to create student/group folder '{key}': {e}", "ERROR")
                move_errors += 1
                continue
        student_keys.add(key)

        if not assignment_folder.exists():
            try:
                assignment_folder.mkdir(parents=True)
                log(f"Created assignment folder: {key}/{assignment_name}")
            except OSError as e:
                log(f"Failed to create assignment folder '{key}/{assignment_name}': {e}", "ERROR")
                move_errors += 1
                continue

        destination = assignment_folder / folder.name
        try:
            shutil.move(str(folder), str(destination))
            log(f"Moved '{folder.name}' to '{key}/{assignment_name}'")
            moved += 1
        except (shutil.Error, OSError) as e:
            log(f"Failed to move '{folder.name}' to '{key}/{assignment_name}': {e}", "ERROR")
            move_errors += 1

    try:
        shutil.rmtree(temp_extract_path)
        log(f"Removed temporary extraction folder: {temp_extract_path.name}")
    except OSError as e:
        log(f"Failed to remove temporary extraction folder: {e}", "ERROR")

    print()
    log(f"Done. {moved} folder(s) moved into {len(student_keys)} student/group folder(s), "
        f"{skipped} skipped, {move_errors} move error(s).", "OK")


# --------------------------------------------------------------------------
# Main menu
# --------------------------------------------------------------------------

def organize_flow():
    directory = choose_directory()
    while directory is not None:
        zips = find_zips(directory)
        if not zips:
            clear()
            banner()
            log("No .zip files found in that folder.", "ERROR")
            pause()
            directory = choose_directory()
            continue

        result = preview_and_confirm(directory, zips)
        if result == "back":
            directory = choose_directory()
            continue

        fmt = determine_format(zips)
        if fmt is None:
            continue

        run_organizer(directory, fmt)
        pause("Press Enter to return to the menu...")
        directory = None


def main_menu():
    while True:
        clear()
        banner()
        print(f"  {C.CYAN}1{C.RESET}) View instructions")
        print(f"  {C.CYAN}2{C.RESET}) Start organizing")
        print(f"  {C.CYAN}3{C.RESET}) Reset saved naming format")
        print(f"  {C.CYAN}4{C.RESET}) Exit\n")

        choice = input(f"{C.BOLD}> {C.RESET}").strip().lower()

        if choice == "1":
            print_instructions()
            pause("Press Enter to return to the menu...")

        elif choice == "2":
            organize_flow()

        elif choice == "3":
            reset_saved_format()

        elif choice in ("4", "q"):
            print(f"\n{C.CYAN}Goodbye!{C.RESET}")
            sys.exit(0)

        else:
            log("Please choose 1, 2, 3, or 4.", "WARN")
            pause()


def main():
    _enable_windows_ansi()
    try:
        main_menu()
    except KeyboardInterrupt:
        print(f"\n{C.CYAN}Goodbye!{C.RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
