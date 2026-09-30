"""Whole-document JSON binding. No markdown extraction or prose repair."""
from dataclasses import dataclass
from pathlib import Path
from .encoding import canonical, digest, strict_loads, write_once


@dataclass(frozen=True)
class CandidateArtifact:
    candidate_hash: str
    tested_hash: str
    artifact_type: str = "application/json"
    schema_version: str = "deployment-policy/1"
    parser: str = "strict-whole-json/canonical-utf8-v1"


def original_identity(content: str) -> dict:
    try:
        return {"candidate_hash": digest(content.encode("utf-8")), "hash_unavailable_reason": None}
    except UnicodeError:
        return {"candidate_hash": None, "hash_unavailable_reason": "original_utf8_unavailable_invalid_unicode"}


def artifact_identity(content: str, schema_version="deployment-policy/1") -> CandidateArtifact:
    original = content.encode("utf-8")
    parsed = strict_loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Candidate must be one JSON object")
    return CandidateArtifact(digest(original), digest(canonical(parsed)), schema_version=schema_version)


class ArtifactStore:
    def __init__(self, directory: Path, schema_version="deployment-policy/1"):
        self.directory = Path(directory)
        self.schema_version = schema_version

    def capture(self, content: str) -> CandidateArtifact:
        original = content.encode("utf-8")
        original_hash = digest(original)
        write_once(self.directory / (original_hash + ".candidate"), original)
        parsed = strict_loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Candidate must be one JSON object")
        tested = canonical(parsed)
        tested_hash = digest(tested)
        write_once(self.directory / (tested_hash + ".json"), tested)
        return CandidateArtifact(original_hash, tested_hash, schema_version=self.schema_version)

    def load(self, artifact: CandidateArtifact) -> dict:
        original = (self.directory / (artifact.candidate_hash + ".candidate")).read_bytes()
        tested = (self.directory / (artifact.tested_hash + ".json")).read_bytes()
        if digest(original) != artifact.candidate_hash or digest(tested) != artifact.tested_hash:
            raise ValueError("Stored artifact hash mismatch")
        if canonical(strict_loads(original)) != tested:
            raise ValueError("Original and tested artifacts do not match")
        return strict_loads(tested)
