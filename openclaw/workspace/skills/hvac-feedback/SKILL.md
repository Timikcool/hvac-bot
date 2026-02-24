---
name: hvac-feedback
description: Submit feedback and corrections on bot responses
triggers:
  - user says the answer was wrong or incorrect
  - user provides a correction
  - user says "that's not right" or similar
  - user rates a response
priority: 4
---

# Feedback Skill

## Purpose
Capture technician feedback and corrections to improve the system over time.

## How to Use

When a user indicates something was wrong or wants to provide feedback:

1. Determine the type of correction:
   - **wrong_order**: Steps were in the wrong diagnostic order
   - **wrong_terminology**: Wrong technical term used
   - **missing_step**: Important step was left out
   - **good**: Positive feedback

2. Send to the backend:
   ```
   POST {HVAC_BACKEND_URL}/api/feedback
   Content-Type: application/json
   X-OpenClaw-Secret: {OPENCLAW_SHARED_SECRET}

   {
     "message_id": "<id of the message being corrected>",
     "feedback_type": "incorrect",
     "correction_type": "wrong_order",
     "details": "<user's explanation>",
     "correct_answer": "<what the user says is correct>",
     "correct_sequence": ["capacitor", "contactor", "wiring"],
     "terminology_correction": {
       "wrong": "relay contacts",
       "correct": "contactor"
     }
   }
   ```

3. Acknowledge the correction:
   - Thank the technician
   - Confirm what was learned
   - Example: "Got it — I'll check the capacitor first next time. Thanks for the correction!"

4. For simple positive feedback ("that was helpful", "good answer", thumbs up):
   ```
   {
     "message_id": "<message id>",
     "rating": 5,
     "feedback_type": "helpful",
     "correction_type": "good"
   }
   ```
