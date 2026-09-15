"""
CryoNav — Strategy 1 Data Distribution, Hosting & Sync Tool.

Allows team members, collaborators, and evaluators to download the pre-compiled,
analysis-ready Zarr data cube and trained model checkpoints with a single command,
without needing individual API accounts for NASA Earthdata, Copernicus CDS, or CMEMS.

Supports downloading from Google Drive, Hugging Face Hub, or Direct HTTP mirrors.

Usage:
    # 1. Verification of local datasets
    python scripts/download_data.py --verify

    # 2. Download from Cloud Mirror (Google Drive / Hugging Face)
    python scripts/download_data.py --all
    python scripts/download_data.py --gdrive-id <FILE_ID>

    # 3. Package local cube for uploading to Google Drive
    python scripts/download_data.py --package
"""
import os
import sys
import shutil
import tarfile
import zipfile
import re
from pathlib import Path
import argparse
import urllib.request

# This script prints U+2713 / U+2717 / U+23F3. On Windows the console defaults
# to cp1252, which cannot encode them, so --verify died with UnicodeEncodeError
# mid-report - and then died again inside its own except: handler, which also
# prints a mark. Force UTF-8 where the runtime supports it.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import DOMAIN

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data/processed"
MODELS_DIR = PROJECT_ROOT / "results/models"
ZARR_PATH = PROJECT_ROOT / DOMAIN["paths"]["zarr_cube"]
PACKAGE_ARCHIVE = PROCESSED_DIR / "antarctic_cube_2017_2024.tar.gz"

# Default Hosted Storage Configuration (Google Drive / Hugging Face)
# When you upload to Google Drive, set GDRIVE_FILE_ID or pass --gdrive-id <ID>
DEFAULT_GDRIVE_FILE_ID = os.environ.get("CRYONAV_GDRIVE_ID", "")
DEFAULT_MIRROR_URLS = {
    "cube": "https://huggingface.co/datasets/cryonav/antarctic-sea-ice/resolve/main/antarctic_cube_2017_2024.tar.gz",
    "bergs": "https://huggingface.co/datasets/cryonav/antarctic-sea-ice/resolve/main/tracked_icebergs_2017_2024.parquet",
    "models": "https://huggingface.co/datasets/cryonav/antarctic-sea-ice/resolve/main/unet_v1_weights.pt",
}


def download_from_google_drive(file_id: str, destination: Path):
    """
    Download a file from Google Drive with large-file confirmation token handling.
    """
    try:
        import gdown
        print(f"Downloading from Google Drive ID: {file_id} via gdown...")
        url = f"https://drive.google.com/uc?id={file_id}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        gdown.download(url, str(destination), quiet=False)
        return True
    except ImportError:
        pass

    # Fallback to requests with cookies/session for confirmation token
    try:
        import requests
        print(f"Downloading from Google Drive ID: {file_id} ...")
        url = "https://docs.google.com/uc?export=download"
        session = requests.Session()
        response = session.get(url, params={"id": file_id}, stream=True)
        
        # Check for confirmation token
        token = None
        for key, value in response.cookies.items():
            if key.startswith("download_warning"):
                token = value
                break
        
        if token:
            params = {"id": file_id, "confirm": token}
            response = session.get(url, params=params, stream=True)
        
        destination.parent.mkdir(parents=True, exist_ok=True)
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        
        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024 * 4):  # 4MB chunks
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = int(downloaded * 100 / total_size)
                        mb = downloaded / (1024 * 1024)
                        tot_mb = total_size / (1024 * 1024)
                        sys.stdout.write(f"\r  [{'=' * (pct // 2)}{' ' * (50 - pct // 2)}] {pct}% ({mb:.1f}/{tot_mb:.1f} MB)")
                        sys.stdout.flush()
                    else:
                        mb = downloaded / (1024 * 1024)
                        sys.stdout.write(f"\r  Downloaded: {mb:.1f} MB...")
                        sys.stdout.flush()
        sys.stdout.write("\n")
        print(f"✓ Downloaded to {destination}")
        return True
    except Exception as e:
        print(f"✗ Google Drive download failed: {e}")
        return False


