from __future__ import annotations

import logging
import uuid
from typing import Any

from . import PLUGIN_VERSION
from .json_utils import json_safe
from .session import utc_now
from .store import STORE

LOGGER = logging.getLogger("comfy.trace_inspector")
_REGISTERED = False
NOTE_CATEGORIES = {"observation", "hypothesis", "decision", "issue"}


def _parse_optional_note_step(body: dict[str, Any]) -> tuple[bool, int | None]:
    if "step" not in body:
        return False, None
    value = body.get("step")
    if value is None or value == "":
        return True, None
    if isinstance(value, bool):
        raise ValueError("invalid note step")
    step = int(value)
    if step < 0:
        raise ValueError("invalid note step")
    return True, step


def _parse_optional_note_segment_index(body: dict[str, Any]) -> tuple[bool, int | None]:
    if "segmentIndex" not in body:
        return False, None
    value = body.get("segmentIndex")
    if value is None or value == "":
        return True, None
    if isinstance(value, bool):
        raise ValueError("invalid note segment index")
    segment_index = int(value)
    if segment_index < 0:
        raise ValueError("invalid note segment index")
    return True, segment_index


def _run_contains_step(
    run: dict[str, Any],
    step: int | None,
    segment_index: int | None = None,
) -> bool:
    if step is None:
        return segment_index is None
    return any(
        isinstance(item, dict)
        and item.get("step") == step
        and (
            segment_index is None
            or item.get("segmentIndex", 0) == segment_index
        )
        for item in run.get("steps", [])
    )


