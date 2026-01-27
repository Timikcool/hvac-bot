#!/usr/bin/env python3
"""Migrate Qdrant data from local to Railway"""

import requests
import json
from tqdm import tqdm

LOCAL_QDRANT = "http://localhost:6333"
RAILWAY_QDRANT = "https://qdrant-production-64b4.up.railway.app"
COLLECTION = "hvac_manuals"
BATCH_SIZE = 100

def get_collection_info(url):
    """Get collection info"""
    resp = requests.get(f"{url}/collections/{COLLECTION}")
    if resp.status_code == 200:
        return resp.json()["result"]
    return None

def create_collection(url, config):
    """Create collection with same config"""
    payload = {
        "vectors": config["config"]["params"]["vectors"],
        "on_disk_payload": config["config"]["params"].get("on_disk_payload", True)
    }
    resp = requests.put(f"{url}/collections/{COLLECTION}", json=payload)
    return resp.status_code == 200

def scroll_points(url, limit=100, offset=None):
    """Scroll through all points"""
    payload = {"limit": limit, "with_payload": True, "with_vector": True}
    if offset:
        payload["offset"] = offset
    resp = requests.post(f"{url}/collections/{COLLECTION}/points/scroll", json=payload)
    if resp.status_code == 200:
        data = resp.json()["result"]
        return data["points"], data.get("next_page_offset")
    return [], None

def upsert_points(url, points):
    """Upsert points to collection"""
    payload = {"points": points}
    resp = requests.put(f"{url}/collections/{COLLECTION}/points", json=payload)
    return resp.status_code == 200

def main():
    print("🔄 Qdrant Migration: Local → Railway")
    print("=" * 50)
    
    # Get local collection info
    local_info = get_collection_info(LOCAL_QDRANT)
    if not local_info:
        print("❌ Could not connect to local Qdrant")
        return
    
    total_points = local_info["points_count"]
    print(f"📊 Local collection: {total_points} points")
    
    # Check Railway collection
    railway_info = get_collection_info(RAILWAY_QDRANT)
    if railway_info:
        existing = railway_info["points_count"]
        if existing > 0:
            print(f"⚠️  Railway collection exists with {existing} points")
            resp = input("Delete and recreate? [y/N]: ")
            if resp.lower() != 'y':
                print("Aborted")
                return
            requests.delete(f"{RAILWAY_QDRANT}/collections/{COLLECTION}")
    
    # Create collection on Railway
    print("📦 Creating collection on Railway...")
    if not create_collection(RAILWAY_QDRANT, local_info):
        print("❌ Failed to create collection")
        return
    print("✅ Collection created")
    
    # Migrate points
    print(f"\n🚀 Migrating {total_points} points...")
    migrated = 0
    offset = None
    
    with tqdm(total=total_points, unit="points") as pbar:
        while True:
            points, next_offset = scroll_points(LOCAL_QDRANT, BATCH_SIZE, offset)
            if not points:
                break
            
            # Convert points format for upsert
            upsert_data = []
            for p in points:
                upsert_data.append({
                    "id": p["id"],
                    "vector": p["vector"],
                    "payload": p["payload"]
                })
            
            if not upsert_points(RAILWAY_QDRANT, upsert_data):
                print(f"\n❌ Failed to upsert batch at offset {offset}")
                break
            
            migrated += len(points)
            pbar.update(len(points))
            
            if not next_offset:
                break
            offset = next_offset
    
    # Verify
    railway_info = get_collection_info(RAILWAY_QDRANT)
    if railway_info:
        final_count = railway_info["points_count"]
        print(f"\n✅ Migration complete!")
        print(f"   Local: {total_points} points")
        print(f"   Railway: {final_count} points")
        if final_count == total_points:
            print("   ✓ Counts match!")
        else:
            print("   ⚠️ Count mismatch!")

if __name__ == "__main__":
    main()

