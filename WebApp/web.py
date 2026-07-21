import html
import json as _json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory, stream_with_context, url_for
from mistune import HTMLRenderer, create_markdown

from config_loader import load_config
from logger import Logger
from main import main as run_pipeline

CID_PATTERN = re.compile(r"\.Id(\d+)(?:_part_\d+)?\.md$")

app = Flask(__name__)
export_root_abs: Optional[Path] = None
export_serve_abs: Optional[Path] = None
large_root_abs: Optional[Path] = None
dialogs_dir_abs: Optional[Path] = None
renderer = HTMLRenderer(escape=False)
md = create_markdown(renderer=renderer, plugins=['table', 'strikethrough'])
_config_path = ""


def init_app(config_path: str):
    global _config_path, export_root_abs, export_serve_abs, large_root_abs, dialogs_dir_abs
    _config_path = config_path
    config = load_config(config_path)
    export_root_abs = Path(config.export_root).resolve()
    export_serve_abs = export_root_abs / "ExportMessages"
    large_root_abs = export_root_abs / "LargeRawData"
    dialogs_dir_abs = export_serve_abs / "Dialogs"


def _get_dialog_dir(peer_id: int) -> Path:
    return dialogs_dir_abs / f"dialog_{peer_id}"


def _max_filename_len(directory: Path) -> int:
    return 254 - len(str(directory)) - 1


def _rewrite_md_links(md_text: str, md_file_abs: Path) -> str:
    md_dir = md_file_abs.parent

    extra_mounts = []
    if export_serve_abs and large_root_abs:
        extra_mounts = [(large_root_abs, "/large")]

    def _resolve(url: str) -> str:
        if url.startswith(("http://", "https://", "/", "data:")):
            return url
        resolved = (md_dir / url).resolve()
        try:
            rel = resolved.relative_to(export_serve_abs)
            return f"/export/{rel.as_posix()}"
        except ValueError:
            pass
        for mount_root, mount_prefix in extra_mounts:
            try:
                rel = resolved.relative_to(mount_root)
                return f"{mount_prefix}/{rel.as_posix()}"
            except ValueError:
                pass
        return url

    def _fix_md_link(m: re.Match) -> str:
        before, link = m.group(1), m.group(2)
        return f"{before}{_resolve(link)})"

    def _fix_html_src(m: re.Match) -> str:
        return f'{m.group(1)}{_resolve(m.group(2))}"'

    md_text = re.sub(r'(!\[.*?\]\()(.+?)\)', _fix_md_link, md_text)
    md_text = re.sub(r'(\[[^\]]*?\]\()(.+?)\)', _fix_md_link, md_text)
    md_text = re.sub(r'(src=")(.+?)(")', _fix_html_src, md_text)
    md_text = re.sub(r'(href=")(.+?)(")', _fix_html_src, md_text)
    return md_text


def _md_to_html(md_file_abs: Path) -> str:
    raw = md_file_abs.read_text(encoding="utf-8")
    rewritten = _rewrite_md_links(raw, md_file_abs)
    html = md(rewritten)
    return html


def _find_md_files(md_dir: Path, cid: int) -> list[Path]:
    result = []
    if not md_dir.is_dir():
        return result
    for f in md_dir.iterdir():
        if not f.is_file() or not f.name.endswith(".md"):
            continue
        m = CID_PATTERN.search(f.name)
        if m and int(m.group(1)) == cid:
            result.append(f)
    return sorted(result)



def _get_attachment_size(md_dir: Path, raw_dir: Path, large_dir_root: Path, peer_id: int, cid: int) -> int:
    total = 0
    cid_raw = raw_dir / str(cid)
    if cid_raw.is_dir():
        for f in cid_raw.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    cid_large = large_dir_root / f"dialog_{peer_id}" / str(cid)
    if cid_large.is_dir():
        for f in cid_large.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    return total


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / 1024 / 1024:.1f} MB"


