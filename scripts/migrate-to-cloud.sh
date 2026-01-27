#!/bin/bash
set -e

# ═══════════════════════════════════════════════════════════════════════════════
# HVAC Bot - Local to Cloud Migration Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# Development Workflow:
#   1. Develop locally (add books, tune prompts, test)
#   2. Run this script to push to cloud
#
# Usage:
#   ./scripts/migrate-to-cloud.sh [command] [options]
#
# Commands:
#   all        - Sync everything (default)
#   qdrant     - Sync vector database only
#   postgres   - Sync PostgreSQL only (merge mode)
#   status     - Check local and cloud status
#   config     - Edit cloud configuration
#
# Options:
#   --replace  - Replace cloud data instead of merging (destructive!)
#   --dry-run  - Show what would be synced without making changes
#
# ═══════════════════════════════════════════════════════════════════════════════

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration - UPDATE THESE FOR YOUR CLOUD SETUP
CLOUD_CONFIG_FILE="$(dirname "$0")/../.cloud-config"
SCRIPT_DIR="$(dirname "$0")"

# Default local settings
LOCAL_QDRANT_URL="http://localhost:6333"
LOCAL_POSTGRES_URL="postgresql://hvac_user:hvac_password@localhost:5432/hvac_bot"
QDRANT_COLLECTION="hvac_manuals"

# Sync mode flags
REPLACE_MODE=false
DRY_RUN=false
AUTO_YES=false

# Load from .env first (supports QDRANT_API_KEY, QDRANT_API_ENDPOINT naming)
ENV_FILE="$(dirname "$0")/../backend/.env"
if [ -f "$ENV_FILE" ]; then
    # Parse .env without executing (safer)
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ $key =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        # Remove quotes from value
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        export "$key=$value" 2>/dev/null || true
    done < "$ENV_FILE"
fi

# Load cloud config (can override .env values)
if [ -f "$CLOUD_CONFIG_FILE" ]; then
    source "$CLOUD_CONFIG_FILE"
fi

# Map alternative variable names (prioritize QDRANT_API_* from .env)
if [ -n "$QDRANT_API_ENDPOINT" ]; then
    CLOUD_QDRANT_URL="$QDRANT_API_ENDPOINT"
fi
if [ -n "$QDRANT_API_KEY" ]; then
    CLOUD_QDRANT_API_KEY="$QDRANT_API_KEY"
fi

# Parse command line options
parse_options() {
    for arg in "$@"; do
        case $arg in
            --replace)
                REPLACE_MODE=true
                ;;
            --dry-run)
                DRY_RUN=true
                ;;
            --yes|-y)
                AUTO_YES=true
                ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    if ! command -v $1 &> /dev/null; then
        log_error "$1 is required but not installed."
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration Check
# ═══════════════════════════════════════════════════════════════════════════════

check_config() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  HVAC Bot Migration - Configuration Check"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    
    if [ ! -f "$CLOUD_CONFIG_FILE" ]; then
        log_warn "Cloud config not found. Creating template..."
        create_config_template
        log_info "Please edit $CLOUD_CONFIG_FILE with your cloud credentials"
        exit 1
    fi
    
    # Check required variables
    local missing=0
    
    if [ -z "$CLOUD_QDRANT_URL" ]; then
        log_error "CLOUD_QDRANT_URL not set"
        missing=1
    else
        log_success "Qdrant Cloud: $CLOUD_QDRANT_URL"
    fi
    
    if [ -z "$CLOUD_QDRANT_API_KEY" ]; then
        log_error "CLOUD_QDRANT_API_KEY not set"
        missing=1
    else
        log_success "Qdrant API Key: ****${CLOUD_QDRANT_API_KEY: -4}"
    fi
    
    if [ -z "$CLOUD_POSTGRES_URL" ]; then
        log_warn "CLOUD_POSTGRES_URL not set (PostgreSQL migration disabled)"
    else
        log_success "PostgreSQL Cloud: ${CLOUD_POSTGRES_URL%%@*}@****"
    fi
    
    if [ $missing -eq 1 ]; then
        log_error "Missing required configuration. Edit $CLOUD_CONFIG_FILE"
        exit 1
    fi
    
    echo ""
}

