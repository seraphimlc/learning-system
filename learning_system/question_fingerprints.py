from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


FINGERPRINT_POLICY_VERSION = "question-fingerprint.v1"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def descriptor_fingerprint(
    descriptor: dict[str, Any],
    *,
    fingerprint_type: str,
    policy_version: str = FINGERPRINT_POLICY_VERSION,
) -> str:
    if not isinstance(descriptor, dict):
        raise TypeError("fingerprint descriptor must be a mapping")
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ValueError("policy_version must be a nonempty string")
    if fingerprint_type not in {"prompt_instance", "core_structure"}:
        raise ValueError("unsupported fingerprint type")
    normalized_descriptor = deepcopy(descriptor)
    if fingerprint_type == "prompt_instance":
        values = normalized_descriptor.get("values")
        if isinstance(values, list) and all(
            isinstance(entry, dict) and isinstance(entry.get("name"), str)
            for entry in values
        ):
            normalized_descriptor["values"] = sorted(
                values,
                key=lambda entry: entry["name"],
            )
    return canonical_sha256(
        {
            "fingerprint_policy_version": policy_version,
            "fingerprint_type": fingerprint_type,
            "descriptor": normalized_descriptor,
        }
    )


def fingerprint_pair(
    normalized_instance_descriptor: dict[str, Any],
    normalized_core_structure_descriptor: dict[str, Any],
    *,
    policy_version: str = FINGERPRINT_POLICY_VERSION,
) -> dict[str, str]:
    return {
        "fingerprint_policy_version": policy_version,
        "prompt_instance_fingerprint": descriptor_fingerprint(
            normalized_instance_descriptor,
            fingerprint_type="prompt_instance",
            policy_version=policy_version,
        ),
        "core_structure_fingerprint": descriptor_fingerprint(
            normalized_core_structure_descriptor,
            fingerprint_type="core_structure",
            policy_version=policy_version,
        ),
    }