def _get_date_from_json(orig_dir: Path, cid: int) -> str:
    if not orig_dir.is_dir():
        return ""
    for f in orig_dir.iterdir():
        if f.is_file() and f.name.endswith(f"_{cid}.json"):
            parts = f.name.rsplit("_", 1)[0].split("-")
            return f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}:{parts[4]}:{parts[5]}"
    return ""


def _build_message_date_str_by_cid(orig_dir: Path) -> dict[int, str]:
    result: dict[int, str] = {}
    if not orig_dir.is_dir():
        return result
    for f in orig_dir.glob("*.json"):
        name = f.name
        date_part, _, cid_part = name.rpartition("_")
        cid_str = cid_part.replace(".json", "")
        try:
            cid_val = int(cid_str)
            parts = date_part.split("-")
            result[cid_val] = f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}:{parts[4]}:{parts[5]}"
        except (ValueError, IndexError):
            Logger.LogWarning(f"Не удалось распарсить имя файла JSON: {name}")
    return result


def _delete_cid(peer_id: int, cid: int) -> dict:
    dialog_dir = _get_dialog_dir(peer_id)
    md_dir = dialog_dir / "MdFiles"
    raw_dir = dialog_dir / "RawData"
    orig_dir = dialog_dir / "OriginalMessages"
    large_dir = large_root_abs / f"dialog_{peer_id}"

    deleted = {"md_files": [], "raw_dir": None, "large_dir": None, "json_files": []}

    for f in _find_md_files(md_dir, cid):
        f.unlink()
        deleted["md_files"].append(str(f))

    cid_raw = raw_dir / str(cid)
    if cid_raw.is_dir():
        shutil.rmtree(cid_raw)
        deleted["raw_dir"] = str(cid_raw)

    cid_large = large_dir / str(cid)
    if cid_large.is_dir():
        shutil.rmtree(cid_large)
        deleted["large_dir"] = str(cid_large)

    if orig_dir.is_dir():
        for f in orig_dir.iterdir():
            if f.is_file() and f.name.endswith(f"_{cid}.json"):
                f.unlink()
                deleted["json_files"].append(str(f))

    return deleted


def _list_attachments(peer_id: int, cid: int) -> dict:
    dialog_dir = _get_dialog_dir(peer_id)
    raw_dir = dialog_dir / "RawData" / str(cid)
    large_dir = large_root_abs / f"dialog_{peer_id}" / str(cid)

    files = {"raw": [], "large": []}
    if raw_dir.is_dir():
        for f in sorted(raw_dir.iterdir()):
            if f.is_file():
                files["raw"].append({"name": f.name, "size": f.stat().st_size, "path": str(f)})
    if large_dir.is_dir():
        for f in sorted(large_dir.iterdir()):
            if f.is_file():
                files["large"].append({"name": f.name, "size": f.stat().st_size, "path": str(f)})
    return files


def _get_dialog_name(peer_id: int) -> str:
    md_dir = _get_dialog_dir(peer_id) / "MdFiles"
    if not md_dir.is_dir():
        return f"dialog_{peer_id}"
    for f in sorted(md_dir.iterdir()):
        if f.is_file() and f.name.endswith(".md"):
            heading = f.name
            if heading:
                return f"{heading} ({peer_id})"
    return f"dialog_{peer_id}"


# ─── Routes (Export) ─────────────────────────────────────────

