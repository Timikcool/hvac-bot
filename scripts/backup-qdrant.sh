#!/bin/bash
set -e

# ═══════════════════════════════════════════════════════════════════════════════
# Qdrant Backup Script - Create local snapshots
# ═══════════════════════════════════════════════════════════════════════════════

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION="${QDRANT_COLLECTION:-hvac_manuals}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_BACKUPS="${KEEP_BACKUPS:-5}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

mkdir -p "$BACKUP_DIR"

echo -e "${BLUE}[INFO]${NC} Creating Qdrant snapshot..."

# Create snapshot
RESPONSE=$(curl -s -X POST "$QDRANT_URL/collections/$COLLECTION/snapshots")
SNAPSHOT_NAME=$(echo "$RESPONSE" | jq -r '.result.name')

if [ -z "$SNAPSHOT_NAME" ] || [ "$SNAPSHOT_NAME" == "null" ]; then
    echo "Error: Failed to create snapshot"
    echo "$RESPONSE"
    exit 1
fi

echo -e "${GREEN}[SUCCESS]${NC} Snapshot created: $SNAPSHOT_NAME"

# Download snapshot
BACKUP_FILE="$BACKUP_DIR/${COLLECTION}_$(date +%Y%m%d_%H%M%S).snapshot"
echo -e "${BLUE}[INFO]${NC} Downloading to $BACKUP_FILE..."

curl -s -o "$BACKUP_FILE" "$QDRANT_URL/collections/$COLLECTION/snapshots/$SNAPSHOT_NAME"

FILE_SIZE=$(ls -lh "$BACKUP_FILE" | awk '{print $5}')
echo -e "${GREEN}[SUCCESS]${NC} Backup saved: $BACKUP_FILE ($FILE_SIZE)"

# Cleanup old backups
COUNT=$(ls -1 "$BACKUP_DIR"/*.snapshot 2>/dev/null | wc -l)
if [ "$COUNT" -gt "$KEEP_BACKUPS" ]; then
    echo -e "${BLUE}[INFO]${NC} Cleaning up old backups (keeping last $KEEP_BACKUPS)..."
    ls -1t "$BACKUP_DIR"/*.snapshot | tail -n +$((KEEP_BACKUPS + 1)) | xargs rm -f
fi

# Show backup summary
echo ""
echo "Backups in $BACKUP_DIR:"
ls -lh "$BACKUP_DIR"/*.snapshot 2>/dev/null | tail -5


