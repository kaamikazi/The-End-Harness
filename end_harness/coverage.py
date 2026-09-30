"""Candidate-bound evidence reporting. These summaries never decide acceptance."""
from copy import deepcopy
from dataclasses import asdict
from .artifacts import artifact_identity, original_identity


def check_outcome(check_id, *, status="UNEXECUTED", reason="not_attempted", **values):
    return {"check_id": check_id, "status": status, "verdict": None, "reason": reason,
            "execution_id": None, "receipt": None, "check_version": None, "fixture_hash": None,
            **values}


def coverage_record(run_id, engine, *, artifact=None, candidate_hash=None,
                    hash_unavailable_reason=None, required=(), optional=(), checks=(),
                    unsupported_requests=(), status="unavailable", reason=None):
    checks = deepcopy(list(checks))
    completed = sorted({c["check_id"] for c in checks if c["status"] == "COMPLETED"})
    return {"schema_version": "1.1", "run_id": run_id, "engine": deepcopy(engine),
            "artifact": deepcopy(artifact), "candidate_hash": candidate_hash,
            "hash_unavailable_reason": hash_unavailable_reason, "status": status, "reason": reason,
            "required": sorted(set(required)), "optional": sorted(set(optional)-set(required)),
            "checks": checks, "completed": completed,
            "passed": sorted({c["check_id"] for c in checks if c["status"] == "COMPLETED" and c["verdict"] == "PASS"}),
            "failed": sorted({c["check_id"] for c in checks if c["status"] == "COMPLETED" and c["verdict"] == "FAIL"}),
            "errored": sorted({c["check_id"] for c in checks if c["status"] in ("ERROR", "TIMEOUT")}),
            "unknown": sorted({c["check_id"] for c in checks if c["status"] == "UNKNOWN"}),
            "missing": sorted(set(required)-set(completed)),
            "unsupported_requests": deepcopy(list(unsupported_requests)),
            "repeat_policy": "latest_collection_same_candidate_and_artifact_no_merge",
            "repeat_count": 1, "conflicting_checks": []}


def final_coverage(run_id, result, trajectory, history, required, artifact_schema="deployment-policy/1"):
    """Resolve END's actual returned identity, then select one exact collection."""
    def unavailable(reason, engine=None, **binding):
        return coverage_record(run_id, engine, required=required,
            checks=[check_outcome(c, status="UNAVAILABLE", reason=reason) for c in sorted(set(required))],
            reason=reason, **binding)
    if not result:
        return unavailable("engine_result_unavailable")
    trajectory_id = result.get("trajectory_id")
    candidate_id = result.get("best_candidate_id")
    content = result.get("answer")
    if trajectory is not None:
        if trajectory.get("trajectory_id") != trajectory_id:
            return unavailable("trajectory_identity_mismatch")
        final_id = trajectory.get("final_candidate_id")
        if candidate_id is not None and candidate_id != final_id:
            return unavailable("engine_final_identity_conflict")
        candidate_id = final_id
        candidate = next((c for c in trajectory.get("candidates", ()) if c["candidate_id"] == candidate_id), None)
        if candidate and candidate["content"] != content:
            return unavailable("returned_content_mismatch")
        if candidate_id and candidate is None:
            return unavailable("final_candidate_record_unavailable")
    if not trajectory_id or not candidate_id or not isinstance(content, str):
        return unavailable("final_candidate_identity_unavailable")
    ref = {"trajectory_id": trajectory_id, "local_id": candidate_id}
    binding = original_identity(content)
    try:
        artifact = asdict(artifact_identity(content, artifact_schema))
    except (ValueError, UnicodeError):
        artifact = None
    matching = [h for h in history if h.get("schema_version") == "1.1" and h.get("run_id") == run_id
        and h.get("engine") == ref and h.get("artifact") == artifact
        and h.get("candidate_hash") == binding["candidate_hash"]
        and h.get("hash_unavailable_reason") == binding["hash_unavailable_reason"]]
    # Unencodable content has no hash identity, so it can never match positive evidence.
    if binding["candidate_hash"] is None:
        return unavailable("final_content_has_no_utf8_identity", ref, artifact=None, **binding)
    if not matching:
        return unavailable("no_matching_final_candidate_evidence", ref, artifact=artifact, **binding)
    selected = deepcopy(matching[-1])
    selected["required"] = sorted(set(required))
    selected["optional"] = sorted(set(selected["optional"])-set(required))
    selected["missing"] = sorted(set(required)-set(selected["completed"]))
    selected["repeat_count"] = len(matching)
    by_check = {}
    for collection in matching:
        for check in collection["checks"]:
            by_check.setdefault(check["check_id"], set()).add((check["status"], check["verdict"]))
    selected["conflicting_checks"] = sorted(c for c, outcomes in by_check.items() if len(outcomes) > 1)
    return selected
