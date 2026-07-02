"""Repository operations: init, staging, commits, branches, merge, blame, verify.

Semantics contracts: docs/prd/cogit-mvp.md, docs/spec/*, docs/invariants.md.
"""

import os
import re
from datetime import datetime, timezone

from .errors import (
    ConcurrentUpdateError,
    CorruptionError,
    RepositoryNotFound,
    UnsupportedFormatError,
    UserError,
)
from .index_state import EMPTY_INDEX, index_is_empty, load_index, save_index
from .objects import is_oid, validate_object
from .refs import RefStore, validate_ref_name
from .secrets import reject_suspected_secrets
from .store import ObjectStore

HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_CONFIG = """[core]
\trepositoryFormatVersion = 1
[extensions]
\tobjectFormat = sha256
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_config(text: str) -> dict:
    """Minimal INI parser for .cogit/config."""
    sections = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            sections.setdefault(current, {})
            continue
        if "=" in line and current is not None:
            key, value = line.split("=", 1)
            sections[current][key.strip()] = value.strip()
    return sections


def init_repository(path: str) -> str:
    """Create .cogit layout. Idempotent: never destroys existing state (US-001)."""
    cogit_dir = os.path.join(path, ".cogit")
    for sub in (
        "",
        "objects",
        "tmp",
        "logs",
        os.path.join("logs", "refs", "heads"),
        os.path.join("logs", "refs", "anchors"),
        os.path.join("refs", "heads"),
        os.path.join("refs", "anchors"),
        os.path.join("refs", "remotes"),
    ):
        os.makedirs(os.path.join(cogit_dir, sub), exist_ok=True)
    head_path = os.path.join(cogit_dir, "HEAD")
    if not os.path.exists(head_path):
        with open(head_path, "w", encoding="utf-8") as handle:
            handle.write("ref: refs/heads/main\n")
    config_path = os.path.join(cogit_dir, "config")
    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write(DEFAULT_CONFIG)
    index_path = os.path.join(cogit_dir, "index.json")
    if not os.path.exists(index_path):
        save_index(cogit_dir, dict(EMPTY_INDEX))
    return cogit_dir


def find_repository(start: str) -> str:
    current = os.path.abspath(start)
    while True:
        candidate = os.path.join(current, ".cogit")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            raise RepositoryNotFound(f"no .cogit repository found from '{start}'")
        current = parent


class Repository:
    def __init__(self, cogit_dir: str):
        self.cogit_dir = cogit_dir
        self.store = ObjectStore(cogit_dir)
        self.refs = RefStore(cogit_dir)
        self._check_format()

    @classmethod
    def open(cls, start: str = ".") -> "Repository":
        return cls(find_repository(start))

    def _check_format(self):
        config_path = os.path.join(self.cogit_dir, "config")
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                config = _parse_config(handle.read())
        except FileNotFoundError as exc:
            raise RepositoryNotFound(f"{self.cogit_dir}: missing config") from exc
        version = config.get("core", {}).get("repositoryFormatVersion")
        if version != "1":
            raise UnsupportedFormatError(f"unsupported repositoryFormatVersion: {version}")
        extensions = config.get("extensions", {})
        if extensions.get("objectFormat", "sha256") != "sha256":
            raise UnsupportedFormatError(f"unsupported objectFormat: {extensions.get('objectFormat')}")
        unknown = set(extensions) - {"objectFormat"}
        if unknown:
            raise UnsupportedFormatError(f"unknown required extensions: {sorted(unknown)}")

    # -- HEAD / resolution -----------------------------------------------------

    def head_info(self):
        """Return (branch_refname_or_None, thought_oid_or_None)."""
        kind, value = self.refs.read_head()
        if kind == "symbolic":
            return value, self.refs.read_ref(value)
        return None, value

    def resolve(self, name: str) -> str:
        """Resolve a ref-ish name to a thought oid. Anchors dereference to targets."""
        if name in (None, "", "HEAD"):
            _branch, thought = self.head_info()
            if thought is None:
                raise UserError("resolve: HEAD has no commits yet")
            return thought
        if is_oid(name):
            return name
        if HEX64_RE.match(name):
            return "sha256:" + name
        candidates = [name] if name.startswith("refs/") else [f"refs/heads/{name}", f"refs/anchors/{name}"]
        for refname in candidates:
            try:
                validate_ref_name(refname)
            except UserError:
                continue
            target = self.refs.read_ref(refname)
            if target is None:
                continue
            if refname.startswith("refs/anchors/"):
                anchor = self._read_typed(target, "anchor")
                return anchor["target"]
            return target
        # refs take precedence; a hex-looking name falls through to prefix expansion
        stripped = name[len("sha256:") :] if name.startswith("sha256:") else name
        if ObjectStore.PREFIX_RE.match(stripped):
            return self.store.expand_prefix(name)
        raise UserError(f"resolve: unknown ref or object '{name}'")

    def expand_object_id(self, name: str) -> str:
        """Full oid, bare 64-hex, or unique prefix -> full oid (no ref lookup)."""
        if is_oid(name):
            return name
        return self.store.expand_prefix(name)

    def _read_typed(self, oid: str, expected: str) -> dict:
        obj = self.store.read(oid)
        if obj["type"] != expected:
            raise UserError(f"{oid} is a {obj['type']}, expected {expected}")
        return obj

    def _mindset_assertions(self, thought_oid) -> set:
        if thought_oid is None:
            return set()
        thought = self._read_typed(thought_oid, "thought")
        mindset = self._read_typed(thought["mindset"], "mindset")
        return set(mindset["assertions"])

    # -- staging ------------------------------------------------------------------

    def add_fact(self, doc: dict):
        """Write claim+assertion objects and stage the assertion. Returns (claim_oid, assertion_oid)."""
        if not isinstance(doc, dict):
            raise UserError("add-fact: input must be a JSON object")
        unknown = set(doc) - {"claim", "assertion"}
        if unknown:
            raise UserError(f"add-fact: unknown top-level fields: {sorted(unknown)}")
        if "assertion" not in doc:
            raise UserError("add-fact: 'assertion' is required")
        reject_suspected_secrets(doc, "add-fact")

        assertion = dict(doc["assertion"])
        if "claim" in doc:
            claim = dict(doc["claim"])
            claim.setdefault("type", "claim")
            claim_oid = self.store.write(claim)
            if "claim" in assertion and assertion["claim"] != claim_oid:
                raise UserError("add-fact: assertion.claim does not match the provided claim object")
            assertion["claim"] = claim_oid
        else:
            claim_oid = assertion.get("claim")
            if not is_oid(claim_oid) or not self.store.exists(claim_oid):
                raise UserError("add-fact: assertion.claim must reference an existing claim")
            self._read_typed(claim_oid, "claim")
        assertion.setdefault("type", "assertion")
        assertion_oid = self.store.write(assertion)

        index = load_index(self.cogit_dir)
        self._pin_base_mindset(index)
        if assertion_oid not in index["staged_facts"]:
            index["staged_facts"].append(assertion_oid)
            index["staged_facts"].sort()
        save_index(self.cogit_dir, index)
        return claim_oid, assertion_oid

    def remove_fact(self, assertion_oid: str, reason: str):
        if not is_oid(assertion_oid):
            raise UserError(f"remove-fact: invalid assertion id '{assertion_oid}'")
        if not reason or not reason.strip():
            raise UserError("remove-fact: an explicit --reason is required")
        reject_suspected_secrets(reason, "remove-fact")
        index = load_index(self.cogit_dir)
        self._pin_base_mindset(index)
        if assertion_oid in index["staged_facts"]:
            index["staged_facts"].remove(assertion_oid)
            save_index(self.cogit_dir, index)
            return "unstaged"
        base_set = self._base_assertions(index)
        if assertion_oid not in base_set:
            raise UserError("remove-fact: assertion is neither staged nor active in the base mindset")
        if all(entry["id"] != assertion_oid for entry in index["removed_facts"]):
            index["removed_facts"].append({"id": assertion_oid, "reason": reason})
            index["removed_facts"].sort(key=lambda entry: entry["id"])
        save_index(self.cogit_dir, index)
        return "removed"

    def _pin_base_mindset(self, index):
        """Record the mindset the staging round started from (first staging op)."""
        if index["base_mindset"] is None and not index["staged_facts"] and not index["removed_facts"]:
            _branch, thought_oid = self.head_info()
            if thought_oid is not None:
                thought = self._read_typed(thought_oid, "thought")
                index["base_mindset"] = thought["mindset"]

    def _base_assertions(self, index) -> set:
        if index["base_mindset"] is None:
            return set()
        mindset = self._read_typed(index["base_mindset"], "mindset")
        return set(mindset["assertions"])

    # -- commit ------------------------------------------------------------------

    def commit_thought(self, message: str, author: str, timestamp: str = None) -> str:
        if not message or not message.strip():
            raise UserError("commit-thought: --message is required")
        if not author or not author.strip():
            raise UserError("commit-thought: --author is required")
        reject_suspected_secrets(message, "commit-thought")
        timestamp = timestamp or now_utc()

        index = load_index(self.cogit_dir)
        if index["conflicts"]:
            raise UserError(
                f"commit-thought: {len(index['conflicts'])} unresolved conflict(s) block commit; "
                "use `cogit resolve` or edit index.json"
            )
        merge_state = index["merge"]
        if not index["staged_facts"] and not index["removed_facts"] and merge_state is None:
            raise UserError("commit-thought: nothing staged; use add-fact/remove-fact first")

        branch, parent = self.head_info()
        parent_mindset = None
        if parent is not None:
            parent_mindset = self._read_typed(parent, "thought")["mindset"]
        if index["base_mindset"] != parent_mindset:
            raise ConcurrentUpdateError(
                "commit-thought: HEAD moved since staging began "
                f"(staged against {index['base_mindset'] or 'null'}, HEAD mindset is {parent_mindset or 'null'})"
            )
        if merge_state is not None and merge_state["ours"] != parent:
            raise ConcurrentUpdateError("commit-thought: HEAD moved since merge started")

        base_set = self._base_assertions(index)
        removed_ids = {entry["id"] for entry in index["removed_facts"]}
        new_assertions = sorted((base_set | set(index["staged_facts"])) - removed_ids)
        self._check_negation_consistency(new_assertions, index)

        mindset_oid = self.store.write(
            {"type": "mindset", "assertions": new_assertions, "created_at": timestamp}
        )
        if merge_state is not None:
            parents = [merge_state["ours"], merge_state["theirs"]]
            operation = "merge"
        else:
            parents = [parent] if parent else []
            operation = "commit"
        thought_oid = self.store.write(
            {
                "type": "thought",
                "parents": parents,
                "mindset": mindset_oid,
                "operation": operation,
                "message": message,
                "author": author,
                "timestamp": timestamp,
            }
        )

        reason = message
        if branch is not None:
            self.refs.update_ref(branch, thought_oid, parent, author, operation, reason, timestamp)
            self.refs.append_reflog("HEAD", parent, thought_oid, author, operation, reason, timestamp)
        else:
            # detached: HEAD content must still be the parent we committed from
            self.refs.write_head(
                thought_oid, parent, author, operation, reason, timestamp, expected_raw=parent
            )
        # Clear index only after the ref moved (invariant: mutation ordering).
        save_index(self.cogit_dir, dict(EMPTY_INDEX))
        return thought_oid

    # -- negation (invariants 24-25) -------------------------------------------------

    def _negation_group(self, claim_oid: str) -> str:
        """Follow the negates chain to its root claim (the proposition family)."""
        seen = set()
        current = claim_oid
        while True:
            if current in seen:
                raise CorruptionError(f"claims: negation cycle involving {current}")
            seen.add(current)
            negated = self._read_typed(current, "claim").get("negates")
            if negated is None:
                return current
            current = negated

    def _check_negation_consistency(self, assertion_ids, index):
        """Reject a mindset holding both a claim and its negation (invariant 25)."""
        claim_of = {aid: self._read_typed(aid, "assertion")["claim"] for aid in assertion_ids}
        active_claims = set(claim_of.values())
        for aid, claim_oid in sorted(claim_of.items()):
            negated = self._read_typed(claim_oid, "claim").get("negates")
            if negated is not None and negated in active_claims:
                raise UserError(
                    f"commit-thought: contradictory mindset — {aid} activates a claim that negates "
                    f"{negated}, which is still active; remove the original assertion with reason "
                    "'refuted' first (invariant 25)"
                )
        # When a negation is being activated, the original's removal must say why.
        staged_negated = set()
        for aid in index["staged_facts"]:
            claim_oid = self._read_typed(aid, "assertion")["claim"]
            negated = self._read_typed(claim_oid, "claim").get("negates")
            if negated is not None:
                staged_negated.add(negated)
        if staged_negated:
            for entry in index["removed_facts"]:
                removed_claim = self._read_typed(entry["id"], "assertion")["claim"]
                if removed_claim in staged_negated and entry["reason"] != "refuted":
                    raise UserError(
                        f"commit-thought: removal of {entry['id']} must use reason 'refuted' — "
                        "a staged assertion negates its claim (invariant 25)"
                    )

    # -- branches / checkout -------------------------------------------------------

    def branch(self, name: str, thought: str = None, actor: str = "agent", timestamp: str = None) -> str:
        refname = f"refs/heads/{name}"
        validate_ref_name(refname)
        if self.refs.read_ref(refname) is not None:
            raise UserError(f"branch: '{name}' already exists")
        target = self.resolve(thought) if thought else self.resolve("HEAD")
        self._read_typed(target, "thought")
        self.refs.update_ref(
            refname, target, None, actor, "branch", f"created from {thought or 'HEAD'}", timestamp or now_utc()
        )
        return target

    def list_branches(self):
        current, _thought = self.head_info()
        return [
            {"name": refname[len("refs/heads/") :], "target": target, "current": refname == current}
            for refname, target in self.refs.list_refs("refs/heads")
        ]

    def checkout(self, target: str, actor: str = "agent", timestamp: str = None):
        index = load_index(self.cogit_dir)
        if not index_is_empty(index):
            raise UserError(
                "checkout: index is not empty (staged facts, removals, conflicts, or merge in progress); "
                "commit or clear it first — MVP blocks checkout with a dirty index"
            )
        timestamp = timestamp or now_utc()
        old_raw = self.refs.read_head_raw()
        kind, value = self.refs.parse_head(old_raw)
        old_thought = self.refs.read_ref(value) if kind == "symbolic" else value

        branch_ref = f"refs/heads/{target}" if not target.startswith("refs/") else target
        is_branch = False
        try:
            validate_ref_name(branch_ref)
            is_branch = self.refs.read_ref(branch_ref) is not None
        except UserError:
            pass

        if is_branch:
            reason = f"moving to branch {target}"
            self.refs.write_head(
                f"ref: {branch_ref}", old_thought, actor, "checkout", reason, timestamp, expected_raw=old_raw
            )
            mode = "branch"
            new_thought = self.refs.read_ref(branch_ref)
        else:
            new_thought = self.resolve(target)
            self._read_typed(new_thought, "thought")
            reason = f"detached at {target}"
            self.refs.write_head(
                new_thought, old_thought, actor, "checkout", reason, timestamp, expected_raw=old_raw
            )
            mode = "detached"
        save_index(self.cogit_dir, dict(EMPTY_INDEX))
        return mode, new_thought

    # -- history -----------------------------------------------------------------

    def _ancestry(self, start_oid: str):
        """Return {oid: thought} for all thoughts reachable from start."""
        seen = {}
        stack = [start_oid]
        while stack:
            oid = stack.pop()
            if oid in seen:
                continue
            thought = self._read_typed(oid, "thought")
            seen[oid] = thought
            stack.extend(thought["parents"])
        return seen

    def _topo_oldest_first(self, thoughts: dict):
        """Kahn topological order, oldest first; ties broken by (timestamp, oid)."""
        pending = {oid: [p for p in t["parents"] if p in thoughts] for oid, t in thoughts.items()}
        emitted = []
        done = set()
        while pending:
            ready = sorted(
                (oid for oid, parents in pending.items() if all(p in done for p in parents)),
                key=lambda oid: (thoughts[oid]["timestamp"], oid),
            )
            if not ready:
                raise CorruptionError("history: cycle detected in thought graph")
            for oid in ready:
                emitted.append(oid)
                done.add(oid)
                del pending[oid]
        return emitted

    def log(self, start: str = None):
        start_oid = self.resolve(start or "HEAD")
        thoughts = self._ancestry(start_oid)
        order = self._topo_oldest_first(thoughts)
        return [{"id": oid, **thoughts[oid]} for oid in reversed(order)]

    def reflog(self, refname: str = "HEAD"):
        if refname != "HEAD" and not refname.startswith("refs/"):
            refname = f"refs/heads/{refname}"
        entries = self.refs.read_reflog(refname)
        return list(reversed(entries))

    def is_ancestor(self, maybe_ancestor: str, descendant: str) -> bool:
        return maybe_ancestor in self._ancestry(descendant)

    def merge_base(self, a: str, b: str):
        """Nearest common ancestor by BFS edge distance from b."""
        ancestors_a = set(self._ancestry(a))
        queue = [b]
        seen = set()
        while queue:
            oid = queue.pop(0)
            if oid in seen:
                continue
            seen.add(oid)
            if oid in ancestors_a:
                return oid
            queue.extend(self._read_typed(oid, "thought")["parents"])
        return None

    # -- diff ----------------------------------------------------------------------

    def _assertions_of(self, name: str) -> set:
        """Accept a thought/mindset oid, unique prefix, or ref-ish name."""
        oid = self.resolve(name)  # refs first; hex names fall through to prefix expansion
        obj = self.store.read(oid)
        if obj["type"] == "mindset":
            return set(obj["assertions"])
        if obj["type"] == "thought":
            return set(self._read_typed(obj["mindset"], "mindset")["assertions"])
        raise UserError(f"diff: {oid} is a {obj['type']}, expected thought or mindset")

    def diff(self, a: str, b: str):
        set_a = self._assertions_of(a)
        set_b = self._assertions_of(b)
        return {
            "added": sorted(set_b - set_a),
            "removed": sorted(set_a - set_b),
            "unchanged": sorted(set_a & set_b),
        }

    # -- merge ------------------------------------------------------------------------

    def _claims_by_assertion(self, assertion_ids):
        return {aid: self._read_typed(aid, "assertion")["claim"] for aid in assertion_ids}

    def merge(self, target: str, actor: str = "agent", timestamp: str = None):
        timestamp = timestamp or now_utc()
        index = load_index(self.cogit_dir)
        if not index_is_empty(index):
            raise UserError("merge: index is not empty; commit or clear it first")

        branch, ours = self.head_info()
        if ours is None:
            raise UserError("merge: HEAD has no commits yet")
        theirs = self.resolve(target)
        if theirs == ours or self.is_ancestor(theirs, ours):
            return {"result": "already-up-to-date", "thought": ours}
        if self.is_ancestor(ours, theirs):
            reason = f"fast-forward to {target}"
            if branch is not None:
                self.refs.update_ref(branch, theirs, ours, actor, "merge", reason, timestamp)
                self.refs.append_reflog("HEAD", ours, theirs, actor, "merge", reason, timestamp)
            else:
                self.refs.write_head(theirs, ours, actor, "merge", reason, timestamp, expected_raw=ours)
            save_index(self.cogit_dir, dict(EMPTY_INDEX))
            return {"result": "fast-forward", "thought": theirs}

        base = self.merge_base(ours, theirs)
        base_set = self._mindset_assertions(base)
        ours_set = self._mindset_assertions(ours)
        theirs_set = self._mindset_assertions(theirs)

        added_ours = ours_set - base_set
        removed_ours = base_set - ours_set
        added_theirs = theirs_set - base_set
        removed_theirs = base_set - theirs_set

        # Conflict detection groups by NEGATION GROUP (a claim plus everything
        # in its `negates` chain), so "ours strengthens X, theirs activates
        # not-X" collides instead of silently unioning (invariants 24-25).
        claims = self._claims_by_assertion(base_set | ours_set | theirs_set)
        groups = {aid: self._negation_group(claim_oid) for aid, claim_oid in claims.items()}

        def by_group(assertion_ids):
            grouped = {}
            for aid in assertion_ids:
                grouped.setdefault(groups[aid], set()).add(aid)
            return grouped

        added_ours_by_group = by_group(added_ours)
        added_theirs_by_group = by_group(added_theirs)
        removed_ours_by_group = by_group(removed_ours)
        removed_theirs_by_group = by_group(removed_theirs)

        conflicts = []
        conflicted_groups = set()
        for group_oid in sorted(set(added_ours_by_group) | set(added_theirs_by_group)):
            ours_added = added_ours_by_group.get(group_oid, set())
            theirs_added = added_theirs_by_group.get(group_oid, set())
            # add/add with different assertions in one proposition family
            add_add = ours_added and theirs_added and ours_added != theirs_added
            # change/delete: one side added where the other side removed
            change_delete = (ours_added and group_oid in removed_theirs_by_group) or (
                theirs_added and group_oid in removed_ours_by_group
            )
            # negation split: both sides added, one of them on a negating claim
            negation_split = (
                ours_added
                and theirs_added
                and any(claims[aid] != group_oid for aid in ours_added | theirs_added)
            )
            if add_add or change_delete or negation_split:
                conflicted_groups.add(group_oid)
                conflicts.append(
                    {
                        "claim": group_oid,
                        "ours": sorted(ours_added),
                        "theirs": sorted(theirs_added),
                        "base": sorted(aid for aid in base_set if groups.get(aid) == group_oid),
                    }
                )

        def unconflicted(assertion_ids):
            return {aid for aid in assertion_ids if groups[aid] not in conflicted_groups}

        result = (
            (base_set - removed_ours - removed_theirs)
            | unconflicted(added_ours)
            | unconflicted(added_theirs)
        )
        # keep whole conflicted families out of the auto-merged result
        result = {aid for aid in result if groups[aid] not in conflicted_groups}

        ours_mindset = self._read_typed(ours, "thought")["mindset"]
        index = dict(EMPTY_INDEX)
        index["base_mindset"] = ours_mindset
        index["staged_facts"] = sorted(result - ours_set)
        # Removals in conflicted families wait for resolution; auto-apply the rest.
        # A removal whose claim is negated by an incoming staged assertion is a
        # refutation and must say so (invariant 25).
        staged_negated = set()
        for aid in index["staged_facts"]:
            negated = self._read_typed(claims[aid], "claim").get("negates")
            if negated is not None:
                staged_negated.add(negated)
        index["removed_facts"] = [
            {"id": aid, "reason": "refuted" if claims[aid] in staged_negated else "merge"}
            for aid in sorted(ours_set - result)
            if groups.get(aid) not in conflicted_groups
        ]
        index["conflicts"] = conflicts
        index["merge"] = {"ours": ours, "theirs": theirs, "base": base}
        save_index(self.cogit_dir, index)
        return {
            "result": "conflicts" if conflicts else "staged",
            "conflicts": conflicts,
            "staged": index["staged_facts"],
            "removed": [entry["id"] for entry in index["removed_facts"]],
            "base": base,
        }

    def resolve_conflict(self, claim_oid: str, keep: str = None, drop: bool = False):
        if (keep is None) == (not drop):
            raise UserError("resolve: exactly one of --keep <assertion-id> or --drop is required")
        index = load_index(self.cogit_dir)
        entry = next((c for c in index["conflicts"] if c["claim"] == claim_oid), None)
        if entry is None:
            raise UserError(f"resolve: no recorded conflict for claim {claim_oid}")
        candidates = set(entry["ours"]) | set(entry["theirs"]) | set(entry["base"])
        kept = set()
        if keep is not None:
            if keep not in candidates:
                raise UserError(f"resolve: {keep} is not a candidate for this conflict")
            kept = {keep}
        # Resolution defines the FULL assertion set for the conflicted claim:
        # everything else about it that is currently active or staged goes away.
        base_set = self._base_assertions(index)
        active = base_set | set(index["staged_facts"])
        for aid in sorted(kept - active):
            index["staged_facts"].append(aid)
        index["staged_facts"] = sorted(set(index["staged_facts"]) - (candidates - kept))
        # Choosing a negation over the original IS a refutation (invariant 25).
        kept_negates = set()
        for aid in kept:
            kept_claim = self._read_typed(aid, "assertion")["claim"]
            negated = self._read_typed(kept_claim, "claim").get("negates")
            if negated is not None:
                kept_negates.add(negated)
        for aid in sorted((candidates & base_set) - kept):
            if all(removed["id"] != aid for removed in index["removed_facts"]):
                removed_claim = self._read_typed(aid, "assertion")["claim"]
                reason = "refuted" if removed_claim in kept_negates else "merge-conflict-resolution"
                index["removed_facts"].append({"id": aid, "reason": reason})
        index["removed_facts"].sort(key=lambda removed: removed["id"])
        index["conflicts"] = [c for c in index["conflicts"] if c["claim"] != claim_oid]
        save_index(self.cogit_dir, index)
        return len(index["conflicts"])

    # -- blame ---------------------------------------------------------------------

    def blame_fact(self, assertion_oid: str, start: str = None):
        if not is_oid(assertion_oid):
            raise UserError(f"blame-fact: invalid assertion id '{assertion_oid}'")
        assertion = self._read_typed(assertion_oid, "assertion")
        start_oid = self.resolve(start or "HEAD")
        thoughts = self._ancestry(start_oid)
        mindsets = {
            oid: set(self._read_typed(t["mindset"], "mindset")["assertions"])
            for oid, t in thoughts.items()
        }
        for oid in self._topo_oldest_first(thoughts):
            if assertion_oid not in mindsets[oid]:
                continue
            parents = thoughts[oid]["parents"]
            if all(assertion_oid not in mindsets.get(p, set()) for p in parents):
                return {
                    "thought": oid,
                    "message": thoughts[oid]["message"],
                    "author": thoughts[oid]["author"],
                    "timestamp": thoughts[oid]["timestamp"],
                    "operation": thoughts[oid]["operation"],
                    "claim": assertion["claim"],
                    "source": assertion["source"],
                }
        raise UserError(f"blame-fact: {assertion_oid} was never introduced in the selected ancestry")

    # -- anchors --------------------------------------------------------------------

    def anchor(self, name: str, thought: str, author: str = "agent", timestamp: str = None) -> str:
        refname = f"refs/anchors/{name}"
        validate_ref_name(refname)
        if "/" in name:
            raise UserError("anchor: name must be a single ref segment")
        if self.refs.read_ref(refname) is not None:
            raise UserError(f"anchor: '{name}' already exists (anchors are fixed in MVP)")
        timestamp = timestamp or now_utc()
        target = self.resolve(thought)
        self._read_typed(target, "thought")
        anchor_oid = self.store.write(
            {"type": "anchor", "name": name, "target": target, "created_at": timestamp, "author": author}
        )
        self.refs.update_ref(refname, anchor_oid, None, author, "anchor", f"{name} -> {target}", timestamp)
        return anchor_oid

    def list_anchors(self):
        anchors = []
        for refname, target in self.refs.list_refs("refs/anchors"):
            anchor = self._read_typed(target, "anchor")
            anchors.append(
                {"name": refname[len("refs/anchors/") :], "anchor": target, "target": anchor["target"]}
            )
        return anchors

    # -- facts / show (COG-028) --------------------------------------------------------

    def facts(self, ref: str = None):
        """Active facts of a thought, decoded enough to act on (pick IDs, judge beliefs)."""
        thought_oid = self.resolve(ref or "HEAD")
        rows = []
        for aid in sorted(self._mindset_assertions(thought_oid)):
            assertion = self._read_typed(aid, "assertion")
            claim = self._read_typed(assertion["claim"], "claim")
            rows.append(
                {
                    "assertion": aid,
                    "claim": assertion["claim"],
                    "kind": claim["kind"],
                    "subject": claim["subject"],
                    "predicate": claim["predicate"],
                    "object": claim["object"],
                    "negates": claim.get("negates"),
                    "confidence_bps": assertion["confidence_bps"],
                    "source": assertion["source"]["type"],
                    "status": assertion["status"],
                }
            )
        return {"thought": thought_oid, "facts": rows}

    def show(self, ref: str = None):
        """Thought header plus its active facts (git-show analogue)."""
        thought_oid = self.resolve(ref or "HEAD")
        thought = self._read_typed(thought_oid, "thought")
        return {"id": thought_oid, **thought, "facts": self.facts(thought_oid)["facts"]}

    # -- status ---------------------------------------------------------------------

    def status(self):
        branch, thought = self.head_info()
        index = load_index(self.cogit_dir)
        return {
            "branch": branch[len("refs/heads/") :] if branch else None,
            "detached": branch is None,
            "thought": thought,
            "staged": index["staged_facts"],
            "removed": index["removed_facts"],
            "conflicts": index["conflicts"],
            "merge_in_progress": index["merge"] is not None,
        }
