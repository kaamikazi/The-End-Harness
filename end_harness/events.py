"""Single-writer JSONL journal; recovery annotates original evidence, never replays it."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from .encoding import canonical, diagnostic, digest, strict_loads, write_once
from .coverage import coverage_record, final_coverage


class JournalError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class EngineRef:
    trajectory_id: str
    local_id: str | None = None


@dataclass(frozen=True)
class RuntimeEvent:
    schema_version: str
    run_id: str
    seq: int
    timestamp: str
    type: str
    payload: dict
    call_id: str | None = None
    parent_seq: int | None = None
    engine: EngineRef | None = None


class Journal:
    def __init__(self, directory: Path, run_id: str):
        self.directory, self.run_id = Path(directory), run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / "events.jsonl"
        self._stream = self.path.open("xb")
        self.seq = 0
        self.failed = False

    def append(self, kind: str, payload: dict, *, call_id=None, parent_seq=None, engine=None) -> RuntimeEvent:
        if self.failed:
            raise JournalError("Journal is poisoned after a persistence failure")
        event = RuntimeEvent("1.0", self.run_id, self.seq + 1, utc_now(), kind,
                             payload, call_id, parent_seq, engine)
        try:
            self._stream.write(canonical(asdict(event)) + b"\n")
            self.checkpoint()
        except Exception as exc:
            self.failed = True
            raise JournalError(f"Journal persistence failed: {exc}") from exc
        self.seq += 1
        return event

    def checkpoint(self):
        self._stream.flush()
        os.fsync(self._stream.fileno())

    def close(self):
        self._stream.close()


def inspect_run(directory: Path) -> dict:
    directory = Path(directory)
    raw = (directory / "events.jsonl").read_bytes()
    lines = raw.splitlines(keepends=True)
    events, truncated, pending, run_id = [], None, {}, None
    for index, line in enumerate(lines):
        # Only a final record without the newline commit marker may be incomplete.
        if index == len(lines)-1 and not line.endswith(b"\n"):
            truncated = {"offset": sum(map(len, lines[:index])), "bytes": len(line), "sha256": digest(line)}
            break
        try:
            e = strict_loads(line)
            required = set(RuntimeEvent.__dataclass_fields__)
            if not isinstance(e, dict) or set(e) != required or e["schema_version"] != "1.0":
                raise ValueError("Invalid event envelope")
            if type(e["seq"]) is not int or e["seq"] != len(events)+1:
                raise ValueError("Non-monotonic sequence")
            if not isinstance(e["run_id"], str) or not e["run_id"]:
                raise ValueError("Missing run ID")
            run_id = run_id or e["run_id"]
            if e["run_id"] != run_id or not isinstance(e["payload"], dict):
                raise ValueError("Invalid run or payload")
            if datetime.fromisoformat(e["timestamp"]).utcoffset().total_seconds() != 0:
                raise ValueError("Timestamp must be UTC")
            if e["engine"] is not None and (set(e["engine"]) != {"trajectory_id", "local_id"}
                    or not e["engine"]["trajectory_id"]):
                raise ValueError("Invalid Engine reference")
            if not isinstance(e["type"], str) or not e["type"]:
                raise ValueError("Invalid event type")
            if e["parent_seq"] is not None and (type(e["parent_seq"]) is not int or not 0 < e["parent_seq"] < e["seq"]):
                raise ValueError("Invalid parent link")
            if e["type"] in ("model/call", "check/call", "judge/call"):
                if not e["call_id"] or e["call_id"] in pending or any(x["call_id"] == e["call_id"] for x in events):
                    raise ValueError("Duplicate or missing call ID")
                pending[e["call_id"]] = e
            if e["type"] in ("model/result", "check/result", "judge/result"):
                call = pending.pop(e["call_id"], None)
                if call is None or call["seq"] != e["parent_seq"] or call["type"].split('/')[0] != e["type"].split('/')[0]:
                    raise ValueError("Result does not link to an open matching call")
            events.append(e)
        except Exception as exc:
            raise JournalError(f"Corrupt committed record at line {index+1}: {exc}") from exc
    summary = {"schema_version": "1.0", "run_id": run_id, "journal_sha256": digest(raw),
               "event_count": len(events), "truncated_tail": truncated,
               "unfinished_calls": [{"call_id": e["call_id"], "call_seq": e["seq"], "type": e["type"],
                                     "status": "OUTCOME_UNKNOWN"} for e in pending.values()],
               "completed": bool(events and events[-1]["type"] == "run/end" and not pending and not truncated),
               "engine_state": "post-run snapshot imported" if any(e["type"] == "engine/import_complete" for e in events)
                               else "not durably imported; live cognitive state unavailable",
               "reexecuted": False}
    final = next((e["payload"] for e in reversed(events) if e["type"] == "run/end"), None)
    persisted = None
    summary_file = {"status": "missing", "error": None}
    if (directory / "result.json").exists():
        try:
            persisted = strict_loads((directory / "result.json").read_bytes())
            if not isinstance(persisted, dict) or persisted.get("run_id") != run_id:
                raise ValueError("Summary does not match journal run")
            summary_file["status"] = "readable"
            # Later persistence failures are allowed to extend failures/status, never change Engine evidence.
            if final and any(persisted.get(k) != final.get(k) for k in
                             ("engine_result", "evidence_coverage", "final_candidate", "final_candidate_coverage")):
                raise ValueError("Summary conflicts with journal outcome/evidence")
        except Exception as exc:
            summary_file = {"status": "invalid", "error": diagnostic(exc)}
            persisted = None
    observed = persisted or final
    source = "summary_file" if persisted else "run/end" if final else None
    snapshot_file = {"status": "missing", "error": None}
    trajectory = None
    if (directory / "trajectory.json").exists():
        try:
            trajectory = strict_loads((directory / "trajectory.json").read_bytes())
            if not isinstance(trajectory, dict) or not trajectory.get("trajectory_id"):
                raise ValueError("Invalid trajectory snapshot")
            known_trajectories = {e["engine"]["trajectory_id"] for e in events if e["engine"]}
            if trajectory["trajectory_id"] not in known_trajectories:
                raise ValueError("Trajectory snapshot has no matching journal identity")
            snapshot_file["status"] = "readable"
        except Exception as exc:
            snapshot_file = {"status": "invalid", "error": diagnostic(exc)}
            trajectory = None
    if observed is None and trajectory and trajectory.get("final_result"):
        observed = {"engine_result": trajectory["final_result"], "evidence_coverage": [
            e["payload"] for e in events if e["type"] == "checks/coverage"]}
        source = "trajectory_snapshot"
    data = {key: observed.get(key) if observed else None for key in (
        "engine_result", "engine_result_source", "harness_stop_cause", "budget", "evidence_coverage", "limitations", "failures")}
    data["source"] = source
    if source in (None, "trajectory_snapshot"):
        errors = [e["payload"] for e in events if e["type"] == "run/error"]
        if errors:
            data["harness_stop_cause"] = errors[-1].get("harness_stop_cause")
            data["failures"] = [p["failure"] for p in errors if "failure" in p]
        exhaustion = next((e["payload"] for e in reversed(events) if e["type"] == "budget/exhausted"), None)
        if exhaustion:
            data["budget"] = exhaustion
            data["harness_stop_cause"] = data["harness_stop_cause"] or exhaustion.get("stop_cause")
    start = next((e["payload"] for e in events if e["type"] == "run/start"), {})
    if observed and observed.get("schema_version") == "1.1":
        data["final_candidate"] = observed.get("final_candidate")
        data["final_candidate_coverage"] = observed.get("final_candidate_coverage")
    elif source == "trajectory_snapshot" and start.get("result_schema_version") == "1.1":
        coverage = final_coverage(run_id, data["engine_result"], trajectory, data["evidence_coverage"] or (),
                                  start.get("required_checks", ()), start.get("artifact_schema", "deployment-policy/1"))
        data.update(final_candidate=coverage["engine"], final_candidate_coverage=coverage)
    else:
        engine_result = data["engine_result"] or {}
        ref = ({"trajectory_id": engine_result["trajectory_id"], "local_id": engine_result["best_candidate_id"]}
               if engine_result.get("trajectory_id") and engine_result.get("best_candidate_id") else None)
        data["final_candidate"] = ref
        data["final_candidate_coverage"] = coverage_record(run_id, ref, reason=
            "legacy_format_has_no_artifact_bound_final_coverage" if observed else "final_result_unavailable")
        data["final_candidate_coverage"]["repeat_count"] = 0
    summary["result"] = data
    summary["persistence"] = {
        "journal_structure": "closed" if summary["completed"] else "incomplete",
        "end_record_present": final is not None,
        "writer_closure_observation": persisted.get("journal_closure", "unavailable") if persisted and persisted.get("schema_version") == "1.1" else "unavailable",
        "summary_file": summary_file, "trajectory_snapshot_file": snapshot_file,
        "summary_write_confirmation": "not_reconstructible_from_file_itself",
        "cleanup_confirmation": "unavailable",
        "trajectory_import_record_present": any(e["type"] == "engine/import_complete" for e in events)}
    summary["inspection_status"] = ("closed_" if summary["completed"] else "incomplete_") + "summary_" + summary_file["status"]
    summary["check_outcomes"] = [{"execution_id": e["call_id"], "engine": e["engine"],
        "status": e["payload"]["receipt"]["status"], "verdict": e["payload"]["receipt"]["verdict"],
        "check_id": e["payload"]["receipt"]["check_id"]} for e in events
        if e["type"] == "check/result" and "receipt" in e["payload"]]
    recovery = directory / "recovery.json"
    if recovery.exists():
        closure = strict_loads(recovery.read_bytes())
        if closure["journal_sha256"] != summary["journal_sha256"]:
            raise JournalError("Journal changed after recovery closure")
        summary["closure"] = closure
    return summary


def close_interrupted(directory: Path) -> dict:
    """Publish an immutable closure sidecar. Call only on a stopped writer."""
    directory = Path(directory)
    summary = inspect_run(directory)
    if "closure" in summary or summary["completed"]:
        return summary
    # The sidecar leaves even a torn final record byte-for-byte intact.
    closure = {"schema_version": "1.0", "run_id": summary["run_id"],
               "journal_sha256": summary["journal_sha256"], "type": "run/recovery_closed",
               "provenance": "historical_inspection", "reexecuted": False,
               "unfinished_calls": summary["unfinished_calls"], "truncated_tail": summary["truncated_tail"],
               "engine_state": summary["engine_state"]}
    # Deterministic bytes make repeated inspection idempotent; atomic publication avoids a torn sidecar.
    temporary = directory / "recovery.pending"
    write_once(temporary, canonical(closure) + b"\n")
    os.replace(temporary, directory / "recovery.json")
    return inspect_run(directory)
