from __future__ import annotations
import pathlib

_LIBRARY_DIR = pathlib.Path(__file__).resolve().parent.parent / "solution_library"

def has_solution(task_id: str) -> bool:
    clean_id = task_id.replace("t1-", "").strip()
    direct = _LIBRARY_DIR / f"{task_id}.py"
    clean = _LIBRARY_DIR / f"{clean_id}.py"
    return direct.exists() or clean.exists()

def get_solution(task_id: str) -> str | None:
    clean_id = task_id.replace("t1-", "").strip()
    direct = _LIBRARY_DIR / f"{task_id}.py"
    clean = _LIBRARY_DIR / f"{clean_id}.py"
    if direct.exists():
        return direct.read_text(encoding="utf-8")
    if clean.exists():
        return clean.read_text(encoding="utf-8")
    return None

def save_solution(task_id: str, code: str) -> pathlib.Path:
    _LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    clean = task_id.replace("t1-", "").strip()
    target = _LIBRARY_DIR / f"{clean}.py"
    target.write_text(code, encoding="utf-8")
    return target
