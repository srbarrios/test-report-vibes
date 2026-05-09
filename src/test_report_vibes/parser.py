"""Cucumber JSON report parser."""

import json
from pathlib import Path
from typing import List
from pydantic import ValidationError

from .models import Feature


def parse_cucumber_json(file_path: str) -> List[Feature]:
    """
    Parse Cucumber JSON file into Feature objects.

    Args:
        file_path: Path to cucumber JSON report

    Returns:
        List of Feature objects

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If invalid JSON
        ValidationError: If JSON doesn't match Cucumber schema
        ValueError: If the JSON structure is invalid
    """
    path = Path(file_path)

    # Check file exists
    if not path.exists():
        raise FileNotFoundError(
            f"Cannot find file '{file_path}'. Please check the path."
        )

    # Check file is readable
    if not path.is_file():
        raise ValueError(f"'{file_path}' is not a file.")

    # Read and parse JSON
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"Invalid JSON format in '{file_path}': {e.msg}",
            e.doc,
            e.pos
        )

    # Validate it's a list
    if not isinstance(data, list):
        raise ValueError(
            f"Invalid Cucumber JSON structure in '{file_path}': "
            "Expected a list of features at the root level."
        )

    # Parse into Pydantic models
    try:
        features = [Feature(**feature_data) for feature_data in data]
    except ValidationError as e:
        # Provide helpful error message
        raise ValueError(
            f"Invalid Cucumber JSON structure in '{file_path}'. \nError details:\n{e}"
        ) from e

    return features


def validate_cucumber_format(data: dict) -> bool:
    """
    Validate that JSON follows Cucumber format conventions.

    Args:
        data: Dictionary representing a potential Cucumber feature

    Returns:
        True if valid, False otherwise
    """
    required_fields = ["uri", "id", "name", "keyword", "elements"]
    return all(field in data for field in required_fields)
