#!/bin/bash
# CryoNav — Reproduce everything from scratch
# Run: bash scripts/reproduce_all.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT"

echo "========================================"
echo "  CryoNav — Full Reproduction Pipeline"
echo "========================================"

# 0. Activate venv
source .venv/bin/activate

# 1. Build data cube (synthetic if no real data)
echo ""
echo "Step 1: Building data cube..."
CUBE="$PROJECT_ROOT/data/processed/antarctic_cube.zarr"
if [ -d "$CUBE" ]; then
    echo "  Cube already present at $CUBE — skipping generation."
    echo "  (Delete it, or run synthetic.py --force, to rebuild.)"
else
    python src/data/synthetic.py
fi

# 2. Run baselines
echo ""
echo "Step 2: Evaluating baselines..."
python src/ice/baselines.py

# 3. Train model (quick test mode)
echo ""
echo "Step 3: Training U-Net (quick test)..."
python src/ice/train.py --quick-test

# 4. Run demo for all 3 dates
echo ""
echo "Step 4: Running demo sequence..."
python scripts/run_demo.py --all

echo ""
echo "========================================"
echo "  REPRODUCTION COMPLETE"
echo "  Results in: results/"
echo "  Demo in: results/demo/"
echo "========================================"
