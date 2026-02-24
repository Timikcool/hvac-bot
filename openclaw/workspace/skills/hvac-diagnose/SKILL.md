---
name: hvac-diagnose
description: Visual diagnosis from equipment photos
triggers:
  - user sends a photo of equipment with a problem description
  - user asks to diagnose something visible
  - user sends an image with words like "what's wrong", "issue", "problem"
priority: 3
---

# Visual Diagnosis Skill

## Purpose
Analyze photos of HVAC equipment to identify visible issues and cross-reference with manuals.

## How to Use

When a user sends a photo with a description of a problem:

1. Send the image and description to the backend:
   ```
   POST {HVAC_BACKEND_URL}/api/analyze-image
   Content-Type: multipart/form-data
   X-OpenClaw-Secret: {OPENCLAW_SHARED_SECRET}

   image: <the uploaded image>
   description: "<user's description of the problem>"
   equipment_brand: "<from memory or null>"
   equipment_model: "<from memory or null>"
   ```

2. Format the diagnosis response:
   - Start with any safety concerns (⚠️)
   - List identified components
   - Describe visible issues with severity
   - Provide suggested causes (ordered by likelihood)
   - Include recommended next checks
   - Note if physical inspection is needed

3. Example response:
   ```
   ⚠️ Disconnect power before inspecting.

   I can see: condenser coil, contactor, capacitor

   Potential issues:
   1. Capacitor appears bulged on top — likely failed (HIGH severity)
   2. Contactor contacts show pitting — may need replacement soon (MEDIUM)

   Recommended checks:
   1. Check capacitor with multimeter (compare to rated µF on label)
   2. Check contactor for continuity
   3. Check amp draw on compressor

   📖 Reference: Carrier 24ACC Service Manual, p.47
   ```

4. Save diagnostic findings to conversation memory.