create_config_template() {
    cat > "$CLOUD_CONFIG_FILE" << 'EOF'
# ═══════════════════════════════════════════════════════════════════════════════
# Cloud Configuration for HVAC Bot Migration
# ═══════════════════════════════════════════════════════════════════════════════

# Qdrant Cloud (https://cloud.qdrant.io)
# Get these from your Qdrant Cloud dashboard
CLOUD_QDRANT_URL="https://your-cluster-id.us-east4-0.gcp.cloud.qdrant.io:6333"
CLOUD_QDRANT_API_KEY="your-qdrant-api-key"

# PostgreSQL Cloud (Supabase, Railway, Render, etc.)
# Format: postgresql://user:password@host:port/database
CLOUD_POSTGRES_URL="postgresql://user:password@db.example.com:5432/hvac_bot"

# Optional: Backup settings
BACKUP_DIR="./backups"
KEEP_BACKUPS=5
EOF
    chmod 600 "$CLOUD_CONFIG_FILE"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Qdrant Migration
# ═══════════════════════════════════════════════════════════════════════════════

migrate_qdrant() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  Syncing Qdrant: $QDRANT_COLLECTION"
    if [ "$REPLACE_MODE" = true ]; then
        echo "  Mode: REPLACE (will overwrite cloud)"
    else
        echo "  Mode: MERGE (will add new documents only)"
    fi
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    
    check_command curl
    check_command jq
    
    BACKUP_DIR="${BACKUP_DIR:-./backups}"
    mkdir -p "$BACKUP_DIR"
    
    # Step 1: Check local Qdrant
    log_info "Checking local Qdrant..."
    local local_info=$(curl -s "$LOCAL_QDRANT_URL/collections/$QDRANT_COLLECTION")
    local local_vectors=$(echo "$local_info" | jq -r '.result.points_count // .result.vectors_count // 0')
    
    if [ "$local_vectors" == "0" ] || [ "$local_vectors" == "null" ]; then
        log_error "Local collection '$QDRANT_COLLECTION' is empty or doesn't exist"
        exit 1
    fi
    
    log_success "Local collection has $local_vectors vectors"
    
    # Step 2: Get local documents list
    log_info "Getting local documents..."
    local local_docs=$(curl -s -X POST "$LOCAL_QDRANT_URL/collections/$QDRANT_COLLECTION/points/scroll" \
        -H "Content-Type: application/json" \
        -d '{"limit": 10000, "with_payload": {"include": ["document_id", "title"]}, "with_vector": false}' \
        | jq -r '[.result.points[].payload | {document_id, title}] | unique_by(.document_id)')
    
    local local_doc_ids=$(echo "$local_docs" | jq -r '.[].document_id' | sort -u)
    local local_doc_count=$(echo "$local_doc_ids" | grep -c . || echo 0)
    log_success "Found $local_doc_count unique documents locally"
    
    # Step 3: Check cloud collection
    log_info "Checking cloud Qdrant..."
    local cloud_check=$(curl -s -H "api-key: $CLOUD_QDRANT_API_KEY" \
        "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION")
    
    local cloud_exists=false
    local cloud_vectors=0
    local cloud_doc_ids=""
    
    if echo "$cloud_check" | jq -e '.result.status' > /dev/null 2>&1; then
        cloud_exists=true
        cloud_vectors=$(echo "$cloud_check" | jq -r '.result.points_count // .result.vectors_count // 0')
        log_success "Cloud collection has $cloud_vectors vectors"
        
        # Get cloud documents
        local cloud_docs=$(curl -s -X POST \
            -H "api-key: $CLOUD_QDRANT_API_KEY" \
            -H "Content-Type: application/json" \
            "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION/points/scroll" \
            -d '{"limit": 10000, "with_payload": {"include": ["document_id", "title"]}, "with_vector": false}' \
            | jq -r '[.result.points[].payload | {document_id, title}] | unique_by(.document_id)')
        
        cloud_doc_ids=$(echo "$cloud_docs" | jq -r '.[].document_id' | sort -u)
    else
        log_info "Cloud collection doesn't exist yet"
    fi
    
    # Step 4: Determine what needs to be synced
    if [ "$REPLACE_MODE" = true ]; then
        # Full replace mode
        log_warn "REPLACE MODE: Will overwrite all cloud data"
        
        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would upload all $local_vectors vectors"
            return
        fi
        
        if [ "$AUTO_YES" != true ]; then
            read -p "This will DELETE all cloud data. Continue? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "Aborted."
                return
            fi
        fi
        
        # Delete and recreate
        if [ "$cloud_exists" = true ]; then
            log_info "Deleting existing cloud collection..."
            curl -s -X DELETE -H "api-key: $CLOUD_QDRANT_API_KEY" \
                "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION" > /dev/null
            sleep 2
        fi
        
        # Create snapshot and upload
        sync_full_collection
    else
        # Merge mode - only sync new documents
        log_info "Comparing documents..."
        
        # Find documents that exist locally but not in cloud
        local new_docs=""
        for doc_id in $local_doc_ids; do
            if ! echo "$cloud_doc_ids" | grep -q "^${doc_id}$"; then
                local title=$(echo "$local_docs" | jq -r ".[] | select(.document_id == \"$doc_id\") | .title")
                new_docs="$new_docs$doc_id|$title\n"
            fi
        done
        
        if [ -z "$new_docs" ]; then
            log_success "All documents already in cloud. Nothing to sync!"
            show_sync_summary "$local_vectors" "$cloud_vectors" 0
            return
        fi
        
        local new_count=$(echo -e "$new_docs" | grep -c . || echo 0)
        
        echo ""
        echo "┌─────────────────────────────────────────┐"
        echo "│  New Documents to Sync                  │"
        echo "├─────────────────────────────────────────┤"
        echo -e "$new_docs" | while IFS='|' read -r id title; do
            [ -n "$id" ] && printf "│  • %-36s │\n" "${title:0:36}"
        done
        echo "└─────────────────────────────────────────┘"
        echo ""
        
        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would sync $new_count new documents"
            return
        fi
        
        if [ "$AUTO_YES" != true ]; then
            read -p "Sync $new_count new documents to cloud? (Y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Nn]$ ]]; then
                log_info "Aborted."
                return
            fi
        fi
        
        # Sync only new documents
        sync_new_documents "$new_docs"
    fi
}