@app.route("/export")
def export_page():
    sources_dir = export_serve_abs / "Sources"
    sources_dir_exists = sources_dir.is_dir()
    files_by_peer_id = {}
    if sources_dir_exists:
        for f in sorted(sources_dir.iterdir()):
            if f.is_file() and f.suffix == ".json":
                try:
                    with open(f, encoding="utf-8") as fp:
                        data = _json.load(fp)
                    peer_id = data.get("peer_id", 0)
                except Exception:
                    peer_id = 0
                files_by_peer_id.setdefault(peer_id, []).append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "size_str": _format_size(f.stat().st_size),
                })

    config = load_config(_config_path)
    filters = {}
    for peer_id in files_by_peer_id:
        min_cid = config.min_cid_by_peer_id.get(peer_id)
        min_date_ts = config.min_date_by_peer_id.get(peer_id)
        min_date_str = ""
        if min_date_ts:
            min_date_str = datetime.fromtimestamp(min_date_ts).strftime("%Y-%m-%d-%H-%M-%S")
        filters[peer_id] = {"min_cid": min_cid if min_cid is not None else "", "min_date": min_date_str}

    status = request.args.get("status")
    return render_template("export.html", files_by_peer_id=files_by_peer_id,
                           filters=filters,
                           sources_path=str(sources_dir),
                           dialogs_path=str(dialogs_dir_abs),
                           sources_dir_exists=sources_dir_exists, status=status)


@app.route("/export/create-sources", methods=["POST"])
def create_sources():
    sources_dir = export_serve_abs / "Sources"
    already = sources_dir.is_dir()
    sources_dir.mkdir(parents=True, exist_ok=True)
    status = "already" if already else "created"
    return redirect(url_for("export_page", status=status))


@app.route("/export/upload", methods=["POST"])
def upload_to_sources():
    sources_dir = export_serve_abs / "Sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    file = request.files.get("file")
    if file and file.filename:
        dest = sources_dir / file.filename
        file.save(str(dest))
        return redirect(url_for("export_page", status="uploaded"))
    return redirect(url_for("export_page", status="upload_error"))


@app.route("/export/save-filters", methods=["POST"])
def save_filters():
    data = request.get_json()
    filters = data.get("filters", {})

    with open(_config_path, encoding="utf-8") as f:
        raw = _json.load(f)

    raw["min_cid_by_peer_id"] = {}
    raw["min_date_by_peer_id"] = {}

    for peer_id_str, item in filters.items():
        cid = item.get("min_cid", "")
        date = item.get("min_date", "")
        if cid != "":
            raw["min_cid_by_peer_id"][peer_id_str] = int(cid)
        if date:
            raw["min_date_by_peer_id"][peer_id_str] = date

    with open(_config_path, "w", encoding="utf-8") as f:
        _json.dump(raw, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True})


@app.route("/export/generate", methods=["POST"])
def run_export():
    config = load_config(_config_path)

    def generate():
        yield "<!DOCTYPE html>\n<html lang='ru'>\n<head>\n<meta charset='UTF-8'>\n<title>Генерация MD</title>\n<style>"
        yield "body{font-family:monospace;background:#1e1e1e;color:#d4d4d4;padding:20px;font-size:14px;line-height:1.5}"
        yield "pre{margin:0}.done{color:#4ec9b0}.err{color:#f44747}</style></head><body><pre>"
        try:
            for msg in run_pipeline(config):
                escaped = html.escape(msg)
                yield escaped + "\n"
        except Exception as e:
            yield f'<span class="err">{html.escape(str(e))}</span>\n'
        yield '</pre><p class="done"><a href="/export" style="color:#4ec9b0">← Назад к экспорту</a></p></body></html>'

    return Response(stream_with_context(generate()), mimetype="text/html")


# ─── Routes (Main) ────────────────────────────────────────────

@app.route("/")
def index():
    dialogs = []
    if not dialogs_dir_abs.is_dir():
        return render_template("index.html", dialogs=[])
    for entry in sorted(dialogs_dir_abs.iterdir()):
        if entry.is_dir() and entry.name.startswith("dialog_"):
            peer_id = int(entry.name[len("dialog_"):])
            md_dir = entry / "MdFiles"
            count = len([f for f in md_dir.glob("*.md")]) if md_dir.is_dir() else 0

            last_message_name = ""
            if md_dir.is_dir():
                last_cid = 0
                last_filename = ""
                for f in md_dir.iterdir():
                    if f.is_file() and f.name.endswith(".md"):
                        m = CID_PATTERN.search(f.name)
                        if m:
                            cid = int(m.group(1))
                            if cid > last_cid:
                                last_cid = cid
                                last_filename = f.name
                if last_filename:
                    last_message_name = re.sub(r"\.Id\d+(?:_part_\d+)?\.md$", "", last_filename)

            dialogs.append({
                "peer_id": peer_id,
                "name": _get_dialog_name(peer_id),
                "count": count,
                "last_message_name": last_message_name,
            })
    return render_template("index.html", dialogs=dialogs)


