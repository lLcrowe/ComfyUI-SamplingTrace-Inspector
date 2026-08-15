from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

from .diagnostics import diagnose_run
from .json_utils import append_jsonl, atomic_write_json, atomic_write_jsonl, read_json, read_jsonl
from .report import write_comparison_reports, write_reports


def default_base_directory() -> Path:
    try:
        import folder_paths

        get_user_directory = getattr(folder_paths, "get_user_directory", None)
        if callable(get_user_directory):
            return Path(get_user_directory()) / "trace_inspector" / "runs"
    except Exception:
        pass
    return Path(__file__).resolve().parent.parent / "data" / "runs"


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _absolute_difference(left: Any, right: Any) -> float | None:
    left_value = _number(left)
    right_value = _number(right)
    if left_value is None or right_value is None:
        return None
    return abs(left_value - right_value)


def _runtime_summary(run: dict[str, Any]) -> dict[str, Any]:
    settings = run.get("generationSettings", {}) or {}
    segments = run.get("segments", []) or []
    segment = segments[0] if segments and isinstance(segments[0], dict) else {}
    return {
        "requestedSampler": settings.get("sampler_name"),
        "requestedScheduler": settings.get("scheduler"),
        "actualSampler": segment.get("sampler"),
        "segmentCount": len(segments),
    }


def _model_patch_summary(run: dict[str, Any]) -> dict[str, Any]:
    snapshot = run.get("modelSnapshot", {}) or {}
    transformer_shape = snapshot.get("transformerOptionShape", {}) or {}
    return {
        "type": snapshot.get("type"),
        "weightPatchKeyCount": snapshot.get("weightPatchKeyCount", 0),
        "weightPatchEntryCount": snapshot.get("weightPatchEntryCount", 0),
        "objectPatchCount": snapshot.get("objectPatchCount", 0),
        "transformerPatchCallableCount": snapshot.get("transformerPatchCallableCount", 0),
        "transformerPatchKeys": sorted(str(key) for key in transformer_shape),
        "wrapperCounts": snapshot.get("wrapperCounts", {}) or {},
        "callbackCounts": snapshot.get("callbackCounts", {}) or {},
    }


