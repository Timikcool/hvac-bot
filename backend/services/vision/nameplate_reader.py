"""Equipment nameplate recognition service."""

import re
from dataclasses import dataclass, field
from typing import Any

from core.llm import LLMClient


@dataclass
class EquipmentIdentification:
    """Identified equipment from nameplate."""

    brand: str
    model: str
    serial: str
    manufacture_date: str
    specs: dict[str, Any] = field(default_factory=dict)
    equipment_type: str = "unknown"
    confidence: float = 0.0
    raw_text: str = ""


class NameplateReader:
    """Extract equipment information from nameplate/data plate photos.

    Uses Claude vision with HVAC-specific prompting.
    """

    # Known manufacturer patterns for validation
    MANUFACTURER_PATTERNS = {
        "carrier": {
            "model_pattern": r"(?:24|25|38|40|48|50)[A-Z]{2,3}\d{3,6}",
            "serial_pattern": r"\d{10}",
        },
        "trane": {
            "model_pattern": r"(?:4TT|4WC|XR|XL|XV)\w+",
            "serial_pattern": r"\d{9,10}",
        },
        "lennox": {
            "model_pattern": r"(?:XC|EL|ML|SL)\d{2}[A-Z]-\d{3}",
            "serial_pattern": r"\d{10}[A-Z]",
        },
        "rheem": {
            "model_pattern": r"R\d{2}[A-Z]{2}\d{4}",
            "serial_pattern": r"[A-Z]\d{10}",
        },
        "goodman": {
            "model_pattern": r"G[A-Z]{2,3}\d{4,6}",
            "serial_pattern": r"\d{10}",
        },
        "york": {
            "model_pattern": r"[A-Z]{2,3}\d{2}[A-Z]\d{4,6}",
            "serial_pattern": r"[A-Z]\d{9}",
        },
        "daikin": {
            "model_pattern": r"D[A-Z]{2}\d{4,6}",
            "serial_pattern": r"\d{10}",
        },
    }

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def read_nameplate(self, image_data: bytes) -> EquipmentIdentification:
        """Read equipment nameplate using Claude vision.

        Args:
            image_data: Raw image bytes

        Returns:
            EquipmentIdentification with extracted data
        """
        prompt = """Analyze this HVAC equipment nameplate/data plate and extract:

1. MANUFACTURER/BRAND: (e.g., Carrier, Trane, Lennox, Rheem, Goodman, York, Daikin, etc.)
2. MODEL_NUMBER: The complete model/part number
3. SERIAL_NUMBER: The serial number
4. MANUFACTURE_DATE: Date or date code if visible
5. SPECIFICATIONS:
   - Voltage/Phase (e.g., 208-230V/1Ph/60Hz)
   - Amperage ratings (RLA, LRA, FLA)
   - BTU/Tonnage if shown
   - Refrigerant type and charge
   - SEER/EER rating if visible

6. EQUIPMENT_TYPE: (Air Conditioner, Heat Pump, Furnace, Air Handler, Condenser, etc.)

Return as JSON with these exact keys:
{
    "MANUFACTURER": "brand name",
    "MODEL_NUMBER": "model number or null",
    "SERIAL_NUMBER": "serial number or null",
    "MANUFACTURE_DATE": "date or null",
    "SPECIFICATIONS": {
        "voltage": "...",
        "amperage": "...",
        "capacity": "...",
        "refrigerant": "...",
        "efficiency": "..."
    },
    "EQUIPMENT_TYPE": "type",
    "confidence": 0.0-1.0,
    "raw_text": "all visible text"
}

Use null for any field you cannot read clearly.
Include a confidence score (0-1) for the overall reading quality."""

        response = await self.llm.generate_with_vision(
            prompt=prompt,
            image_data=image_data,
            temperature=0,
        )

        # Parse response
        result = self._parse_vision_response(response.content)

        # Validate against known patterns
        result = self._validate_identification(result)

        return result

    def _parse_vision_response(self, response_text: str) -> EquipmentIdentification:
        """Parse JSON response from vision model."""
        import json

        # Extract JSON from response
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return EquipmentIdentification(
                    brand=data.get("MANUFACTURER", "Unknown"),
                    model=data.get("MODEL_NUMBER", "") or "",
                    serial=data.get("SERIAL_NUMBER", "") or "",
                    manufacture_date=data.get("MANUFACTURE_DATE", "") or "",
                    specs=data.get("SPECIFICATIONS", {}),
                    equipment_type=data.get("EQUIPMENT_TYPE", "unknown"),
                    confidence=data.get("confidence", 0.5),
                    raw_text=data.get("raw_text", ""),
                )
            except json.JSONDecodeError:
                pass

        return EquipmentIdentification(
            brand="Unknown",
            model="",
            serial="",
            manufacture_date="",
            specs={},
            equipment_type="unknown",
            confidence=0.0,
            raw_text=response_text,
        )

    def _validate_identification(
        self,
        ident: EquipmentIdentification,
    ) -> EquipmentIdentification:
        """Validate extracted data against known manufacturer patterns."""
        brand_lower = ident.brand.lower()

        if brand_lower in self.MANUFACTURER_PATTERNS:
            patterns = self.MANUFACTURER_PATTERNS[brand_lower]

            # Validate model number format
            if ident.model:
                model_pattern = patterns.get("model_pattern")
                if model_pattern and not re.match(model_pattern, ident.model, re.IGNORECASE):
                    ident.confidence *= 0.7  # Reduce confidence if pattern doesn't match

            # Validate serial number format
            if ident.serial:
                serial_pattern = patterns.get("serial_pattern")
                if serial_pattern and not re.match(serial_pattern, ident.serial):
                    ident.confidence *= 0.8

        return ident

    async def extract_error_code(self, image_data: bytes) -> dict[str, Any]:
        """Extract error code from display/LED photo.

        Args:
            image_data: Photo of error display

        Returns:
            Dict with error_code, description, and confidence
        """
        prompt = """Analyze this HVAC equipment display/LED panel and extract:

1. ERROR_CODE: The error or fault code shown (e.g., E1, F3, 401, etc.)
2. LED_PATTERN: If showing LED blinks, describe the pattern
3. DISPLAY_TEXT: Any text shown on the display
4. MANUFACTURER_HINT: If you can identify the manufacturer from the display

Return as JSON:
{
    "error_code": "the code or null",
    "led_pattern": "description or null",
    "display_text": "text or null",
    "manufacturer_hint": "brand or null",
    "confidence": 0.0-1.0
}"""

        response = await self.llm.generate_with_vision(
            prompt=prompt,
            image_data=image_data,
            temperature=0,
        )

        return self.llm._parse_json_response(response.content) if hasattr(self.llm, '_parse_json_response') else {}