sync_full_collection() {
    # Create snapshot
    log_info "Creating snapshot..."
    local snapshot_response=$(curl -s -X POST "$LOCAL_QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots")
    local snapshot_name=$(echo "$snapshot_response" | jq -r '.result.name')
    
    if [ -z "$snapshot_name" ] || [ "$snapshot_name" == "null" ]; then
        log_error "Failed to create snapshot: $snapshot_response"
        exit 1
    fi
    
    log_success "Snapshot created: $snapshot_name"
    
    # Download snapshot
    log_info "Downloading snapshot..."
    local snapshot_file="$BACKUP_DIR/${QDRANT_COLLECTION}_$(date +%Y%m%d_%H%M%S).snapshot"
    curl -s -o "$snapshot_file" "$LOCAL_QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots/$snapshot_name"
    
    local file_size=$(ls -lh "$snapshot_file" | awk '{print $5}')
    log_success "Downloaded: $snapshot_file ($file_size)"
    
    # Upload to cloud
    log_info "Uploading snapshot to cloud (this may take a while)..."
    local upload_response=$(curl -s -X POST \
        -H "api-key: $CLOUD_QDRANT_API_KEY" \
        -H "Content-Type: multipart/form-data" \
        -F "snapshot=@$snapshot_file" \
        "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots/upload?priority=snapshot")
    
    if echo "$upload_response" | jq -e '.result' > /dev/null 2>&1; then
        log_success "Snapshot uploaded successfully!"
    else
        log_error "Upload failed: $upload_response"
        exit 1
    fi
    
    # Verify
    sleep 2
    local cloud_info=$(curl -s -H "api-key: $CLOUD_QDRANT_API_KEY" \
        "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION")
    local final_vectors=$(echo "$cloud_info" | jq -r '.result.points_count // .result.vectors_count // 0')

    show_sync_summary "$local_vectors" "$final_vectors" "$local_vectors"
    
    cleanup_backups "$BACKUP_DIR" "*.snapshot"
}

