---
name: hvac-scan
description: Scan equipment nameplates to identify units
triggers:
  - user sends a photo of equipment nameplate
  - user sends a photo of a data plate
  - user asks to identify equipment
  - user sends an image with text about model/serial number
priority: 2
---

# Equipment Scan Skill

## Purpose
Process nameplate/data plate photos to automatically identify equipment.

## How to Use

When a user sends an image (likely a nameplate photo):

1. Send the image to the backend:
   ```
   POST {HVAC_BACKEND_URL}/api/scan-equipment
   Content-Type: multipart/form-data
   X-OpenClaw-Secret: {OPENCLAW_SHARED_SECRET}

   image: <the uploaded image file>
   ```

2. Process the response:
   - Show the identified brand, model, and serial number
   - Show the confidence level
   - If specs were extracted, display voltage, amperage, tonnage, refrigerant type
   - Save the equipment info to user memory for future conversations

3. Example response format:
   ```
   🔍 Equipment Identified:
   Brand: Carrier
   Model: 24ACC636A003
   Serial: 2119E12345
   Type: Air Conditioner

   Specs:
   - 3 Ton / 36,000 BTU
   - 208-230V / 1Ph / 60Hz
   - R-410A refrigerant
   - 16 SEER

   I've saved this equipment to your profile. Ask me anything about it!
   ```

4. If confidence is low (< 0.6), ask the user to confirm or retake the photo.