@app.route("/dialog/<int:peer_id>")
def dialog_messages(peer_id: int):
    dialog_dir = _get_dialog_dir(peer_id)
    if not dialog_dir.is_dir():
        abort(404)
    md_dir = dialog_dir / "MdFiles"
    raw_dir = dialog_dir / "RawData"
    orig_dir = dialog_dir / "OriginalMessages"
    message_date_str_by_cid = _build_message_date_str_by_cid(orig_dir)
    messages = []
    if md_dir.is_dir():
        for f in md_dir.iterdir():
            if not f.is_file() or not f.name.endswith(".md"):
                continue
            m = CID_PATTERN.search(f.name)
            if not m:
                continue
            cid = int(m.group(1))
            heading = f.name
            size = f.stat().st_size
            attach_size = _get_attachment_size(md_dir, raw_dir, large_root_abs, peer_id, cid)
            messages.append({
                "cid": cid,
                "filename": f.name,
                "heading": heading,
                "date_str": message_date_str_by_cid.get(cid, ""),
                "size": size,
                "size_str": _format_size(size),
                "attach_size": attach_size,
                "attach_size_str": _format_size(attach_size) if attach_size else "-",
                "is_part": "_part_" in f.name,
                "has_raw": (raw_dir / str(cid)).is_dir(),
                "has_large": (large_root_abs / f"dialog_{peer_id}" / str(cid)).is_dir(),
            })
    last_message_name = ""
    if messages:
        last_msg = max(messages, key=lambda m: m["cid"])
        last_name = last_msg["filename"]
        last_name = re.sub(r"\.Id\d+(?:_part_\d+)?\.md$", "", last_name)
        last_message_name = last_name

    return render_template("dialog.html", peer_id=peer_id, dialog_name=_get_dialog_name(peer_id),
                           messages=messages, last_message_name=last_message_name)


@app.route("/dialog/<int:peer_id>/<int:cid>/content")
def message_content(peer_id: int, cid: int):
    dialog_dir = _get_dialog_dir(peer_id)
    md_dir = dialog_dir / "MdFiles"
    files = _find_md_files(md_dir, cid)
    if not files:
        return jsonify({"html": "<p><em>MD file not found</em></p>"})
    parts = []
    for f in files:
        html_content = _md_to_html(f)
        parts.append({"filename": f.name, "html": html_content})
    return jsonify({"parts": parts})


@app.route("/dialog/<int:peer_id>/<int:cid>", methods=["DELETE"])
def delete_message(peer_id: int, cid: int):
    result = _delete_cid(peer_id, cid)
    return jsonify({"success": True, "deleted": result})


@app.route("/dialog/<int:peer_id>/delete-batch", methods=["POST"])
def delete_batch(peer_id: int):
    data = request.get_json(force=True)
    cids = data.get("cids", [])
    results = {}
    for cid in cids:
        results[cid] = _delete_cid(peer_id, cid)
    return jsonify({"success": True, "results": results})