sync_new_documents() {
    local new_docs=$1
    local synced=0
    
    echo -e "$new_docs" | while IFS='|' read -r doc_id title; do
        [ -z "$doc_id" ] && continue
        
        log_info "Syncing: $title..."
        
        # Get all points for this document
        local points=$(curl -s -X POST "$LOCAL_QDRANT_URL/collections/$QDRANT_COLLECTION/points/scroll" \
            -H "Content-Type: application/json" \
            -d "{\"filter\": {\"must\": [{\"key\": \"document_id\", \"match\": {\"value\": \"$doc_id\"}}]}, \"limit\": 10000, \"with_payload\": true, \"with_vector\": true}" \
            | jq '.result.points')
        
        local point_count=$(echo "$points" | jq 'length')
        
        if [ "$point_count" -gt 0 ]; then
            # Ensure cloud collection exists with correct config
            ensure_cloud_collection
            
            # Upload points in batches
            echo "$points" | jq -c '.[]' | while read -r point; do
                # Batch upload (collect 100 at a time for efficiency)
                :
            done
            
            # Upload all points at once
            local upsert_response=$(curl -s -X PUT \
                -H "api-key: $CLOUD_QDRANT_API_KEY" \
                -H "Content-Type: application/json" \
                "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION/points?wait=true" \
                -d "{\"points\": $points}")
            
            if echo "$upsert_response" | jq -e '.result' > /dev/null 2>&1; then
                log_success "  Synced $point_count chunks"
                synced=$((synced + point_count))
            else
                log_error "  Failed: $upsert_response"
            fi
        fi
    done
    
    # Final verification
    sleep 2
    local cloud_info=$(curl -s -H "api-key: $CLOUD_QDRANT_API_KEY" \
        "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION")
    local final_vectors=$(echo "$cloud_info" | jq -r '.result.points_count // .result.vectors_count // 0')

    show_sync_summary "$local_vectors" "$final_vectors" "$synced"
}

ensure_cloud_collection() {
    local cloud_check=$(curl -s -H "api-key: $CLOUD_QDRANT_API_KEY" \
        "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION")
    
    if ! echo "$cloud_check" | jq -e '.result.status' > /dev/null 2>&1; then
        log_info "Creating cloud collection..."
        
        # Get local collection config
        local local_config=$(curl -s "$LOCAL_QDRANT_URL/collections/$QDRANT_COLLECTION")
        local vector_size=$(echo "$local_config" | jq -r '.result.config.params.vectors.size')
        local distance=$(echo "$local_config" | jq -r '.result.config.params.vectors.distance')
        
        curl -s -X PUT \
            -H "api-key: $CLOUD_QDRANT_API_KEY" \
            -H "Content-Type: application/json" \
            "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION" \
            -d "{\"vectors\": {\"size\": $vector_size, \"distance\": \"$distance\"}}" > /dev/null
        
        sleep 2
    fi
}