class TraceStore:
    def __init__(self, base_directory: Path | None = None) -> None:
        self.base_directory = (base_directory or default_base_directory()).resolve()
        self.base_directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._sessions: dict[str, Any] = {}

    def run_directory(self, run_id: str) -> Path:
        safe = "".join(ch for ch in str(run_id) if ch.isalnum() or ch in {"-", "_"})
        if not safe or safe != run_id:
            raise ValueError("Invalid run_id")
        path = (self.base_directory / safe).resolve()
        if self.base_directory not in path.parents:
            raise ValueError("run_id escaped trace root")
        return path

    def artifact_directory(self, run_id: str) -> Path:
        path = self.run_directory(run_id) / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def register_session(self, session: Any) -> None:
        with self._lock:
            self._sessions[session.run_id] = session
            self.persist_run(session.to_run_payload())

    def active_session(self, run_id: str) -> Any | None:
        with self._lock:
            return self._sessions.get(run_id)

    def release_session(self, run_id: str) -> None:
        with self._lock:
            self._sessions.pop(run_id, None)

    def persist_run(self, payload: dict[str, Any]) -> None:
        with self._lock:
            run_dir = self.run_directory(payload["runId"])
            run_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(run_dir / "run.json", payload)

    def append_step(self, run_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            append_jsonl(self.run_directory(run_id) / "steps.jsonl", payload)

    def append_probe(self, run_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            append_jsonl(self.run_directory(run_id) / "probes.jsonl", payload)

    def update_note(
        self,
        run_id: str,
        note_id: str,
        *,
        text: str,
        category: str,
        updated_at: str,
    ) -> dict[str, Any]:
        with self._lock:
            run_dir = self.run_directory(run_id)
            if not (run_dir / "run.json").is_file():
                raise FileNotFoundError(run_id)
            path = run_dir / "probes.jsonl"
            probes = read_jsonl(path)
            updated: dict[str, Any] | None = None
            for probe in probes:
                if not isinstance(probe, dict):
                    continue
                if probe.get("probeType") != "note" or probe.get("noteId") != note_id:
                    continue
                probe["label"] = category
                probe["summary"] = {"text": text}
                probe["updatedAt"] = updated_at
                updated = probe
                break
            if updated is None:
                raise FileNotFoundError(note_id)
            atomic_write_jsonl(path, probes)
            return updated

    def delete_note(self, run_id: str, note_id: str) -> bool:
        with self._lock:
            run_dir = self.run_directory(run_id)
            if not (run_dir / "run.json").is_file():
                raise FileNotFoundError(run_id)
            path = run_dir / "probes.jsonl"
            probes = read_jsonl(path)
            remaining = [
                probe
                for probe in probes
                if not (
                    isinstance(probe, dict)
                    and probe.get("probeType") == "note"
                    and probe.get("noteId") == note_id
                )
            ]
            if len(remaining) == len(probes):
                raise FileNotFoundError(note_id)
            atomic_write_jsonl(path, remaining)
            return True

    def refresh_reports_if_present(self, run_id: str) -> bool:
        with self._lock:
            run_dir = self.run_directory(run_id)
            if not ((run_dir / "report.md").is_file() or (run_dir / "report.html").is_file()):
                return False
            self.generate_reports(run_id)
            return True

    def append_frontend_event(self, run_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            append_jsonl(self.run_directory(run_id) / "frontend_events.jsonl", payload)

    def get_run(self, run_id: str, *, include_steps: bool = True) -> dict[str, Any] | None:
        with self._lock:
            run_dir = self.run_directory(run_id)
            run = read_json(run_dir / "run.json")
            if not isinstance(run, dict):
                return None
            if include_steps:
                run["steps"] = read_jsonl(run_dir / "steps.jsonl")
                run["probes"] = read_jsonl(run_dir / "probes.jsonl")
                run["frontendEvents"] = read_jsonl(run_dir / "frontend_events.jsonl")
                run["diagnostics"] = diagnose_run(run)
            return run

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        with self._lock:
            for run_json in self.base_directory.glob("*/run.json"):
                run = read_json(run_json)
                if not isinstance(run, dict):
                    continue
                runs.append(
                    {
                        "runId": run.get("runId"),
                        "promptId": run.get("promptId"),
                        "label": run.get("label"),
                        "status": run.get("status"),
                        "createdAt": run.get("createdAt"),
                        "startedAt": run.get("startedAt"),
                        "finishedAt": run.get("finishedAt"),
                        "workflowHash": run.get("workflowHash"),
                        "options": run.get("options", {}),
                        "generationSettings": run.get("generationSettings", {}),
                        "segmentCount": len(run.get("segments", [])),
                        "stepCount": run.get("stepCount", 0),
                        "reportFiles": run.get("reportFiles", {}),
                    }
                )
        runs.sort(
            key=lambda item: item.get("startedAt") or item.get("createdAt") or "",
            reverse=True,
        )
        return runs[: max(1, min(1000, int(limit)))]

    def finalize_from_frontend(self, run_id: str, status: str, event: dict[str, Any]) -> dict[str, Any] | None:
        session = self.active_session(run_id)
        if session is not None:
            session.finalize(status=status, frontend_event=event)
            return self.get_run(run_id, include_steps=False)

        with self._lock:
            run = self.get_run(run_id, include_steps=False)
            if run is None:
                return None
            run["status"] = status
            run["frontendCompletion"] = event
            run["finishedAt"] = event.get("timestamp") or run.get("finishedAt")
            self.persist_run(run)
            self.generate_reports(run_id)
            return run

    def generate_reports(self, run_id: str) -> dict[str, str]:
        with self._lock:
            run = self.get_run(run_id, include_steps=False)
            if run is None:
                raise FileNotFoundError(run_id)
            steps = read_jsonl(self.run_directory(run_id) / "steps.jsonl")
            probes = read_jsonl(self.run_directory(run_id) / "probes.jsonl")
            report_run = dict(run)
            report_run["probes"] = probes
            report_run["diagnostics"] = diagnose_run({**run, "steps": steps})
            report_files = write_reports(self.run_directory(run_id), report_run, steps)
            run["reportFiles"] = report_files
            self.persist_run(run)
            return report_files

    def resolve_artifact(self, run_id: str, relative_path: str) -> Path:
        run_dir = self.run_directory(run_id)
        artifact_dir = (run_dir / "artifacts").resolve()
        candidate = (artifact_dir / relative_path).resolve()
        if artifact_dir != candidate and artifact_dir not in candidate.parents:
            raise ValueError("Artifact path escaped run directory")
        return candidate

    def resolve_report(self, run_id: str, name: str) -> Path:
        standard = {"report.md", "report.html", "run.json", "steps.jsonl"}
        comparison = (
            name.startswith("compare_")
            and name.endswith((".md", ".html"))
            and all(ch.isalnum() or ch in {"-", "_", "."} for ch in name)
        )
        if name not in standard and not comparison:
            raise ValueError("Unsupported report file")
        return self.run_directory(run_id) / name

    def compare_runs(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.get_run(left_id, include_steps=True)
        right = self.get_run(right_id, include_steps=True)
        if left is None or right is None:
            raise FileNotFoundError("One or both runs do not exist")

        left_settings = left.get("generationSettings", {}) or {}
        right_settings = right.get("generationSettings", {}) or {}
        setting_keys = sorted(set(left_settings) | set(right_settings))
        settings_diff = {
            key: {"left": left_settings.get(key), "right": right_settings.get(key)}
            for key in setting_keys
            if left_settings.get(key) != right_settings.get(key)
        }

        left_steps = left.get("steps", [])
        right_steps = right.get("steps", [])
        pair_count = min(len(left_steps), len(right_steps))
        pairs = []
        for index in range(pair_count):
            a = left_steps[index]
            b = right_steps[index]
            left_control = a.get("control", {}) or {}
            right_control = b.get("control", {}) or {}
            left_x0 = a.get("x0", {}) or {}
            right_x0 = b.get("x0", {}) or {}
            pairs.append(
                {
                    "index": index,
                    "left": {
                        "step": a.get("step"),
                        "sigma": a.get("sigma"),
                        "previewFile": a.get("previewFile"),
                        "previewUrl": a.get("previewUrl"),
                        "previewChange": a.get("previewChange"),
                        "x": a.get("x"),
                        "x0": a.get("x0"),
                        "cfg": a.get("cfg"),
                        "control": a.get("control"),
                    },
                    "right": {
                        "step": b.get("step"),
                        "sigma": b.get("sigma"),
                        "previewFile": b.get("previewFile"),
                        "previewUrl": b.get("previewUrl"),
                        "previewChange": b.get("previewChange"),
                        "x": b.get("x"),
                        "x0": b.get("x0"),
                        "cfg": b.get("cfg"),
                        "control": b.get("control"),
                    },
                    "difference": {
                        "sigmaAbsolute": _absolute_difference(a.get("sigma"), b.get("sigma")),
                        "previewChangeAbsolute": _absolute_difference(a.get("previewChange"), b.get("previewChange")),
                        "x0MeanAbsolute": _absolute_difference(left_x0.get("mean"), right_x0.get("mean")),
                        "controlWeightedMeanAbsolute": _absolute_difference(
                            left_control.get("weightedMeanAbs"),
                            right_control.get("weightedMeanAbs"),
                        ),
                    },
                }
            )

        left_prompt = left.get("promptAnalysis", {}) or {}
        right_prompt = right.get("promptAnalysis", {}) or {}
        left_hash = left.get("workflowHash")
        right_hash = right.get("workflowHash")
        return {
            "left": {k: left.get(k) for k in ("runId", "promptId", "nodeId", "label", "status", "createdAt", "options", "generationSettings")},
            "right": {k: right.get(k) for k in ("runId", "promptId", "nodeId", "label", "status", "createdAt", "options", "generationSettings")},
            "workflow": {
                "leftHash": left_hash,
                "rightHash": right_hash,
                "hashMatch": bool(left_hash and left_hash == right_hash),
                "leftNodeCount": len(left_prompt.get("nodes", []) or []),
                "rightNodeCount": len(right_prompt.get("nodes", []) or []),
            },
            "runtime": {"left": _runtime_summary(left), "right": _runtime_summary(right)},
            "modelPatches": {"left": _model_patch_summary(left), "right": _model_patch_summary(right)},
            "settingsDiff": settings_diff,
            "stepPairs": pairs,
            "leftStepCount": len(left_steps),
            "rightStepCount": len(right_steps),
            "disclaimer": "Observed A/B differences are evidence for inspection, not causal percentages or proof of a single quality cause.",
        }

    def generate_comparison_reports(self, left_id: str, right_id: str) -> dict[str, Any]:
        with self._lock:
            comparison = self.compare_runs(left_id, right_id)
            report_files = write_comparison_reports(
                self.run_directory(left_id),
                comparison,
                right_id,
            )
            return {"comparison": comparison, "reportFiles": report_files}

    def delete_runs(self, run_ids: list[str]) -> int:
        deleted = 0
        with self._lock:
            for run_id in run_ids:
                try:
                    path = self.run_directory(run_id)
                except ValueError:
                    continue
                self.release_session(run_id)
                if path.exists():
                    shutil.rmtree(path)
                    deleted += 1
        return deleted


STORE = TraceStore()
