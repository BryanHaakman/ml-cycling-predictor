#!/usr/bin/env bash
#
# One-time setup for Azure Container Apps deployment.
#
# Prerequisites:
#   - Azure CLI installed (https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
#   - Logged in: az login
#   - Free-tier subscription active
#
# Usage:
#   chmod +x deploy/azure-setup.sh
#   ./deploy/azure-setup.sh
#
# After running this, configure GitHub repo secrets (see output).

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────
RESOURCE_GROUP="cycling-predictor-rg"
LOCATION="uksouth"
CONTAINER_ENV="cycling-predictor-env"
CONTAINER_APP="cycling-predictor"
CONTAINER_APP_STAGING="cycling-predictor-staging"
STORAGE_ACCOUNT="cyclingpredictordata"
STORAGE_CONTAINER="dbsnapshots"
APPINSIGHTS_NAME="cycling-predictor-ai"
LOG_ANALYTICS="cycling-predictor-logs"
GHCR_IMAGE="ghcr.io/$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null || echo 'OWNER/cycling-predictor')"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Azure Container Apps — Cycling Predictor Setup         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Resource Group:    $RESOURCE_GROUP"
echo "Location:          $LOCATION"
echo "Container Env:     $CONTAINER_ENV"
echo "Container App:     $CONTAINER_APP (prod) / $CONTAINER_APP_STAGING (staging)"
echo "Storage Account:   $STORAGE_ACCOUNT"
echo "App Insights:      $APPINSIGHTS_NAME"
echo ""

# ── 1. Resource Group ─────────────────────────────────────────────────
echo "▶ Creating resource group..."
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

# ── 2. Log Analytics Workspace (required for App Insights + Container Env) ─
echo "▶ Creating Log Analytics workspace..."
az monitor log-analytics workspace create \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_ANALYTICS" \
  --location "$LOCATION" \
  --output none