show_sync_summary() {
    local local_count=$1
    local cloud_count=$2
    local synced_count=$3
    
    echo ""
    echo "┌─────────────────────────────────────────┐"
    echo "│  Sync Complete                          │"
    echo "├─────────────────────────────────────────┤"
    printf "│  Local vectors:  %'10d             │\n" $local_count
    printf "│  Cloud vectors:  %'10d             │\n" $cloud_count
    printf "│  Synced:         %'10d             │\n" $synced_count
    echo "└─────────────────────────────────────────┘"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# PostgreSQL Migration
# ═══════════════════════════════════════════════════════════════════════════════

migrate_postgres() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  Syncing PostgreSQL Database"
    if [ "$REPLACE_MODE" = true ]; then
        echo "  Mode: REPLACE (will overwrite cloud)"
    else
        echo "  Mode: MERGE (conversations + feedback preserved)"
    fi
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    
    if [ -z "$CLOUD_POSTGRES_URL" ]; then
        log_warn "CLOUD_POSTGRES_URL not configured. Skipping PostgreSQL sync."
        return
    fi
    
    check_command psql
    
    BACKUP_DIR="${BACKUP_DIR:-./backups}"
    mkdir -p "$BACKUP_DIR"
    
    # Step 1: Get counts from both databases
    log_info "Comparing databases..."
    
    local local_convs=$(psql "$LOCAL_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM conversations" 2>/dev/null | tr -d ' ')
    local local_msgs=$(psql "$LOCAL_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM messages" 2>/dev/null | tr -d ' ')
    local local_feedback=$(psql "$LOCAL_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM message_feedback" 2>/dev/null | tr -d ' ')
    
    local cloud_convs=$(psql "$CLOUD_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM conversations" 2>/dev/null | tr -d ' ')
    local cloud_msgs=$(psql "$CLOUD_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM messages" 2>/dev/null | tr -d ' ')
    local cloud_feedback=$(psql "$CLOUD_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM message_feedback" 2>/dev/null | tr -d ' ')
    
    echo ""
    echo "┌────────────────────────────────────────────────────┐"
    echo "│  Database Comparison                               │"
    echo "├────────────────────────────────────────────────────┤"
    printf "│  %-20s  %8s  %8s          │\n" "" "Local" "Cloud"
    printf "│  %-20s  %8s  %8s          │\n" "Conversations" "$local_convs" "$cloud_convs"
    printf "│  %-20s  %8s  %8s          │\n" "Messages" "$local_msgs" "$cloud_msgs"
    printf "│  %-20s  %8s  %8s          │\n" "Feedback" "$local_feedback" "$cloud_feedback"
    echo "└────────────────────────────────────────────────────┘"
    echo ""
    
    if [ "$REPLACE_MODE" = true ]; then
        # Full replace mode
        log_warn "REPLACE MODE: Will overwrite all cloud data"
        
        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would replace cloud database"
            return
        fi
        
        if [ "$AUTO_YES" != true ]; then
            read -p "This will DELETE all cloud conversations/feedback. Continue? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "Aborted."
                return
            fi
        fi
        
        # Backup cloud first
        log_info "Backing up cloud database first..."
        local cloud_backup="$BACKUP_DIR/cloud_backup_$(date +%Y%m%d_%H%M%S).sql"
        pg_dump "$CLOUD_POSTGRES_URL" --no-owner --no-acl > "$cloud_backup" 2>/dev/null || true
        
        # Full dump and restore
        local dump_file="$BACKUP_DIR/hvac_bot_$(date +%Y%m%d_%H%M%S).sql"
        pg_dump "$LOCAL_POSTGRES_URL" --no-owner --no-acl > "$dump_file"
        psql "$CLOUD_POSTGRES_URL" < "$dump_file"
        
        log_success "PostgreSQL replaced!"
    else
        # Merge mode - sync local records that don't exist in cloud
        log_info "Merge mode: Will sync new local records to cloud"
        log_info "Cloud data will NOT be deleted"
        
        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would merge local records to cloud"
            return
        fi
        
        # Find conversations in local that don't exist in cloud
        log_info "Finding new local conversations..."
        local new_conv_ids=$(psql "$LOCAL_POSTGRES_URL" -t -c "
            SELECT id FROM conversations 
            WHERE id NOT IN (
                SELECT id FROM dblink(
                    '$CLOUD_POSTGRES_URL',
                    'SELECT id FROM conversations'
                ) AS t(id UUID)
            )
        " 2>/dev/null | tr -d ' ' | grep -v '^$' || echo "")
        
        if [ -z "$new_conv_ids" ]; then
            log_success "No new conversations to sync"
        else
            local new_count=$(echo "$new_conv_ids" | wc -l | tr -d ' ')
            log_info "Found $new_count new conversations to sync"
            
            if [ "$AUTO_YES" != true ]; then
                read -p "Sync $new_count conversations to cloud? (Y/n) " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Nn]$ ]]; then
                    log_info "Aborted."
                    return
                fi
            fi
            
            # Export and import new conversations with their messages and feedback
            for conv_id in $new_conv_ids; do
                [ -z "$conv_id" ] && continue
                log_info "Syncing conversation $conv_id..."
                
                # Export conversation
                psql "$LOCAL_POSTGRES_URL" -c "COPY (SELECT * FROM conversations WHERE id = '$conv_id') TO STDOUT" | \
                    psql "$CLOUD_POSTGRES_URL" -c "COPY conversations FROM STDIN" 2>/dev/null
                
                # Export messages
                psql "$LOCAL_POSTGRES_URL" -c "COPY (SELECT * FROM messages WHERE conversation_id = '$conv_id') TO STDOUT" | \
                    psql "$CLOUD_POSTGRES_URL" -c "COPY messages FROM STDIN" 2>/dev/null
                
                # Export feedback for those messages
                psql "$LOCAL_POSTGRES_URL" -c "COPY (SELECT mf.* FROM message_feedback mf JOIN messages m ON mf.message_id = m.id WHERE m.conversation_id = '$conv_id') TO STDOUT" | \
                    psql "$CLOUD_POSTGRES_URL" -c "COPY message_feedback FROM STDIN" 2>/dev/null
            done
            
            log_success "Conversations synced!"
        fi
    fi
    
    # Final counts
    local final_cloud_convs=$(psql "$CLOUD_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM conversations" 2>/dev/null | tr -d ' ')
    local final_cloud_msgs=$(psql "$CLOUD_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM messages" 2>/dev/null | tr -d ' ')
    local final_cloud_feedback=$(psql "$CLOUD_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM message_feedback" 2>/dev/null | tr -d ' ')
    
    echo ""
    echo "┌────────────────────────────────────────────────────┐"
    echo "│  Sync Complete                                     │"
    echo "├────────────────────────────────────────────────────┤"
    printf "│  Cloud conversations:  %8s                    │\n" "$final_cloud_convs"
    printf "│  Cloud messages:       %8s                    │\n" "$final_cloud_msgs"
    printf "│  Cloud feedback:       %8s                    │\n" "$final_cloud_feedback"
    echo "└────────────────────────────────────────────────────┘"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════════

