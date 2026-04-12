#!/usr/bin/env bash
#
# Set up Azure ML workspace + compute for hyperparameter sweeps.
#
# Prerequisites:
#   - Azure CLI + ml extension: az extension add -n ml
#   - Logged in: az login
#
# Usage:
#   chmod +x deploy/azure-ml-setup.sh
#   ./deploy/azure-ml-setup.sh
#
# Cost: ~$0 when idle (compute auto-scales to 0).
#        ~$3-5 per sweep (4x Standard_DS3_v2 for ~1-2 hours).

set -euo pipefail

RESOURCE_GROUP="cycling-predictor-rg"
LOCATION="uksouth"
WORKSPACE="cycling-predictor-ml"
COMPUTE_NAME="cycling-sweep-cpu"
ENVIRONMENT_NAME="cycling-predictor-env"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Azure ML — Cycling Predictor Sweep Setup               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Ensure resource group exists ──────────────────────────────────
echo "▶ Ensuring resource group..."
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

# ── 2. Create ML Workspace ───────────────────────────────────────────
echo "▶ Creating Azure ML workspace..."
az ml workspace create \
  --name "$WORKSPACE" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none 2>/dev/null || echo "  (workspace already exists)"

# ── 3. Create Compute Cluster (auto-scales 0→4) ─────────────────────
echo "▶ Creating compute cluster (0-4 nodes, Standard_DS3_v2)..."
az ml compute create \
  --name "$COMPUTE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$WORKSPACE" \
  --type amlcompute \
  --size Standard_DS3_v2 \
  --min-instances 0 \
  --max-instances 4 \
  --idle-time-before-scale-down 300 \
  --output none 2>/dev/null || echo "  (compute already exists)"

# ── 4. Create Conda Environment ──────────────────────────────────────
echo "▶ Creating ML environment..."

# Write environment spec
cat > /tmp/cycling-env.yml <<'EOF'
$schema: https://azuremlschemas.azureedge.net/latest/environment.schema.json
name: cycling-predictor-env
description: Training environment for cycling H2H predictor
image: mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04
conda_file:
  name: cycling-predictor
  channels:
    - defaults
    - conda-forge
  dependencies:
    - python=3.11
    - pip
    - pip:
      - pandas>=2.0.0
      - numpy>=1.24.0
      - scikit-learn>=1.3.0
      - xgboost>=2.0.0
      - mlflow>=2.10.0
      - azureml-mlflow>=1.55.0
      - cloudscraper>=1.2.71
      - beautifulsoup4>=4.12.0
      - joblib>=1.3.0
      - requests>=2.31.0
EOF

az ml environment create \
  --file /tmp/cycling-env.yml \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$WORKSPACE" \
  --output none 2>/dev/null || echo "  (environment version already exists)"

rm -f /tmp/cycling-env.yml

# ── 5. Print summary ─────────────────────────────────────────────────
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅  Azure ML Setup Complete!                            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Workspace:    $WORKSPACE"
echo "Compute:      $COMPUTE_NAME (0-4 x Standard_DS3_v2, ~\$0.25/hr/node)"
echo "Environment:  $ENVIRONMENT_NAME"
echo ""
echo "━━━ Cost estimate per sweep ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  36 trials × 4 concurrent × ~20 min each = ~3 hours compute"
echo "  Cost: ~\$3-5 per sweep (nodes scale to 0 when idle)"
echo ""
echo "━━━ Run a sweep ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  # Set env vars (or use az login)"
echo "  export AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID"
echo "  export AZURE_RESOURCE_GROUP=$RESOURCE_GROUP"
echo "  export AZURE_ML_WORKSPACE=$WORKSPACE"
echo ""
echo "  # Launch sweep"
echo "  python scripts/aml_sweep.py --max-trials 36"
echo ""
echo "  # Download best model from completed sweep"
echo "  python scripts/aml_sweep.py --download-best"
echo ""
echo "━━━ GitHub Actions secrets (add these for CI sweeps) ━━━━"
echo ""
echo "  AZURE_ML_WORKSPACE: $WORKSPACE"
echo "  gh secret set AZURE_ML_WORKSPACE --body \"$WORKSPACE\""
