#!/usr/bin/env python3
"""
CryoNav — Main Application Entrypoint.

Launches the unified CryoNav system (FastAPI backend + Interactive Leaflet Web UI).
Runs everything on a single port with zero external dependencies beyond requirements.txt.

Usage:
    python main.py                   # Run on http://127.0.0.1:8000 and open browser
    python main.py --port 8080       # Custom port
    python main.py --public          # Bind to 0.0.0.0 for network access
    python main.py --reload          # Enable hot-reloading for development
    python main.py --no-browser      # Do not open browser automatically
"""
import os
import sys
from pathlib import Path

# Auto-activate .venv if running with system python
PROJECT_ROOT = Path(__file__).resolve().parent
_venv_bin = "Scripts" if os.name == "nt" else "bin"
_venv_exe = "python.exe" if os.name == "nt" else "python"
venv_python = PROJECT_ROOT / ".venv" / _venv_bin / _venv_exe
if venv_python.exists() and (sys.prefix == sys.base_prefix):
    os.environ["VIRTUAL_ENV"] = str(PROJECT_ROOT / ".venv")
    os.environ["PATH"] = str(PROJECT_ROOT / ".venv" / _venv_bin) + os.pathsep + os.environ.get("PATH", "")
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

import time
import socket
import argparse
import threading
import urllib.request
import webbrowser

# Ensure project root is first in sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a network port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def check_preflight_status():
    """Verify data dependencies and return system status summary."""
    status = {}
    
    # 1. Zarr Cube
    cube_path = PROJECT_ROOT / "data" / "processed" / "antarctic_cube.zarr"
    status["cube_present"] = cube_path.exists()
    status["cube_path"] = cube_path
    
    # 2. Iceberg Dataset
    berg_path = PROJECT_ROOT / "data" / "processed" / "bergs" / "tracked_icebergs_2017_2024.csv"
    status["berg_present"] = berg_path.exists()
    
    # 3. Checkpoints
    ckpt_best = PROJECT_ROOT / "results" / "checkpoints" / "best_model.pt"
    model_weights = PROJECT_ROOT / "results" / "models" / "unet_v1_weights.pt"
    status["model_present"] = ckpt_best.exists() or model_weights.exists()
    
    # 4. Web Frontend Assets
    index_html = PROJECT_ROOT / "web" / "index.html"
    status["web_present"] = index_html.exists()
    
    return status


def print_banner(host: str, port: int, status: dict):
    """Print clean terminal banner with URLs and diagnostic status."""
    display_host = "127.0.0.1" if host in ("127.0.0.1", "0.0.0.0") else host
    app_url = f"http://{display_host}:{port}"
    docs_url = f"http://{display_host}:{port}/docs"
    
    cube_str = "✓ Ready" if status["cube_present"] else "⚠ Missing (re-run as `python main.py --quick-synth`)"
    berg_str = "✓ Ready" if status["berg_present"] else "⚠ Fallback mode"
    model_str = "✓ Trained weights found" if status["model_present"] else "ℹ Baseline / synthetic mode"
    
    print("\n" + "=" * 66)
    print("   ❄  CryoNav — Antarctic Navigation Decision Support System")
    print("=" * 66)
    print(f"  ► Web Application:   {app_url}")
    print(f"  ► API Documentation: {docs_url}")
    print("  ─────────────────────────────────────────────────────────────")
    print("  Starting… loading model + data cube (~20 s). The browser opens")
    print("  by itself once the server is actually answering.")
    print("  ─────────────────────────────────────────────────────────────")
    print(f"  • Data Cube:        {cube_str}")
    print(f"  • Iceberg Tracks:   {berg_str}")
    print(f"  • Forecast Model:   {model_str}")
    print("  ─────────────────────────────────────────────────────────────")
    print("  Press Ctrl+C to shut down.")
    print("=" * 66 + "\n")


def open_browser_when_ready(url: str, check_url: str, timeout: float = 180.0):
    """
    Poll the server until it actually answers, then launch the browser.

    Cold start is dominated by imports (torch ~8 s, xarray/uvicorn ~5 s) plus
    opening the Zarr cube, so a real-data start takes ~20 s and considerably
    longer on a slower machine. The browser is NEVER opened speculatively: an
    early open lands on a connection-refused page that looks like a crash.
    """
    def _target():
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                req = urllib.request.Request(check_url, headers={"User-Agent": "CryoNav-Preflight"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        time.sleep(0.3)
                        webbrowser.open(url)
                        return
            except Exception:
                time.sleep(0.3)
        print(f"\n[CryoNav] Server did not answer within {timeout:.0f}s; "
              f"not opening a browser.\n           Once the log shows "
              f"'Application startup complete', open {url} yourself.")

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()


def main():
    parser = argparse.ArgumentParser(
        description="CryoNav — Full Stack Antarctic Navigation System"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("HOST", "127.0.0.1"),
        help="Host interface to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Bind to 0.0.0.0 for LAN / remote access",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8000)),
        help="Port to serve on (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code modifications",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Disable automatic opening of default web browser",
    )
    parser.add_argument(
        "--quick-synth",
        action="store_true",
        help="Automatically generate a synthetic data cube if missing",
    )

    args = parser.parse_args()

    # Preflight inspection
    status = check_preflight_status()
    
    # Auto-generate synthetic cube if requested and missing
    if not status["cube_present"] and args.quick_synth:
        print("Data cube missing. Generating quick synthetic test cube...")
        from src.data.synthetic import build_synthetic_cube
        # Same range as `python src/data/synthetic.py --quick`: ~120 days covering
        # the demo date the web UI opens on.
        build_synthetic_cube(start_date="2022-12-01", end_date="2023-03-31")
        status = check_preflight_status()

    bind_host = "0.0.0.0" if args.public else args.host
    display_host = "127.0.0.1" if bind_host in ("127.0.0.1", "0.0.0.0") else bind_host
    app_url = f"http://{display_host}:{args.port}"
    check_url = f"http://127.0.0.1:{args.port}/"

    # Print startup banner
    print_banner(bind_host, args.port, status)

    # Launch browser only after server is fully responding
    if not args.no_browser and not os.environ.get("CI") and not args.reload:
        open_browser_when_ready(app_url, check_url=check_url, timeout=15.0)

    try:
        import uvicorn
        from src.api.main import app
        
        uvicorn.run(
            "src.api.main:app" if args.reload else app,
            host=bind_host,
            port=args.port,
            reload=args.reload,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\n[CryoNav] Server stopped cleanly. Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