LOG_ANALYTICS_ID=$(az monitor log-analytics workspace show \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_ANALYTICS" \
  --query customerId -o tsv)

LOG_ANALYTICS_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_ANALYTICS" \
  --query primarySharedKey -o tsv)

# ── 3. Application Insights ──────────────────────────────────────────
echo "▶ Creating Application Insights..."
az monitor app-insights component create \
  --app "$APPINSIGHTS_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --workspace "$LOG_ANALYTICS" \
  --kind web \
  --output none

APPINSIGHTS_KEY=$(az monitor app-insights component show \
  --app "$APPINSIGHTS_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query connectionString -o tsv)

# ── 4. Blob Storage (for DB snapshots) ───────────────────────────────
echo "▶ Creating storage account..."
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --output none

STORAGE_KEY=$(az storage account keys list \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --query "[0].value" -o tsv)

az storage container create \
  --name "$STORAGE_CONTAINER" \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY" \
  --output none

STORAGE_CONN=$(az storage account show-connection-string \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --query connectionString -o tsv)

# ── 5. Container Apps Environment ─────────────────────────────────────
echo "▶ Creating Container Apps environment..."
az containerapp env create \
  --name "$CONTAINER_ENV" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --logs-workspace-id "$LOG_ANALYTICS_ID" \
  --logs-workspace-key "$LOG_ANALYTICS_KEY" \
  --output none

# ── 6. Production Container App ──────────────────────────────────────
echo "▶ Creating production container app (2 CPU / 4GB)..."
az containerapp create \
  --name "$CONTAINER_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$CONTAINER_ENV" \
  --image "mcr.microsoft.com/k8se/quickstart:latest" \
  --target-port 8000 \
  --ingress external \
  --cpu 2.0 \
  --memory 4.0Gi \
  --min-replicas 0 \
  --max-replicas 2 \
  --env-vars \
    "FLASK_ENV=production" \
    "APPLICATIONINSIGHTS_CONNECTION_STRING=$APPINSIGHTS_KEY" \
    "AZURE_STORAGE_CONNECTION_STRING=$STORAGE_CONN" \
  --output none

# ── 7. Staging Container App ─────────────────────────────────────────
echo "▶ Creating staging container app (1 CPU / 2GB)..."
az containerapp create \
  --name "$CONTAINER_APP_STAGING" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$CONTAINER_ENV" \
  --image "mcr.microsoft.com/k8se/quickstart:latest" \
  --target-port 8000 \
  --ingress external \
  --cpu 1.0 \
  --memory 2.0Gi \
  --min-replicas 0 \
  --max-replicas 1 \
  --env-vars \
    "FLASK_ENV=staging" \
    "APPLICATIONINSIGHTS_CONNECTION_STRING=$APPINSIGHTS_KEY" \
    "AZURE_STORAGE_CONNECTION_STRING=$STORAGE_CONN" \
  --output none

# ── 8. Create service principal for GitHub Actions OIDC ───────────────
echo "▶ Creating service principal for GitHub Actions..."
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

SP_OUTPUT=$(az ad app create --display-name "cycling-predictor-gh-actions" --query appId -o tsv)
APP_ID="$SP_OUTPUT"

az ad sp create --id "$APP_ID" --output none 2>/dev/null || true

# Assign Contributor role on the resource group
SP_OBJECT_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$SP_OBJECT_ID" \
  --assignee-principal-type ServicePrincipal \
  --role Contributor \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP" \
  --output none

# Configure OIDC federation for GitHub Actions
REPO_NAME=$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null || echo "OWNER/cycling-predictor")
az ad app federated-credential create \
  --id "$APP_ID" \
  --parameters "{
    \"name\": \"github-actions-deploy\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:${REPO_NAME}:ref:refs/heads/main\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" \
  --output none

az ad app federated-credential create \
  --id "$APP_ID" \
  --parameters "{
    \"name\": \"github-actions-environment\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:${REPO_NAME}:environment:production\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" \
  --output none 2>/dev/null || true

# ── 9. Get app URLs ──────────────────────────────────────────────────
PROD_URL=$(az containerapp show \
  --name "$CONTAINER_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv)

STAGING_URL=$(az containerapp show \
  --name "$CONTAINER_APP_STAGING" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅  Setup Complete!                                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Production URL:  https://$PROD_URL"
echo "Staging URL:     https://$STAGING_URL"
echo "App Insights:    https://portal.azure.com → $APPINSIGHTS_NAME"
echo "Blob Storage:    $STORAGE_ACCOUNT/$STORAGE_CONTAINER"
echo ""
echo "━━━ Estimated monthly cost ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Container Apps (prod, scale-to-zero):  ~\$30/mo"
echo "  Container Apps (staging, scale-to-zero): ~\$10/mo"
echo "  Application Insights:                  ~\$5/mo"
echo "  Blob Storage:                          ~\$1/mo"
echo "  Log Analytics:                         ~\$5/mo"
echo "  Total:                                 ~\$51/mo"
echo ""
echo "━━━ Add these GitHub repo secrets ━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  AZURE_CLIENT_ID:               $APP_ID"
echo "  AZURE_TENANT_ID:               $TENANT_ID"
echo "  AZURE_SUBSCRIPTION_ID:         $SUBSCRIPTION_ID"
echo "  AZURE_STORAGE_CONNECTION_STRING: (see below)"
echo ""
echo "Run:"
echo "  gh secret set AZURE_CLIENT_ID       --body \"$APP_ID\""
echo "  gh secret set AZURE_TENANT_ID       --body \"$TENANT_ID\""
echo "  gh secret set AZURE_SUBSCRIPTION_ID --body \"$SUBSCRIPTION_ID\""
echo "  gh secret set AZURE_STORAGE_CONNECTION_STRING --body \"$STORAGE_CONN\""
echo ""
echo "Then trigger a deploy:"
echo "  gh workflow run deploy.yml"
