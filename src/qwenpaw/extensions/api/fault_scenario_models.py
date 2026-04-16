from dataclasses import dataclass


@dataclass(slots=True)
class FaultScenarioDetection:
    triggered: bool
    scene_code: str
    entry_summary: str
