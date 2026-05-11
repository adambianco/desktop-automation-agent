"""
DataMapper — maps spreadsheet columns to workflow field variables.

Provides:
  - Column-to-field mapping with optional transformations
  - Default values for missing fields
  - Data validation rules
  - Format transformations (date formatting, number formatting, etc.)
  - Field extraction with type coercion
"""

import re
import logging
from typing import Any, Dict, List, Optional, Callable, Union
from datetime import datetime, date

logger = logging.getLogger(__name__)


class FieldMapping:
    """Defines how a spreadsheet column maps to a workflow field."""

    def __init__(self, source_column: str,
                 field_name: str,
                 default: Any = "",
                 transform: Optional[Callable[[Any], Any]] = None,
                 required: bool = False,
                 validators: Optional[List[Callable[[Any], bool]]] = None):
        """
        Args:
            source_column: Column name in the spreadsheet.
            field_name: Target field name in the workflow context.
            default: Default value if the column is empty or missing.
            transform: Optional callable to transform the value.
            required: If True, raise ValueError when the value is empty.
            validators: List of callables that return True if value is valid.
        """
        self.source_column = source_column
        self.field_name = field_name
        self.default = default
        self.transform = transform
        self.required = required
        self.validators = validators or []

    def extract(self, row: Dict[str, Any]) -> Any:
        """Extract and transform a value from a row dict."""
        raw = row.get(self.source_column, self.default)

        # Use default if value is empty/None
        if raw is None or str(raw).strip() == "" or str(raw).lower() == "nan":
            raw = self.default

        # Apply required check
        if self.required and (raw is None or str(raw).strip() == ""):
            raise ValueError(
                f"Required field '{self.field_name}' (column '{self.source_column}') is empty"
            )

        # Apply transformation
        if self.transform and raw is not None and str(raw).strip() != "":
            try:
                raw = self.transform(raw)
            except Exception as e:
                logger.warning("Transform failed for field '%s': %s", self.field_name, e)

        # Run validators
        for validator in self.validators:
            if not validator(raw):
                raise ValueError(
                    f"Validation failed for field '{self.field_name}': value={raw!r}"
                )

        return raw