cleanup_backups() {
    local dir=$1
    local pattern=$2
    local keep=${KEEP_BACKUPS:-5}
    
    local count=$(ls -1 "$dir"/$pattern 2>/dev/null | wc -l)
    if [ "$count" -gt "$keep" ]; then
        log_info "Cleaning up old backups (keeping last $keep)..."
        ls -1t "$dir"/$pattern | tail -n +$((keep + 1)) | xargs -I {} rm "$dir/{}"
    fi
}

show_status() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  HVAC Bot - Status Check"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    
    # Local Qdrant
    log_info "Local Qdrant ($LOCAL_QDRANT_URL)..."
    local local_qdrant=$(curl -s "$LOCAL_QDRANT_URL/collections/$QDRANT_COLLECTION" 2>/dev/null)
    if [ $? -eq 0 ] && echo "$local_qdrant" | jq -e '.result' > /dev/null 2>&1; then
        local points=$(echo "$local_qdrant" | jq -r '.result.points_count // .result.vectors_count // 0')
        log_success "Connected - $points points"
    else
        log_error "Not reachable"
    fi
    
    # Cloud Qdrant
    if [ -n "$CLOUD_QDRANT_URL" ]; then
        log_info "Cloud Qdrant ($CLOUD_QDRANT_URL)..."
        local cloud_qdrant=$(curl -s -H "api-key: $CLOUD_QDRANT_API_KEY" \
            "$CLOUD_QDRANT_URL/collections/$QDRANT_COLLECTION" 2>/dev/null)
        if [ $? -eq 0 ] && echo "$cloud_qdrant" | jq -e '.result.status' > /dev/null 2>&1; then
            local points=$(echo "$cloud_qdrant" | jq -r '.result.points_count // .result.vectors_count // 0')
            log_success "Connected - $points points"
        else
            log_warn "Collection not found (will be created on first sync)"
        fi
    fi
    
    # Local PostgreSQL
    log_info "Local PostgreSQL..."
    if psql "$LOCAL_POSTGRES_URL" -c "SELECT 1" > /dev/null 2>&1; then
        local msg_count=$(psql "$LOCAL_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM messages" 2>/dev/null | tr -d ' ')
        local conv_count=$(psql "$LOCAL_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM conversations" 2>/dev/null | tr -d ' ')
        log_success "Connected - $conv_count conversations, $msg_count messages"
    else
        log_error "Not reachable"
    fi
    
    # Cloud PostgreSQL
    if [ -n "$CLOUD_POSTGRES_URL" ]; then
        log_info "Cloud PostgreSQL..."
        if psql "$CLOUD_POSTGRES_URL" -c "SELECT 1" > /dev/null 2>&1; then
            local msg_count=$(psql "$CLOUD_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM messages" 2>/dev/null | tr -d ' ')
            local conv_count=$(psql "$CLOUD_POSTGRES_URL" -t -c "SELECT COUNT(*) FROM conversations" 2>/dev/null | tr -d ' ')
            log_success "Connected - $conv_count conversations, $msg_count messages"
        else
            log_warn "Not reachable or not configured"
        fi
    fi
    
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

