"""
SpreadsheetReader — reads Excel and CSV files for data-driven workflows.

Supports:
  - Excel (.xlsx, .xls) and CSV files
  - Multiple sheets
  - Row-by-row iteration for data entry
  - Column filtering and renaming
  - Data validation and type coercion
  - Progress tracking (resume from a specific row)
"""

import os
import logging
from typing import Optional, List, Dict, Any, Iterator, Union

import pandas as pd

logger = logging.getLogger(__name__)


class SpreadsheetReader:
    """
    Reads tabular data from Excel or CSV files and provides an iterator
    interface for row-by-row processing in automation workflows.

    Usage:
        reader = SpreadsheetReader("data/invoices.xlsx")
        reader.load(sheet="Sheet1", header_row=0)

        for row in reader.iter_rows():
            print(row["Invoice Number"], row["Amount"])

        # Resume from row 5 (e.g., after a crash)
        for row in reader.iter_rows(start_row=5):
            ...
    """

    def __init__(self, file_path: str):
        """
        Args:
            file_path: Path to the Excel or CSV file.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Data file not found: {file_path}")
        self.file_path = os.path.abspath(file_path)
        self.file_ext = os.path.splitext(file_path)[1].lower()
        self._df: Optional[pd.DataFrame] = None
        self._current_row: int = 0
        logger.info("SpreadsheetReader initialized: %s", self.file_path)

    def load(self, sheet: Union[str, int] = 0,
             header_row: int = 0,
             skip_rows: int = 0,
             columns: Optional[List[str]] = None,
             column_map: Optional[Dict[str, str]] = None,
             fill_na: Any = "",
             dtype: Optional[Dict[str, Any]] = None) -> "SpreadsheetReader":
        """
        Load the spreadsheet into memory.

        Args:
            sheet: Sheet name or 0-based index (Excel only; ignored for CSV).
            header_row: Row index to use as column headers.
            skip_rows: Number of rows to skip after the header.
            columns: Optional list of column names to keep (others discarded).
            column_map: Optional dict to rename columns {old_name: new_name}.
            fill_na: Value to fill NaN cells with (default: empty string).
            dtype: Optional dict of {column: dtype} for type coercion.

        Returns:
            self (for method chaining)
        """
        logger.info("Loading %s (sheet=%s)", self.file_path, sheet)

        if self.file_ext in (".xlsx", ".xls", ".xlsm", ".xlsb"):
            self._df = pd.read_excel(
                self.file_path,
                sheet_name=sheet,
                header=header_row,
                skiprows=range(1, skip_rows + 1) if skip_rows else None,
                dtype=dtype
            )
        elif self.file_ext == ".csv":
            self._df = pd.read_csv(
                self.file_path,
                header=header_row,
                skiprows=range(1, skip_rows + 1) if skip_rows else None,
                dtype=dtype
            )
        else:
            raise ValueError(f"Unsupported file format: {self.file_ext}")

        # Fill NaN values
        self._df = self._df.fillna(fill_na)

        # Rename columns
        if column_map:
            self._df = self._df.rename(columns=column_map)
            logger.debug("Columns renamed: %s", column_map)

        # Filter columns
        if columns:
            missing = [c for c in columns if c not in self._df.columns]
            if missing:
                raise ValueError(f"Columns not found in spreadsheet: {missing}")
            self._df = self._df[columns]

        # Strip whitespace from string columns
        for col in self._df.select_dtypes(include=["object"]).columns:
            self._df[col] = self._df[col].astype(str).str.strip()

        self._current_row = 0
        logger.info("Loaded %d rows × %d columns", len(self._df), len(self._df.columns))
        logger.debug("Columns: %s", list(self._df.columns))
        return self

    @property
    def row_count(self) -> int:
        """Total number of data rows."""
        self._ensure_loaded()
        return len(self._df)

    @property
    def columns(self) -> List[str]:
        """List of column names."""
        self._ensure_loaded()
        return list(self._df.columns)

    def get_row(self, index: int) -> Dict[str, Any]:
        """
        Get a single row by 0-based index as a dictionary.

        Args:
            index: 0-based row index.

        Returns:
            Dict mapping column names to values.
        """
        self._ensure_loaded()
        if index < 0 or index >= len(self._df):
            raise IndexError(f"Row index {index} out of range [0, {len(self._df) - 1}]")
        return self._df.iloc[index].to_dict()

    def iter_rows(self, start_row: int = 0,
                  end_row: Optional[int] = None,
                  filter_fn: Optional[callable] = None
                  ) -> Iterator[Dict[str, Any]]:
        """
        Iterate over rows as dictionaries.

        Args:
            start_row: 0-based index of the first row to process.
            end_row: 0-based index of the last row (exclusive). None = all rows.
            filter_fn: Optional callable(row_dict) → bool to skip rows.

        Yields:
            Dict mapping column names to values, with an added '_row_index' key.
        """
        self._ensure_loaded()
        end = end_row if end_row is not None else len(self._df)
        end = min(end, len(self._df))

        logger.info("Iterating rows %d–%d of %d", start_row, end - 1, len(self._df))

        for i in range(start_row, end):
            row = self._df.iloc[i].to_dict()
            row["_row_index"] = i
            self._current_row = i

            if filter_fn and not filter_fn(row):
                logger.debug("Row %d skipped by filter", i)
                continue

            logger.debug("Yielding row %d: %s", i, {k: v for k, v in row.items()
                                                      if not k.startswith("_")})
            yield row

    def get_all_rows(self, start_row: int = 0) -> List[Dict[str, Any]]:
        """Return all rows as a list of dictionaries."""
        return list(self.iter_rows(start_row=start_row))

    def get_sheet_names(self) -> List[str]:
        """Return the list of sheet names (Excel only)."""
        if self.file_ext not in (".xlsx", ".xls", ".xlsm"):
            return []
        xl = pd.ExcelFile(self.file_path)
        return xl.sheet_names

    def validate_columns(self, required_columns: List[str]) -> List[str]:
        """
        Check that required columns exist in the loaded data.

        Returns:
            List of missing column names (empty if all present).
        """
        self._ensure_loaded()
        return [c for c in required_columns if c not in self._df.columns]

    def get_unique_values(self, column: str) -> List[Any]:
        """Return unique values in a column."""
        self._ensure_loaded()
        return self._df[column].unique().tolist()

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """Return all rows as a plain list of dicts (no _row_index)."""
        self._ensure_loaded()
        return self._df.to_dict(orient="records")

    def _ensure_loaded(self) -> None:
        if self._df is None:
            raise RuntimeError("Spreadsheet not loaded. Call .load() first.")

    def __len__(self) -> int:
        return self.row_count

    def __repr__(self) -> str:
        if self._df is not None:
            return f"SpreadsheetReader({self.file_path!r}, {len(self._df)} rows)"
        return f"SpreadsheetReader({self.file_path!r}, not loaded)"
