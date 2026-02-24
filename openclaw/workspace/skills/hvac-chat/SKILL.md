---
name: hvac-chat
description: Main HVAC troubleshooting and information chat
triggers:
  - any text message about HVAC equipment
  - questions about heating, cooling, or ventilation
  - troubleshooting requests
  - equipment specifications
priority: 1
---

# HVAC Chat Skill

## Purpose
Handle general HVAC questions by routing them to the backend RAG pipeline.

## How to Use

When a user sends a text message about an HVAC topic:

1. Extract any equipment context from the message or memory:
   - Brand (Carrier, Trane, Lennox, Rheem, Goodman, etc.)
   - Model number
   - System type (split, package, mini-split, etc.)

2. Call the backend API:
   ```
   POST {HVAC_BACKEND_URL}/api/chat
   Content-Type: application/json
   X-OpenClaw-Secret: {OPENCLAW_SHARED_SECRET}

   {
     "message": "<user's message>",
     "equipment": {
       "brand": "<brand or null>",
       "model": "<model or null>",
       "system_type": "<type or null>"
     },
     "conversation_id": "<from memory or null>",
     "user_id": "<openclaw user id>"
   }
   ```

3. Format the response for messaging:
   - Keep the answer text as-is (it's already formatted for field techs)
   - If there are safety warnings, prepend them with ⚠️
   - If citations exist, append a brief "Sources" line
   - If follow-up questions are suggested, present them as quick-reply buttons
   - If escalation is required, add a note suggesting they contact senior tech

4. Save the conversation_id to memory for continuity.

## Response Formatting

For **Telegram**, use Markdown formatting:
- Bold for headers: **Check capacitor first**
- Numbered lists for steps
- ⚠️ for safety warnings

For **WhatsApp**, use plain text with emoji:
- Numbers for steps: 1. Check capacitor...
- ⚠️ for safety warnings
- Keep messages under 4096 characters
