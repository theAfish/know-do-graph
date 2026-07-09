from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def _console_script(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "know-do-graph.exe"
    return venv / "bin" / "know-do-graph"


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _assert_wheel_contents(wheel: Path) -> None:
    with ZipFile(wheel) as zf:
        names = set(zf.namelist())
    required = {
        "core/resources/starter.db",
        "frontend/dist/index.html",
        "examples/python_api.py",
    }
    missing = sorted(required - names)
    if missing:
        raise SystemExit(f"Wheel is missing expected package data: {missing}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build, install, and smoke-test the wheel.")
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary build/install directory for debugging.",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    if not (repo / "frontend" / "dist" / "index.html").exists():
        raise SystemExit("frontend/dist/index.html is missing; run npm --prefix frontend run build")
    if not (repo / "assets" / "starter.db").exists():
        raise SystemExit("assets/starter.db is missing")

    temp_root = Path(tempfile.mkdtemp(prefix="kdg-wheel-smoke-"))
    try:
        dist_dir = temp_root / "dist"
        dist_dir.mkdir()
        _run(
            [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist_dir)],
            cwd=repo,
        )
        wheels = sorted(dist_dir.glob("know_do_graph-*.whl"))
        if not wheels:
            raise SystemExit("No know_do_graph wheel was built")
        wheel = wheels[-1]
        _assert_wheel_contents(wheel)

        venv = temp_root / "venv"
        _run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)], cwd=repo)
        python = _venv_python(venv)
        _run([str(python), "-m", "pip", "install", str(wheel)], cwd=repo)

        db_path = temp_root / "smoke.db"
        env = {**os.environ, "KDG_DB_PATH": str(db_path)}
        cli = _console_script(venv)
        _run([str(cli), "init", "--starter", "--force"], cwd=repo, env=env)
        _run([str(cli), "serve", "--help"], cwd=repo, env=env)

        lifecycle = (
            "from know_do_graph import KnowDoGraph, EntryType; "
            f"g=KnowDoGraph(r'{temp_root / 'client.db'}'); "
            "e=g.add('Wheel Smoke Entry', entry_type=EntryType.capability); "
            "assert g.get(e.slug).id == e.id; "
            "assert g.delete(e.id); "
            "g.close()"
        )
        _run([str(python), "-c", lifecycle], cwd=repo, env=env)
    finally:
        if args.keep_temp:
            print(temp_root)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