@app.route("/dialog/<int:peer_id>/<int:cid>/rename", methods=["PUT"])
def rename_md_file(peer_id: int, cid: int):
    data = request.get_json(force=True)
    new_name = data.get("filename", "").strip()
    if not new_name:
        return jsonify({"success": False, "error": "filename is required"}), 400

    dialog_dir = _get_dialog_dir(peer_id)
    md_dir = dialog_dir / "MdFiles"
    files = _find_md_files(md_dir, cid)
    if not files:
        return jsonify({"success": False, "error": "MD file not found"}), 404

    results = []
    for f in files:
        m = CID_PATTERN.search(f.name)
        if not m:
            continue
        suffix = m.group(0)
        new_filename = f"{new_name}{suffix}"
        if len(new_filename) > _max_filename_len(md_dir):
            return jsonify({"success": False, "error": f"Filename too long (max {_max_filename_len(md_dir) - len(suffix)} chars for name)"}), 400
        new_path = f.parent / new_filename
        if new_path.exists():
            return jsonify({"success": False, "error": f"File {new_filename} already exists"}), 409
        f.rename(new_path)
        results.append({"old": f.name, "new": new_filename})
    return jsonify({"success": True, "renamed": results})


@app.route("/dialog/<int:peer_id>/<int:cid>/attachments")
def list_attachments(peer_id: int, cid: int):
    return jsonify(_list_attachments(peer_id, cid))


@app.route("/dialog/<int:peer_id>/<int:cid>/rename-attachment", methods=["PUT"])
def rename_attachment(peer_id: int, cid: int):
    data = request.get_json(force=True)
    old_name = data.get("old_name", "").strip()
    new_name = data.get("new_name", "").strip()
    storage = data.get("storage", "raw")
    if not old_name or not new_name:
        return jsonify({"success": False, "error": "old_name and new_name are required"}), 400

    if Path(old_name).suffix.lower() != Path(new_name).suffix.lower():
        return jsonify({"success": False, "error": "Cannot change file extension"}), 400

    dialog_dir = _get_dialog_dir(peer_id)
    md_dir = dialog_dir / "MdFiles"

    if storage == "raw":
        file_dir = dialog_dir / "RawData" / str(cid)
    elif storage == "large":
        file_dir = large_root_abs / f"dialog_{peer_id}" / str(cid)
    else:
        return jsonify({"success": False, "error": "invalid storage type"}), 400

    max_len = _max_filename_len(file_dir)
    if len(new_name) > max_len:
        return jsonify({"success": False, "error": f"Filename too long (max {max_len} chars)"}), 400

    old_path = file_dir / old_name
    new_path = file_dir / new_name
    if not old_path.is_file():
        return jsonify({"success": False, "error": f"File not found: {old_name}"}), 404
    if new_path.exists():
        return jsonify({"success": False, "error": f"File {new_name} already exists"}), 409

    old_abs = old_path.resolve()
    new_abs = new_path.resolve()
    old_path.rename(new_path)

    old_rel = os.path.relpath(str(old_abs), str(md_dir)).replace("\\", "/")
    new_rel = os.path.relpath(str(new_abs), str(md_dir)).replace("\\", "/")

    md_files = _find_md_files(md_dir, cid)
    for mf in md_files:
        content = mf.read_text(encoding="utf-8")
        updated = content.replace(old_rel, new_rel)
        if updated != content:
            mf.write_text(updated, encoding="utf-8")

    return jsonify({"success": True, "old_rel": old_rel, "new_rel": new_rel})


@app.route("/dialog/<int:peer_id>/limits/<int:cid>")
def get_limits(peer_id: int, cid: int):
    md_dir = _get_dialog_dir(peer_id) / "MdFiles"
    raw_dir = _get_dialog_dir(peer_id) / "RawData" / str(cid)
    large_dir = large_root_abs / f"dialog_{peer_id}" / str(cid)
    return jsonify({
        "md": _max_filename_len(md_dir),
        "raw": _max_filename_len(raw_dir),
        "large": _max_filename_len(large_dir),
    })


@app.route("/export/<path:filename>")
def serve_export(filename: str):
    return send_from_directory(str(export_serve_abs), filename)


@app.route("/large/<path:filename>")
def serve_large(filename: str):
    return send_from_directory(str(large_root_abs), filename)
