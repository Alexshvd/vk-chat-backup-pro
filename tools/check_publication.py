"""Check publication inputs without printing private values or modifying an archive."""
import argparse
import json
import re
import subprocess
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_BASE = "8f84759f5f7129605ef2005b7644254545e80d2a"
ARCHIVE_DIRS = {"originalmessages", "rawdata", "largerawdata", "sharedmedia", "autorimages"}
PRIVATE_MAPS = ("dialog_name_by_peer_id", "min_cid_by_peer_id", "min_date_by_peer_id")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def private_patterns():
    ids, words = set(), set()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    for key, value in config.get("dialog_name_by_peer_id", {}).items():
        ids.add(str(key))
        if len(value) >= 8:
            words.add(value)
    local_denylist = ROOT / ".publication-private.json"
    if local_denylist.is_file():
        words.update(json.loads(local_denylist.read_text(encoding="utf-8")))

    def walk(value):
        if isinstance(value, dict):
            for key, entry in value.items():
                if key in ("peer_id", "from_id", "owner_id", "user_id") and isinstance(entry, int) and abs(entry) >= 100000:
                    ids.add(str(abs(entry)))
                if key == "text" and isinstance(entry, str) and len(entry.strip()) >= 35:
                    words.add(entry.strip())
                walk(entry)
            if value.get("first_name") and value.get("last_name"):
                words.add(value["first_name"] + " " + value["last_name"])
                if isinstance(value.get("id"), int) and abs(value["id"]) >= 100000:
                    ids.add(str(abs(value["id"])))
        elif isinstance(value, list):
            for entry in value:
                walk(entry)
        elif isinstance(value, str) and value.startswith("http"):
            if any(domain in value for domain in ("userapi.com", "vkuseraudio", "vk-cdn", "vkuser.net")):
                words.add(value)

    export_root = config.get("export_root", "")
    if export_root:
        archive = Path(export_root)
        if not archive.is_absolute():
            archive = ROOT / archive
        for source in (archive / "ExportMessages" / "Sources").glob("*.json"):
            walk(json.loads(source.read_text(encoding="utf-8-sig")))
    numeric = None
    if ids:
        numeric = re.compile(rb"(?<![0-9])(?:" + b"|".join(word.encode() for word in sorted(ids, key=len, reverse=True)) + rb")(?![0-9])")
    patterns = [word.encode("utf-8") for word in words if word]
    # UTF-16 catches private strings in Windows binaries as well.
    patterns.extend(word.encode("utf-16le") for word in words if word and len(word) <= 150)
    return numeric, patterns


def neutral_config(data):
    config = json.loads(data)
    return not config.get("export_root") and all(not config.get(key) for key in PRIVATE_MAPS)


def scan_revision(revision="HEAD", index=False, packages=()):
    failures = []
    numeric, patterns = private_patterns()

    def scan(data, location):
        if any(word in data for word in patterns):
            failures.append(location + ": matches a local private value")
        if numeric and b"\x00" not in data and numeric.search(data):
            failures.append(location + ": matches a local archive identifier")

    def check_file(path, data):
        segments = {part.lower() for part in Path(path).parts}
        if segments & ARCHIVE_DIRS or Path(path).name.lower().startswith("messages_peerid_"):
            failures.append(path + ": archive file must not be published")
        scan(path.encode("utf-8"), path)
        scan(data, path)
        if Path(path).name in ("config.json", "config.example.json"):
            if not neutral_config(data):
                failures.append(path + ": configuration is not neutral")

    if index:
        revision = git("write-tree").decode().strip()
        identity = git("var", "GIT_AUTHOR_IDENT").decode()
        if not re.search(r"<[^<>]+@users\.noreply\.github\.com>", identity):
            failures.append("commit author: use the GitHub noreply email")
    else:
        object_id = git("rev-parse", revision).decode().strip()
        if git("cat-file", "-t", object_id).strip() == b"tag":
            tag = git("cat-file", "tag", object_id)
            scan(tag, "release tag")
            tagger = next((line for line in tag.splitlines() if line.startswith(b"tagger ")), b"")
            if not re.search(rb"<[^<>]+@users\.noreply\.github\.com>", tagger):
                failures.append("release tag: use the GitHub noreply email")
        revision = git("rev-parse", revision + "^{commit}").decode().strip()
        commits = git("log", "--format=%ae%n%ce", UPSTREAM_BASE + ".." + revision).decode().splitlines()
        if any(not email.endswith("@users.noreply.github.com") for email in commits):
            failures.append("fork history: personal author or committer email")
        # Check earlier fork commits too, even if a later commit removed a value.
        for entry in git("rev-list", "--objects", UPSTREAM_BASE + ".." + revision).decode().splitlines():
            oid, _, name = entry.partition(" ")
            kind = git("cat-file", "-t", oid).strip()
            if kind in (b"commit", b"blob"):
                scan(git("cat-file", "-p", oid), "fork history: " + (name or kind.decode()))
    entries = git("ls-tree", "-r", "-z", revision).split(b"\x00")
    files = []
    for entry in entries:
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        if kind == b"blob":
            files.append((oid, path.decode("utf-8")))
        else:
            failures.append(path.decode("utf-8") + ": external Git object needs a separate audit")
    batch = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT,
                           input=b"\n".join(oid for oid, path in files) + b"\n",
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    offset = 0
    for oid, path in files:
        end = batch.index(b"\n", offset)
        size = int(batch[offset:end].split()[-1])
        data = batch[end + 1:end + 1 + size]
        offset = end + 2 + size
        check_file(path, data)
    for package in packages:
        with zipfile.ZipFile(package) as archive:
            if archive.testzip():
                failures.append("package: ZIP integrity check failed")
            for entry in archive.infolist():
                check_file(entry.filename, archive.read(entry))
    return sorted(set(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--package", action="append", default=[])
    args = parser.parse_args()
    try:
        failures = scan_revision(args.revision, args.index, args.package)
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile):
        print("Publication blocked: privacy check could not complete. No private values are printed.")
        return 1
    for failure in failures:
        print("Publication blocked: " + failure)
    if not failures:
        print("Publication privacy checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
