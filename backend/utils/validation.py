"""Input validation utilities."""

import re
from typing import Any


class ValidationError(Exception):
    """Raised when validation fails."""

    def __init__(self, message: str, field: str | None = None):
        self.message = message
        self.field = field
        super().__init__(message)


def validate_required(value: Any, field_name: str) -> Any:
    """Validate that a value is not None or empty."""
    if value is None:
        raise ValidationError(f"{field_name} is required", field_name)
    if isinstance(value, str) and not value.strip():
        raise ValidationError(f"{field_name} cannot be empty", field_name)
    if isinstance(value, (list, dict)) and not value:
        raise ValidationError(f"{field_name} cannot be empty", field_name)
    return value


def validate_string_length(
    value: str,
    field_name: str,
    min_length: int = 0,
    max_length: int | None = None,
) -> str:
    """Validate string length."""
    if len(value) < min_length:
        raise ValidationError(
            f"{field_name} must be at least {min_length} characters",
            field_name,
        )
    if max_length and len(value) > max_length:
        raise ValidationError(
            f"{field_name} must be at most {max_length} characters",
            field_name,
        )
    return value


def validate_email(email: str) -> str:
    """Validate email format."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email):
        raise ValidationError("Invalid email format", "email")
    return email.lower()


def validate_uuid(value: str, field_name: str = "id") -> str:
    """Validate UUID format."""
    pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    if not re.match(pattern, value.lower()):
        raise ValidationError(f"Invalid {field_name} format", field_name)
    return value


def validate_in_list(
    value: Any,
    allowed: list[Any],
    field_name: str,
) -> Any:
    """Validate that value is in allowed list."""
    if value not in allowed:
        raise ValidationError(
            f"{field_name} must be one of: {', '.join(str(a) for a in allowed)}",
            field_name,
        )
    return value


def validate_numeric_range(
    value: int | float,
    field_name: str,
    min_value: int | float | None = None,
    max_value: int | float | None = None,
) -> int | float:
    """Validate numeric value is within range."""
    if min_value is not None and value < min_value:
        raise ValidationError(
            f"{field_name} must be at least {min_value}",
            field_name,
        )
    if max_value is not None and value > max_value:
        raise ValidationError(
            f"{field_name} must be at most {max_value}",
            field_name,
        )
    return value


def validate_file_extension(
    filename: str,
    allowed_extensions: list[str],
) -> str:
    """Validate file has allowed extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_lower = [e.lower().lstrip(".") for e in allowed_extensions]

    if ext not in allowed_lower:
        raise ValidationError(
            f"File type not allowed. Allowed: {', '.join(allowed_extensions)}",
            "file",
        )
    return filename


def validate_model_number(model_number: str) -> str:
    """Validate HVAC model number format."""
    # Basic validation - at least some alphanumeric characters
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", model_number)
    if len(cleaned) < 3:
        raise ValidationError(
            "Model number must contain at least 3 alphanumeric characters",
            "model_number",
        )
    return model_number.strip().upper()


def validate_brand(brand: str, known_brands: list[str] | None = None) -> str:
    """Validate and normalize brand name."""
    brand = brand.strip()

    if not brand:
        raise ValidationError("Brand name is required", "brand")

    # Normalize common variations
    brand_mappings = {
        "CARRIER": "Carrier",
        "TRANE": "Trane",
        "LENNOX": "Lennox",
        "RHEEM": "Rheem",
        "GOODMAN": "Goodman",
        "DAIKIN": "Daikin",
        "YORK": "York",
        "BRYANT": "Bryant",
        "AMERICAN STANDARD": "American Standard",
        "RUUD": "Ruud",
    }

    normalized = brand_mappings.get(brand.upper(), brand.title())

    if known_brands and normalized not in known_brands:
        # Return as-is but log warning (don't reject unknown brands)
        return brand.title()

    return normalized


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage."""
    # Remove path components
    filename = filename.replace("/", "_").replace("\\", "_")

    # Remove or replace unsafe characters
    filename = re.sub(r"[<>:\"|?*]", "_", filename)

    # Limit length
    name, ext = (filename.rsplit(".", 1) + [""])[:2]
    if len(name) > 200:
        name = name[:200]

    return f"{name}.{ext}" if ext else name


def validate_pagination(
    page: int,
    page_size: int,
    max_page_size: int = 100,
) -> tuple[int, int]:
    """Validate pagination parameters."""
    if page < 1:
        raise ValidationError("Page must be at least 1", "page")

    if page_size < 1:
        raise ValidationError("Page size must be at least 1", "page_size")

    if page_size > max_page_size:
        raise ValidationError(
            f"Page size cannot exceed {max_page_size}",
            "page_size",
        )

    return page, page_size


def validate_date_range(
    start_date: str | None,
    end_date: str | None,
) -> tuple[str | None, str | None]:
    """Validate date range."""
    from datetime import datetime

    date_format = "%Y-%m-%d"

    parsed_start = None
    parsed_end = None

    if start_date:
        try:
            parsed_start = datetime.strptime(start_date, date_format)
        except ValueError:
            raise ValidationError(
                "Invalid start_date format. Use YYYY-MM-DD",
                "start_date",
            )

    if end_date:
        try:
            parsed_end = datetime.strptime(end_date, date_format)
        except ValueError:
            raise ValidationError(
                "Invalid end_date format. Use YYYY-MM-DD",
                "end_date",
            )

    if parsed_start and parsed_end and parsed_start > parsed_end:
        raise ValidationError(
            "start_date must be before end_date",
            "date_range",
        )

    return start_date, end_date