print_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  all       Sync everything (Qdrant + PostgreSQL) - DEFAULT"
    echo "  qdrant    Sync Qdrant vectors only"
    echo "  postgres  Sync PostgreSQL database only"
    echo "  status    Check local and cloud status"
    echo "  config    Create/edit cloud configuration"
    echo ""
    echo "Options:"
    echo "  --replace  Replace cloud data instead of merging (destructive!)"
    echo "  --dry-run  Show what would be synced without making changes"
    echo ""
    echo "Examples:"
    echo "  $0 status                    # Check sync status"
    echo "  $0 all                       # Sync new documents (merge mode)"
    echo "  $0 qdrant --dry-run          # Preview what would sync"
    echo "  $0 all --replace             # Full replace (careful!)"
    echo ""
}

main() {
    # Parse options first
    parse_options "$@"
    
    # Get command (first non-option argument)
    local command="all"
    for arg in "$@"; do
        case $arg in
            --*) continue ;;
            *) command=$arg; break ;;
        esac
    done
    
    case $command in
        all)
            check_config
            migrate_qdrant
            migrate_postgres
            echo ""
            log_success "Sync complete!"
            echo ""
            if [ "$REPLACE_MODE" = true ]; then
                echo "Cloud has been fully replaced with local data."
            else
                echo "New documents have been synced to cloud."
                echo "Existing cloud data was preserved."
            fi
            echo ""
            ;;
        qdrant)
            check_config
            migrate_qdrant
            ;;
        postgres)
            check_config
            migrate_postgres
            ;;
        status|check)
            check_config 2>/dev/null || true
            show_status
            ;;
        config)
            if [ -f "$CLOUD_CONFIG_FILE" ]; then
                ${EDITOR:-nano} "$CLOUD_CONFIG_FILE"
            else
                create_config_template
                log_info "Created $CLOUD_CONFIG_FILE"
                ${EDITOR:-nano} "$CLOUD_CONFIG_FILE"
            fi
            ;;
        help|--help|-h)
            print_usage
            ;;
        *)
            log_error "Unknown command: $command"
            print_usage
            exit 1
            ;;
    esac
}

main "$@"

