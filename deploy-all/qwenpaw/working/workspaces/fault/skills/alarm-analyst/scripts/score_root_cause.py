"""Calculate the v2 evidence-support score for an explicitly scoped claim."""

from __future__ import annotations

import argparse
import json
from typing import Any

RULE_VERSION = "root-cause-evidence-v2"
WEIGHTS = {
    "对象与事实对应": 20,
    "直接因果证据": 50,
    "时间对应": 20,
    "独立佐证": 10,
}


def score_root_cause(
    *,
    claim: str,
    object_match: float,
    mechanism: float,
    time_match: float,
    independent: float,
    key_conflict: bool = False,
) -> dict[str, Any]:
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("须明确评分所针对的具体结论")
    levels = (object_match, mechanism, time_match, independent)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value not in (0, 0.5, 1)
        for value in levels
    ):
        raise ValueError("每项证据等级只能取0、0.5或1")
    if not isinstance(key_conflict, bool):
        raise ValueError("关键证据冲突标记须为布尔值")
    components = {
        name: int(weight * level)
        for (name, weight), level in zip(WEIGHTS.items(), levels)
    }
    raw_score = sum(components.values())
    limits = []
    if mechanism == 0:
        limits.append({"reason": "缺少支持该结论的直接因果证据", "cap": 40})
    if key_conflict:
        limits.append({"reason": "该结论存在未解决的关键证据冲突", "cap": 30})
    return {
        "ruleVersion": RULE_VERSION,
        "scoredClaim": claim.strip(),
        "components": components,
        "rawScore": raw_score,
        "score": min([raw_score, *(item["cap"] for item in limits)]),
        "limits": limits,
        "isStatisticalProbability": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claim", required=True)
    for name in ("object-match", "mechanism", "time-match", "independent"):
        parser.add_argument(
            "--" + name, type=float, choices=(0, 0.5, 1), required=True
        )
    parser.add_argument("--key-conflict", action="store_true")
    args = parser.parse_args()
    try:
        result = score_root_cause(**vars(args))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