def register_routes() -> bool:
    global _REGISTERED
    if _REGISTERED:
        return True

    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as exc:
        LOGGER.debug("Trace routes unavailable during import: %s", exc)
        return False

    server = getattr(PromptServer, "instance", None)
    if server is None:
        return False
    routes = server.routes

    @routes.get("/trace-inspector/health")
    async def trace_health(request):
        return web.json_response(
            {
                "ok": True,
                "version": PLUGIN_VERSION,
                "baseDirectory": str(STORE.base_directory),
            }
        )

    @routes.get("/trace-inspector/runs")
    async def trace_runs(request):
        try:
            limit = int(request.query.get("limit", "100"))
        except ValueError:
            limit = 100
        return web.json_response({"runs": STORE.list_runs(limit=limit)})

    @routes.get("/trace-inspector/runs/{run_id}")
    async def trace_run(request):
        try:
            run = STORE.get_run(request.match_info["run_id"], include_steps=True)
        except ValueError:
            return web.json_response({"error": "invalid run id"}, status=400)
        if run is None:
            return web.json_response({"error": "run not found"}, status=404)
        return web.json_response(json_safe(run, max_depth=16))

    @routes.get("/trace-inspector/runs/{run_id}/artifact/{filename:.*}")
    async def trace_artifact(request):
        try:
            path = STORE.resolve_artifact(
                request.match_info["run_id"],
                request.match_info["filename"],
            )
        except ValueError:
            return web.json_response({"error": "invalid artifact path"}, status=400)
        if not path.exists() or not path.is_file():
            return web.json_response({"error": "artifact not found"}, status=404)
        return web.FileResponse(path)

    @routes.get("/trace-inspector/runs/{run_id}/report/{name}")
    async def trace_report(request):
        try:
            path = STORE.resolve_report(
                request.match_info["run_id"],
                request.match_info["name"],
            )
        except ValueError:
            return web.json_response({"error": "unsupported report"}, status=400)
        if not path.exists() or not path.is_file():
            return web.json_response({"error": "report not found"}, status=404)
        return web.FileResponse(path)

    @routes.get("/trace-inspector/compare")
    async def trace_compare(request):
        left = request.query.get("left", "")
        right = request.query.get("right", "")
        try:
            result = STORE.compare_runs(left, right)
        except (ValueError, FileNotFoundError):
            return web.json_response({"error": "one or both runs were not found"}, status=404)
        return web.json_response(json_safe(result))

    @routes.post("/trace-inspector/compare/report")
    async def trace_compare_report(request):
        try:
            body: Any = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        left = str(body.get("left", "")) if isinstance(body, dict) else ""
        right = str(body.get("right", "")) if isinstance(body, dict) else ""
        try:
            result = STORE.generate_comparison_reports(left, right)
        except (ValueError, FileNotFoundError):
            return web.json_response({"error": "one or both runs were not found"}, status=404)
        return web.json_response(json_safe(result))

    @routes.post("/trace-inspector/runs/{run_id}/frontend-events")
    async def trace_frontend_events(request):
        run_id = request.match_info["run_id"]
        try:
            body: Any = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        events = body.get("events", []) if isinstance(body, dict) else []
        if not isinstance(events, list):
            events = [events]

        completion_status: str | None = None
        completion_event: dict[str, Any] | None = None
        for event in events:
            if not isinstance(event, dict):
                continue
            event.setdefault("receivedAt", utc_now())
            try:
                STORE.append_frontend_event(run_id, event)
            except (ValueError, OSError):
                return web.json_response({"error": "run not found or invalid"}, status=404)
            event_type = event.get("type")
            if event_type == "workflow_identity":
                detail = event.get("detail", {})
                workflow_name = detail.get("workflowName") if isinstance(detail, dict) else None
                try:
                    STORE.set_workflow_name(run_id, workflow_name)
                except (ValueError, OSError, FileNotFoundError):
                    return web.json_response({"error": "run not found or invalid"}, status=404)
            if event_type == "execution_success":
                completion_status, completion_event = "success", event
            elif event_type == "execution_interrupted":
                completion_status, completion_event = "interrupted", event
            elif event_type == "execution_error":
                completion_status, completion_event = "error", event

        if completion_status and completion_event:
            STORE.finalize_from_frontend(run_id, completion_status, completion_event)
        return web.json_response({"ok": True, "accepted": len(events)})

    @routes.post("/trace-inspector/runs/{run_id}/finalize")
    async def trace_finalize(request):
        run_id = request.match_info["run_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        status = str(body.get("status", "success"))
        if status not in {"success", "interrupted", "error"}:
            status = "success"
        event = {"type": "manual_finalize", "timestamp": utc_now(), "body": body}
        run = STORE.finalize_from_frontend(run_id, status, event)
        if run is None:
            return web.json_response({"error": "run not found"}, status=404)
        return web.json_response({"ok": True, "run": json_safe(run)})

    @routes.post("/trace-inspector/runs/{run_id}/note")
    async def trace_note(request):
        run_id = request.match_info["run_id"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        text = str(body.get("text", "")).strip()[:8000]
        category = str(body.get("category", "observation"))
        try:
            _step_provided, step = _parse_optional_note_step(body)
            _segment_provided, segment_index = _parse_optional_note_segment_index(body)
        except (TypeError, ValueError):
            return web.json_response({"error": "invalid note step target"}, status=400)
        if not text:
            return web.json_response({"error": "note text is required"}, status=400)
        if category not in NOTE_CATEGORIES:
            return web.json_response({"error": "invalid note category"}, status=400)
        try:
            run = STORE.get_run(run_id, include_steps=True)
        except ValueError:
            return web.json_response({"error": "invalid run id"}, status=400)
        if run is None:
            return web.json_response({"error": "run not found"}, status=404)
        if not _run_contains_step(run, step, segment_index):
            return web.json_response({"error": "note step not found in run"}, status=400)
        payload = {
            "noteId": str(uuid.uuid4()),
            "probeType": "note",
            "label": category,
            "summary": {"text": text},
            "timestamp": utc_now(),
        }
        if step is not None:
            payload["step"] = step
            if segment_index is not None:
                payload["segmentIndex"] = segment_index
        session = STORE.active_session(run_id)
        if session is not None:
            session.add_probe(payload)
        else:
            try:
                STORE.append_probe(run_id, payload)
            except (ValueError, OSError, FileNotFoundError):
                return web.json_response({"error": "run not found"}, status=404)
        STORE.refresh_reports_if_present(run_id)
        return web.json_response({"ok": True, "note": json_safe(payload)})

    @routes.patch("/trace-inspector/runs/{run_id}/notes/{note_id}")
    async def trace_update_note(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        text = str(body.get("text", "")).strip()[:8000]
        category = str(body.get("category", "observation"))
        try:
            step_provided, step = _parse_optional_note_step(body)
            segment_provided, segment_index = _parse_optional_note_segment_index(body)
        except (TypeError, ValueError):
            return web.json_response({"error": "invalid note step target"}, status=400)
        if not text:
            return web.json_response({"error": "note text is required"}, status=400)
        if category not in NOTE_CATEGORIES:
            return web.json_response({"error": "invalid note category"}, status=400)
        try:
            run_id = request.match_info["run_id"]
            run = STORE.get_run(run_id, include_steps=True)
            if run is None:
                raise FileNotFoundError(run_id)
            if segment_provided and not step_provided:
                return web.json_response({"error": "note segment requires step"}, status=400)
            if step_provided and not _run_contains_step(run, step, segment_index if segment_provided else None):
                return web.json_response({"error": "note step not found in run"}, status=400)
            update_kwargs: dict[str, Any] = {
                "text": text,
                "category": category,
                "updated_at": utc_now(),
            }
            if step_provided:
                update_kwargs["step"] = step
            if segment_provided:
                update_kwargs["segment_index"] = segment_index
            note = STORE.update_note(
                run_id,
                request.match_info["note_id"],
                **update_kwargs,
            )
            STORE.refresh_reports_if_present(run_id)
        except (ValueError, OSError, FileNotFoundError):
            return web.json_response({"error": "run or note not found"}, status=404)
        return web.json_response({"ok": True, "note": json_safe(note)})

    @routes.delete("/trace-inspector/runs/{run_id}/notes/{note_id}")
    async def trace_delete_note(request):
        try:
            STORE.delete_note(request.match_info["run_id"], request.match_info["note_id"])
            STORE.refresh_reports_if_present(request.match_info["run_id"])
        except (ValueError, OSError, FileNotFoundError):
            return web.json_response({"error": "run or note not found"}, status=404)
        return web.json_response({"ok": True})

    @routes.post("/trace-inspector/runs/delete")
    async def trace_delete_runs(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        run_ids = body.get("runIds", []) if isinstance(body, dict) else []
        if not isinstance(run_ids, list):
            return web.json_response({"error": "runIds must be an array"}, status=400)
        return web.json_response({"deleted": STORE.delete_runs([str(v) for v in run_ids])})

    _REGISTERED = True
    return True