def download_file_with_progress(url: str, output_path: Path) -> bool:
    """Download a file via HTTP/HTTPS with a progress bar."""
    print(f"Downloading from {url} ...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def reporthook(count, block_size, total_size):
        if total_size > 0:
            percent = int(count * block_size * 100 / total_size)
            downloaded_mb = (count * block_size) / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            sys.stdout.write(f"\r  [{'=' * (percent // 2)}{' ' * (50 - percent // 2)}] {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)")
            sys.stdout.flush()

    try:
        urllib.request.urlretrieve(url, str(output_path), reporthook)
        sys.stdout.write("\n")
        print(f"✓ Downloaded to {output_path}")
        return True
    except Exception as e:
        sys.stdout.write("\n")
        print(f"✗ Failed to download: {e}")
        return False


def extract_archive(archive_path: Path, target_dir: Path, force: bool = False):
    """
    Extract .tar.gz or .zip file into target directory.

    Refuses to extract over an existing cube unless force=True. Zarr is a
    directory of chunk files, so a plain extractall on top of one merges the
    two: chunks the new cube does not overwrite survive from the old one and
    you get a silently mixed dataset (e.g. a 2738-day synthetic cube's tail
    left inside a 2922-day real one). With force, the existing cube is moved
    aside to <name>.bak first rather than deleted.
    """
    if ZARR_PATH.exists():
        if not force:
            print(f"Refusing to overwrite existing cube: {ZARR_PATH}")
            print("Pass --force to replace it (the old one is kept as .bak), "
                  "or --output PATH to extract elsewhere.")
            return False
        backup = ZARR_PATH.with_suffix(ZARR_PATH.suffix + ".bak")
        if backup.exists():
            shutil.rmtree(backup)
        print(f"Moving existing cube aside -> {backup.name}")
        shutil.move(str(ZARR_PATH), str(backup))

    print(f"Extracting {archive_path.name} to {target_dir} ...")
    target_dir.mkdir(parents=True, exist_ok=True)
    
    if archive_path.name.endswith(".tar.gz") or archive_path.name.endswith(".tgz"):
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=target_dir)
        print(f"✓ Extracted archive to {target_dir}")
        return True
    elif archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as z:
            z.extractall(path=target_dir)
        print(f"✓ Extracted archive to {target_dir}")
        return True
    else:
        print(f"Unknown archive format: {archive_path.name}")
        return False


def package_local_cube():
    """
    Compress local antarctic_cube.zarr into a single .tar.gz archive
    for easy upload to Google Drive or Hugging Face.
    """
    if not ZARR_PATH.exists():
        print(f"Error: {ZARR_PATH} does not exist. Run `python src/data/build_cube.py` first.")
        return False

    print("=" * 60)
    print("Packaging Processed Zarr Data Cube for Cloud Distribution")
    print(f"Source: {ZARR_PATH}")
    print(f"Target Archive: {PACKAGE_ARCHIVE}")
    print("=" * 60)

    try:
        with tarfile.open(PACKAGE_ARCHIVE, "w:gz") as tar:
            tar.add(ZARR_PATH, arcname=ZARR_PATH.name)
        
        size_gb = PACKAGE_ARCHIVE.stat().st_size / (1024 ** 3)
        print(f"\n✓ Successfully created compressed archive: {PACKAGE_ARCHIVE} ({size_gb:.2f} GB)")
        print("\nUpload Instructions for Google Drive:")
        print("1. Upload `data/processed/antarctic_cube_2017_2024.tar.gz` to your Google Drive.")
        print("2. Right click the file -> Share -> Change to 'Anyone with the link can view'.")
        print("3. Copy the File ID from the link (the alphanumeric string between /d/ and /view).")
        print("4. Team members can then download with:")
        print("   python scripts/download_data.py --gdrive-id <COPIED_FILE_ID>")
        return True
    except Exception as e:
        print(f"✗ Failed to create package: {e}")
        return False