class DataMapper:
    """
    Maps a spreadsheet row to a structured workflow context dictionary.

    Usage:
        mapper = DataMapper([
            FieldMapping("Invoice #", "invoice_number", required=True),
            FieldMapping("Date", "invoice_date",
                         transform=DataMapper.format_date("%d/%m/%Y")),
            FieldMapping("Amount", "amount",
                         transform=DataMapper.format_currency),
            FieldMapping("Vendor", "vendor_name", default="Unknown"),
        ])

        for row in reader.iter_rows():
            context = mapper.map(row)
            # context = {"invoice_number": "INV-001", "invoice_date": "01/05/2026", ...}
    """

    def __init__(self, mappings: List[FieldMapping]):
        self.mappings = mappings
        logger.info("DataMapper initialized with %d field mappings", len(mappings))

    def map(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map a spreadsheet row to a workflow context dictionary.

        Args:
            row: A row dictionary from SpreadsheetReader.

        Returns:
            Dict of {field_name: transformed_value} for all mappings.

        Raises:
            ValueError: If a required field is empty or validation fails.
        """
        context = {}
        errors = []

        for mapping in self.mappings:
            try:
                value = mapping.extract(row)
                context[mapping.field_name] = value
            except ValueError as e:
                errors.append(str(e))

        if errors:
            row_idx = row.get("_row_index", "?")
            raise ValueError(
                f"Row {row_idx} mapping errors:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        logger.debug("Row mapped: %s", context)
        return context

    def map_all(self, rows: List[Dict[str, Any]],
                skip_errors: bool = False) -> List[Dict[str, Any]]:
        """
        Map all rows, optionally skipping rows with errors.

        Args:
            rows: List of row dicts from SpreadsheetReader.
            skip_errors: If True, log errors and skip bad rows instead of raising.

        Returns:
            List of mapped context dicts.
        """
        results = []
        for row in rows:
            try:
                results.append(self.map(row))
            except ValueError as e:
                if skip_errors:
                    logger.warning("Skipping row %s: %s", row.get("_row_index", "?"), e)
                else:
                    raise
        return results

    # ------------------------------------------------------------------ #
    #  Built-in Transform Factories                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def format_date(output_format: str = "%Y-%m-%d",
                    input_formats: Optional[List[str]] = None) -> Callable:
        """
        Transform factory: parse and reformat a date string.

        Args:
            output_format: strftime format for the output.
            input_formats: List of strptime formats to try for parsing.
                           Defaults to common formats.
        """
        default_formats = [
            "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
            "%d-%m-%Y", "%m-%d-%Y", "%Y/%m/%d",
            "%d %b %Y", "%d %B %Y", "%b %d, %Y"
        ]
        formats = input_formats or default_formats

        def _transform(value: Any) -> str:
            if isinstance(value, (datetime, date)):
                return value.strftime(output_format)
            for fmt in formats:
                try:
                    return datetime.strptime(str(value).strip(), fmt).strftime(output_format)
                except ValueError:
                    continue
            logger.warning("Could not parse date: %r", value)
            return str(value)

        return _transform

    @staticmethod
    def format_currency(value: Any, decimal_places: int = 2,
                        symbol: str = "") -> str:
        """Transform factory: format a number as currency string."""
        try:
            num = float(str(value).replace(",", "").replace("$", "").strip())
            formatted = f"{num:.{decimal_places}f}"
            return f"{symbol}{formatted}" if symbol else formatted
        except (ValueError, TypeError):
            logger.warning("Could not format currency: %r", value)
            return str(value)

    @staticmethod
    def strip_and_upper(value: Any) -> str:
        """Transform: strip whitespace and convert to uppercase."""
        return str(value).strip().upper()

    @staticmethod
    def strip_and_title(value: Any) -> str:
        """Transform: strip whitespace and convert to title case."""
        return str(value).strip().title()

    @staticmethod
    def to_int(value: Any) -> int:
        """Transform: convert to integer."""
        try:
            return int(float(str(value).replace(",", "").strip()))
        except (ValueError, TypeError):
            raise ValueError(f"Cannot convert to int: {value!r}")

    @staticmethod
    def to_float(value: Any) -> float:
        """Transform: convert to float."""
        try:
            return float(str(value).replace(",", "").strip())
        except (ValueError, TypeError):
            raise ValueError(f"Cannot convert to float: {value!r}")

    @staticmethod
    def remove_special_chars(pattern: str = r"[^a-zA-Z0-9\s\-_.]") -> Callable:
        """Transform factory: remove characters matching a regex pattern."""
        def _transform(value: Any) -> str:
            return re.sub(pattern, "", str(value))
        return _transform

    @staticmethod
    def pad_left(width: int, char: str = "0") -> Callable:
        """Transform factory: left-pad a string to a fixed width."""
        def _transform(value: Any) -> str:
            return str(value).strip().zfill(width) if char == "0" else str(value).strip().rjust(width, char)
        return _transform

    @staticmethod
    def truncate(max_length: int) -> Callable:
        """Transform factory: truncate a string to max_length characters."""
        def _transform(value: Any) -> str:
            return str(value)[:max_length]
        return _transform

    # ------------------------------------------------------------------ #
    #  Built-in Validator Factories                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def not_empty() -> Callable:
        """Validator: value must not be empty."""
        return lambda v: str(v).strip() != ""

    @staticmethod
    def max_length(n: int) -> Callable:
        """Validator: value must not exceed n characters."""
        return lambda v: len(str(v)) <= n

    @staticmethod
    def matches_pattern(pattern: str) -> Callable:
        """Validator: value must match a regex pattern."""
        compiled = re.compile(pattern)
        return lambda v: bool(compiled.match(str(v)))

    @staticmethod
    def in_list(allowed: List[Any]) -> Callable:
        """Validator: value must be in the allowed list."""
        return lambda v: v in allowed
