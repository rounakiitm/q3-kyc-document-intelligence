#!/usr/bin/env bash
# Deploy Q3 KYC API to Cloud Run (rounak-iitm / asia-south1).
# Run from WSL: bash scripts/deploy_cloudrun.sh
set -euo pipefail

GCLOUD="${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}"
PROJECT="${GCP_PROJECT:-rounak-iitm}"
REGION="${GCP_REGION:-asia-south1}"
SERVICE="${CLOUD_RUN_SERVICE:-q3-kyc-pipeline}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Project=$PROJECT Region=$REGION Service=$SERVICE"
"$GCLOUD" config set project "$PROJECT"

"$GCLOUD" services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT"

ENV_FILE="$ROOT/.env"
[[ -f "$ENV_FILE" ]] || { echo ".env missing"; exit 1; }

keys=""; model="gemini-3.1-flash-lite"; conf="0.70"
supabase_url=""; supabase_anon=""; supabase_service=""; auth_disabled="false"
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ "$line" =~ ^[[:space:]]*$ ]] && continue
  key="${line%%=*}"; val="${line#*=}"
  key="$(echo "$key" | xargs)"
  case "$key" in
    GEMINI_API_KEYS) keys="$val" ;;
    GEMINI_API_KEY) [[ -z "$keys" ]] && keys="$val" ;;
    MODEL_NAME) model="$val" ;;
    CONFIDENCE_THRESHOLD) conf="$val" ;;
    SUPABASE_URL) supabase_url="$val" ;;
    SUPABASE_ANON_KEY) supabase_anon="$val" ;;
    SUPABASE_SERVICE_ROLE_KEY) supabase_service="$val" ;;
    AUTH_DISABLED) auth_disabled="$val" ;;
  esac
done < "$ENV_FILE"

[[ -n "$keys" && "$keys" != "your_key_here" ]] || { echo "GEMINI_API_KEYS missing"; exit 1; }

SECRET_NAME="q3-gemini-api-keys"
tmp="$(mktemp)"
printf '%s' "$keys" > "$tmp"
if ! "$GCLOUD" secrets describe "$SECRET_NAME" --project "$PROJECT" >/dev/null 2>&1; then
  "$GCLOUD" secrets create "$SECRET_NAME" --replication-policy=automatic --project "$PROJECT"
fi
"$GCLOUD" secrets versions add "$SECRET_NAME" --data-file="$tmp" --project "$PROJECT" >/dev/null
rm -f "$tmp"

PROJECT_NUMBER="$("$GCLOUD" projects describe "$PROJECT" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
"$GCLOUD" secrets add-iam-policy-binding "$SECRET_NAME" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project "$PROJECT" >/dev/null

# Pack env (no secrets in plain text for Gemini keys)
ENV_VARS="MODEL_NAME=${model},CONFIDENCE_THRESHOLD=${conf},SAMPLE_INPUT_DIR=/app/samples,AUTH_DISABLED=${auth_disabled}"
[[ -n "$supabase_url" ]] && ENV_VARS+=",SUPABASE_URL=${supabase_url}"
[[ -n "$supabase_anon" ]] && ENV_VARS+=",SUPABASE_ANON_KEY=${supabase_anon}"
[[ -n "$supabase_service" ]] && ENV_VARS+=",SUPABASE_SERVICE_ROLE_KEY=${supabase_service}"

echo "Building and deploying…"
"$GCLOUD" run deploy "$SERVICE" \
  --source "$ROOT" \
  --region "$REGION" \
  --project "$PROJECT" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 2 \
  --memory 2Gi \
  --timeout 3600 \
  --concurrency 10 \
  --max-instances 2 \
  --cpu-boost \
  --execution-environment gen2 \
  --set-secrets "GEMINI_API_KEYS=${SECRET_NAME}:latest" \
  --set-env-vars "$ENV_VARS" \
  --quiet

URL="$("$GCLOUD" run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
echo ""
echo "Deployed: $URL"
echo "Health:   $URL/health"
echo "$URL" > "$ROOT/.cloudrun_url"