def verify_local_data():
    """Verify local data integrity and print detailed summary."""
    print("=" * 60)
    print("CryoNav — Local Dataset Verification")
    print("=" * 60)

    # 1. Zarr Cube
    print(f"1. Processed Zarr Data Cube: {ZARR_PATH}")
    if ZARR_PATH.exists():
        try:
            import xarray as xr
            ds = xr.open_zarr(str(ZARR_PATH))
            print(f"   ✓ Valid Zarr Cube: dims={dict(ds.sizes)}, vars={len(ds.data_vars)}")
            print(f"   ✓ Time coverage: {str(ds.time.values[0])[:10]} to {str(ds.time.values[-1])[:10]} ({len(ds.time)} days)")
            if all(v in ds for v in ("sic_is_real", "atmo_is_real", "ocean_is_real")):
                print(f"   ✓ Real SIC: {float(ds.sic_is_real.mean())*100:.1f}% | Real ERA5: {float(ds.atmo_is_real.mean())*100:.1f}% | Real CMEMS: {float(ds.ocean_is_real.mean())*100:.1f}%")
            else:
                print("   ℹ Synthetic cube (no real-data provenance flags).")
            ds.close()
        except Exception as e:
            print(f"   ✗ Zarr cube found but error reading: {e}")
    else:
        print("   ✗ Not found. Run `python scripts/download_data.py --all` or `python src/data/build_cube.py`.")

    # 2. Icebergs Parquet
    berg_dir = PROCESSED_DIR / "bergs"
    berg_parquet = berg_dir / "tracked_icebergs_2017_2024.parquet"
    # The API reads the CSV (src/api/main.py), so accept either form here.
    berg_csv = berg_dir / "tracked_icebergs_2017_2024.csv"
    berg_file = berg_parquet if berg_parquet.exists() else berg_csv
    print(f"\n2. Tracked Icebergs Database: {berg_file}")
    if berg_file.exists():
        try:
            import pandas as pd
            df = (pd.read_parquet(berg_file) if berg_file.suffix == ".parquet"
                  else pd.read_csv(berg_file))
            print(f"   ✓ Valid Berg Trajectories: {df['berg_id'].nunique()} bergs, {len(df):,} observations")
        except Exception as e:
            print(f"   ✗ Error reading {berg_file.suffix.lstrip('.')}: {e}")
    else:
        print("   ℹ Not found — /bergs falls back to synthetic positions. "
              "Run `python src/berg/parse_byu.py` for real tracks.")

    # 3. Model Weights — best_model.pt ships with the repo and is what
    # src/ice/predict.py loads; unet_v1_weights.pt is an optional export.
    checkpoint = PROJECT_ROOT / "results" / "checkpoints" / "best_model.pt"
    weights_path = checkpoint if checkpoint.exists() else MODELS_DIR / "unet_v1_weights.pt"
    print(f"\n3. Forecast Model Checkpoint: {weights_path}")
    if weights_path.exists():
        print(f"   ✓ Model checkpoint available ({weights_path.stat().st_size / 1e6:.1f} MB)")
    else:
        print("   ⏳ Not trained yet. Run `python src/ice/train.py`.")

    # 4. Cached real forecasts — these make /forecast return source="model"
    cache_dir = PROCESSED_DIR / "demo_cache"
    cached = sorted(cache_dir.glob("forecast_*.npy")) if cache_dir.exists() else []
    print(f"\n4. Cached Model Forecasts: {cache_dir}")
    if cached:
        dates = ", ".join(f.stem.replace("forecast_", "") for f in cached)
        print(f"   ✓ {len(cached)} cached init dates: {dates}")
    else:
        print("   ⏳ None cached. /forecast will return observed_fallback. "
              "Generate with `python src/ice/predict.py`.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CryoNav Data Distribution & Cloud Sync Tool")
    parser.add_argument("--verify", action="store_true", help="Verify integrity of local dataset")
    parser.add_argument("--package", action="store_true", help="Package local Zarr cube into .tar.gz for Google Drive upload")
    parser.add_argument("--all", action="store_true", help="Download all processed data from default cloud mirror")
    parser.add_argument("--gdrive-id", type=str, default=None, help="Google Drive File ID of the antarctic_cube_2017_2024.tar.gz archive")
    # Both of these are documented in the README but were never implemented,
    # so the script silently extracted on top of whatever cube was already there.
    parser.add_argument("--force", action="store_true", help="Replace an existing cube (the old one is kept alongside as .bak)")
    parser.add_argument("--output", type=str, default=None, help="Extract into PATH instead of data/processed/")
    args = parser.parse_args()

    target_dir = Path(args.output).expanduser().resolve() if args.output else PROCESSED_DIR

    if args.package:
        package_local_cube()
    elif args.gdrive_id:
        target_archive = target_dir / "antarctic_cube_2017_2024.tar.gz"
        success = download_from_google_drive(args.gdrive_id, target_archive)
        if success:
            if extract_archive(target_archive, target_dir, force=args.force):
                verify_local_data()
    elif args.all:
        print("Syncing dataset from cloud mirror...")
        target_archive = target_dir / "antarctic_cube_2017_2024.tar.gz"
        if download_file_with_progress(DEFAULT_MIRROR_URLS["cube"], target_archive):
            if extract_archive(target_archive, target_dir, force=args.force):
                verify_local_data()
    else:
        verify_local_data()
