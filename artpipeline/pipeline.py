"""The pipeline: enforced per-asset state machine, leases, style lock, review gates, history.

Every public method is one transaction and returns a JSON-able dict. Refusals raise
PipelineError with a stable code and a hint naming the next valid step."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from pydantic import ValidationError

from artpipeline import __version__
from artpipeline import errors as E
from artpipeline.checks import CheckContext, Checker, imaging_checker
from artpipeline.imaging.render import RenderError, load_rgba
from artpipeline.imaging.sheet import SheetItem, build_sheets, render_grid_pages, render_page
from artpipeline.errors import PipelineError
from artpipeline.intake import load_brief
from artpipeline.schema import AssetClass, Provenance, Settings, Style
from artpipeline.store import Store, dumps, loads

# Asset statuses
PENDING = "pending"
IN_PROGRESS = "in_progress"
AWAITING_REVIEW = "awaiting_review"
APPROVED = "approved"
FLAGGED = "flagged"
WAIVED = "waived"
PLACED = "placed"
STATUSES = (PENDING, IN_PROGRESS, AWAITING_REVIEW, APPROVED, FLAGGED, WAIVED, PLACED)

SOURCE_EXTS = {".png", ".webp", ".jpg", ".jpeg", ".svg"}
MANIFEST_NAME = "art-manifest.json"
USER = "user"
DECIDERS = ("user", "agent")

_STATE_HINTS = {
    PENDING: "Claim it first with claim(asset_ids=[...]).",
    AWAITING_REVIEW: "Review it on a contact sheet and decide(approve|reject) first.",
    APPROVED: "It is already approved.",
    FLAGGED: "It is flagged for the user; only unflag (by the user) can reopen it.",
    WAIVED: "The user waived it.",
    PLACED: "It is already placed in the project.",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Pipeline:
    def __init__(
        self,
        store: Store,
        *,
        checker: Checker = imaging_checker,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.store = store
        self.checker = checker
        self.clock = clock

    @property
    def root(self) -> Path:
        return self.store.root

    # ------------------------------------------------------------------ init / refresh

    @classmethod
    def init(
        cls,
        brief_path: Path,
        root: Path | None = None,
        *,
        actor: str = "agent",
        **kwargs: Any,
    ) -> tuple["Pipeline", dict[str, Any]]:
        brief_path = Path(brief_path).resolve()
        manifest = load_brief(brief_path)
        store = Store.create(Path(root) if root else brief_path.parent)
        p = cls(store, **kwargs)
        now = p._now()
        added, changed, unchanged, removed = [], [], [], []
        with store.tx() as c:
            meta = _meta(c)
            if "project" in meta and meta["project"] != manifest.project:
                raise PipelineError(
                    E.PROJECT_MISMATCH,
                    f"{store.root} already holds project '{meta['project']}', not '{manifest.project}'.",
                    hint="Use a different --root for a different project.",
                )
            _set_meta(c, {
                "project": manifest.project,
                "direction": manifest.direction,
                "brief": _rel(brief_path, store.root),
                "settings": dumps(manifest.settings.model_dump()),
                "style": dumps(manifest.style.model_dump()),
            })
            rows = {r["id"]: r for r in c.execute("SELECT * FROM assets")}
            for i, a in enumerate(manifest.assets):
                spec = dumps(a.model_dump(by_alias=True, mode="json"))
                klass = dumps(manifest.resolve_class(a).model_dump(mode="json"))
                r = rows.get(a.id)
                if r is None:
                    c.execute(
                        "INSERT INTO assets(id, ord, spec, cls, status, updated_at) VALUES (?,?,?,?,?,?)",
                        (a.id, i, spec, klass, PENDING, now),
                    )
                    added.append(a.id)
                elif r["spec"] != spec or r["cls"] != klass:
                    c.execute(
                        "UPDATE assets SET ord=?, spec=?, cls=?, in_brief=1, updated_at=? WHERE id=?",
                        (i, spec, klass, now, a.id),
                    )
                    changed.append({"id": a.id, "status": r["status"]})
                else:
                    c.execute("UPDATE assets SET ord=?, in_brief=1 WHERE id=?", (i, a.id))
                    unchanged.append(a.id)
            ids = {a.id for a in manifest.assets}
            for aid in rows:
                if aid not in ids:
                    c.execute("UPDATE assets SET in_brief=0, updated_at=? WHERE id=?", (now, aid))
                    removed.append(aid)
            _event(c, now, actor, "init", None, brief=_rel(brief_path, store.root),
                   added=added, changed=[x["id"] for x in changed], removed=removed)
            p._write_manifest(c)

        warnings = []
        if not any(a.hero for a in manifest.assets):
            warnings.append(
                f"No hero assets in the brief. Claims stop after {manifest.settings.gate_threshold} "
                "assets until the user locks the style (lock_style)."
            )
        for ch in changed:
            if ch["status"] in (APPROVED, PLACED):
                warnings.append(f"'{ch['id']}' changed in the brief after it was {ch['status']}; "
                                "consider flagging it for re-review.")
        if removed:
            warnings.append(f"{len(removed)} asset(s) are no longer in the brief and are excluded: {removed}")
        report = {
            "root": str(store.root),
            "project": manifest.project,
            "direction": manifest.direction,
            "assets": len(manifest.assets),
            "heroes": [a.id for a in manifest.assets if a.hero],
            "added": added,
            "changed": changed,
            "unchanged": len(unchanged),
            "removed": removed,
            "warnings": warnings,
            "next": "claim(n, agent) to start; heroes come first until the style is locked.",
        }
        return p, report

    # ------------------------------------------------------------------ claims

    def claim(
        self,
        agent: str,
        n: int = 1,
        *,
        group: str | None = None,
        asset_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        if n < 1:
            raise PipelineError(E.INVALID_ARGUMENT, "n must be at least 1.")
        now_dt = self.clock()
        now = _iso(now_dt)
        wanted = list(asset_ids) if asset_ids else None
        with self.store.tx() as c:
            settings = _settings(c)
            gate = _open_gate(c)
            if gate:
                raise PipelineError(
                    E.GATE_DUE,
                    f"Batch review gate {gate['id']} is due: {len(loads(gate['asset_ids']))} approvals "
                    "since the last user review.",
                    hint=f"Build review_sheet(gate={gate['id']}), show it to the user, then pass_gate "
                    f"({gate['id']}, by='user') once they sign off.",
                    gate_id=gate["id"],
                    asset_ids=loads(gate["asset_ids"]),
                )
            rows = list(c.execute("SELECT * FROM assets WHERE in_brief=1 ORDER BY ord"))
            if wanted:
                by_id = {r["id"]: r for r in rows}
                for aid in wanted:
                    if aid not in by_id:
                        _asset(c, aid)  # raises ASSET_NOT_FOUND
            candidates = [r for r in rows if _claimable(r, agent, now, renew=bool(wanted))]
            if wanted:
                not_ok = [aid for aid in wanted if aid not in {r["id"] for r in candidates}]
                if not_ok:
                    states = {r["id"]: _lease_view(r, now) for r in rows if r["id"] in not_ok}
                    raise PipelineError(
                        E.INVALID_STATE, f"Not claimable: {not_ok}",
                        hint="Only pending assets, expired leases, or your own leases can be claimed.",
                        states=states,
                    )
                candidates = [r for r in candidates if r["id"] in wanted]
            if group:
                candidates = [r for r in candidates if loads(r["spec"]).get("group") == group]

            lock = _current_lock(c)
            heroes = [r for r in rows if loads(r["spec"]).get("hero")]
            note = None
            if lock is None:
                if heroes:
                    allowed = [r for r in candidates if loads(r["spec"]).get("hero")]
                    if len(allowed) < len(candidates):
                        note = "Only hero assets are claimable until the user locks the style."
                else:
                    tried = {x[0] for x in c.execute("SELECT DISTINCT asset_id FROM attempts")}
                    started = sum(1 for r in rows if r["status"] != PENDING or r["id"] in tried)
                    room = settings.gate_threshold - started
                    allowed = []
                    for r in candidates:
                        if r["status"] != PENDING or r["id"] in tried:
                            allowed.append(r)
                        elif room > 0:
                            allowed.append(r)
                            room -= 1
                    if len(allowed) < len(candidates):
                        note = (f"No heroes in the brief: only {settings.gate_threshold} assets can be "
                                "started before the user locks the style.")
            else:
                allowed = candidates

            take = allowed[:n]
            if not take:
                if candidates and lock is None:
                    raise PipelineError(
                        E.STYLE_NOT_LOCKED,
                        "The remaining assets wait for a style lock.",
                        hint="Finish the hero assets, show the user a contact sheet of them, and call "
                        "lock_style(by='user') after they approve.",
                        heroes={r["id"]: r["status"] for r in heroes},
                    )
                raise PipelineError(
                    E.NOTHING_CLAIMABLE, "No assets are claimable right now.",
                    hint=_nothing_hint(rows, now),
                    counts=_counts(rows),
                )

            expires = _iso(now_dt + timedelta(minutes=settings.lease_minutes))
            packets = []
            for r in take:
                c.execute(
                    "UPDATE assets SET status=?, lease_owner=?, lease_expires=?, updated_at=? WHERE id=?",
                    (IN_PROGRESS, agent, expires, now, r["id"]),
                )
                _event(c, now, agent, "claim", r["id"], lease_expires=expires)
                packets.append(self._packet(c, _asset(c, r["id"]), settings, lock))
        out: dict[str, Any] = {"agent": agent, "lease_expires": expires, "claimed": packets}
        if note:
            out["note"] = note
        return out

    def release(self, asset_id: str, agent: str) -> dict[str, Any]:
        now = self._now()
        with self.store.tx() as c:
            r = _asset(c, asset_id)
            if r["status"] != IN_PROGRESS:
                raise PipelineError(E.INVALID_STATE, f"'{asset_id}' is {r['status']}, not in progress.")
            if r["lease_owner"] != agent and not _expired(r, now):
                raise _leased(r)
            c.execute(
                "UPDATE assets SET status=?, lease_owner=NULL, lease_expires=NULL, updated_at=? WHERE id=?",
                (PENDING, now, asset_id),
            )
            _event(c, now, agent, "release", asset_id)
        return {"asset_id": asset_id, "status": PENDING}

    # ------------------------------------------------------------------ attempts

    def register_attempt(
        self,
        asset_id: str,
        file: Path | str,
        agent: str,
        provenance: dict[str, Any],
        change_from_previous: str | None = None,
    ) -> dict[str, Any]:
        try:
            prov = Provenance.model_validate(provenance)
        except ValidationError as e:
            raise PipelineError(
                E.INVALID_ARGUMENT, "Invalid provenance.",
                hint="route ∈ code_native|agent_app|image_gen|human and tool are required.",
                problems=[{"at": ".".join(map(str, x["loc"])), "problem": x["msg"]} for x in e.errors()],
            ) from None
        src = Path(file).expanduser().resolve()
        now_dt = self.clock()
        now = _iso(now_dt)

        # Phase 1: validate, reserve the attempt number, copy the source in.
        with self.store.tx() as c:
            settings = _settings(c)
            r = _asset(c, asset_id)
            if r["status"] != IN_PROGRESS:
                raise PipelineError(
                    E.INVALID_STATE, f"'{asset_id}' is {r['status']}; attempts need it in progress.",
                    hint=_STATE_HINTS.get(r["status"]),
                )
            if r["lease_owner"] != agent and not _expired(r, now):
                raise _leased(r)
            used = _attempt_count(c, asset_id)
            budget = settings.max_attempts + r["extra_attempts"]
            if used >= budget:
                raise PipelineError(E.RETRY_BUDGET_SPENT, f"'{asset_id}' has used all {budget} attempts.")
            if used and not (change_from_previous or "").strip():
                raise PipelineError(
                    E.NO_CAUSE_CHANGE,
                    f"Attempt {used + 1} of '{asset_id}' must say what changed since attempt {used}.",
                    hint="Change the cause (subject line, reference, seed, geometry), not a blind reroll, "
                    "and describe it in change_from_previous.",
                )
            klass = AssetClass.model_validate(loads(r["cls"]))
            if not src.is_file():
                raise PipelineError(E.SOURCE_NOT_FOUND, f"Source file not found: {src}")
            ext = src.suffix.lower()
            if ext not in SOURCE_EXTS:
                raise PipelineError(E.WRONG_FORMAT, f"Unsupported source type '{ext}'.",
                                    hint=f"Use one of {sorted(SOURCE_EXTS)}.")
            if klass.is_vector and ext != ".svg":
                raise PipelineError(E.WRONG_FORMAT, f"'{asset_id}' is a vector class; register an .svg.")
            n = used + 1
            att_dir = self.store.state_dir / "attempts" / asset_id / str(n)
            att_dir.mkdir(parents=True, exist_ok=True)
            stored = att_dir / f"source{'.jpg' if ext == '.jpeg' else ext}"
            shutil.copy2(src, stored)
            lock = _current_lock(c)
            c.execute(
                "INSERT INTO attempts(asset_id, n, created_at, agent, provenance, change_from_previous,"
                " source_path, style_lock_version) VALUES (?,?,?,?,?,?,?,?)",
                (asset_id, n, now, agent, dumps(prov.model_dump(mode="json")),
                 change_from_previous, _rel(stored, self.root), lock["version"] if lock else None),
            )
            c.execute(
                "UPDATE assets SET lease_owner=?, lease_expires=?, updated_at=? WHERE id=?",
                (agent, _iso(now_dt + timedelta(minutes=settings.lease_minutes)), now, asset_id),
            )
            style = _style(c)
            ctx = CheckContext(
                palette=loads(lock["palette"]) if lock else style.palette,
                backgrounds=klass.review_backgrounds or style.backgrounds,
                out_dir=att_dir,
                name=Path(loads(r["spec"])["destination"]).stem,
            )

        # Phase 2: checks run outside the write lock (imaging can be slow).
        result = self.checker(stored, klass, ctx)

        # Phase 3: record the outcome and move the state machine.
        now = self._now()
        with self.store.tx() as c:
            fields = {
                "checks": dumps(result.to_dict()),
                "passed": int(result.passed),
                "processed_path": _rel(result.processed_path, self.root) if result.processed_path else None,
                "renditions": dumps({k: _rel(v, self.root) for k, v in result.renditions.items()})
                if result.renditions else None,
            }
            if result.passed:
                status = AWAITING_REVIEW
            else:
                fields.update(decision="failed_checks", decision_by="checker", decided_at=now,
                              reason="; ".join(result.fail))
                status = FLAGGED if n >= budget else IN_PROGRESS
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE attempts SET {sets} WHERE asset_id=? AND n=?",
                      (*fields.values(), asset_id, n))
            if status == IN_PROGRESS:
                c.execute("UPDATE assets SET updated_at=? WHERE id=?", (now, asset_id))
            else:
                c.execute(
                    "UPDATE assets SET status=?, lease_owner=NULL, lease_expires=NULL, updated_at=? WHERE id=?",
                    (status, now, asset_id),
                )
            _event(c, now, agent, "attempt", asset_id, n=n, passed=result.passed, fail=result.fail,
                   route=prov.route, tool=prov.tool)
            if status == FLAGGED:
                _event(c, now, "checker", "flag", asset_id, reason="retry budget spent on failed checks")
            self._write_manifest(c)

        if status == AWAITING_REVIEW:
            nxt = "Put it on a review_sheet, look at it at display size, then decide(approve|reject)."
        elif status == FLAGGED:
            nxt = "Retry budget spent: the asset is flagged for the user. Move on to another asset."
        else:
            nxt = f"Fix the cause of the failures and register attempt {n + 1} with change_from_previous."
        return {
            "asset_id": asset_id,
            "attempt": n,
            "checks": result.to_dict(),
            "status": status,
            "attempts_left": max(0, budget - n),
            "stored": _rel(stored, self.root),
            "next": nxt,
        }

    # ------------------------------------------------------------------ review

    def review_sheet(
        self,
        asset_ids: Iterable[str] | None = None,
        *,
        pending_review: bool = False,
        gate_id: int | None = None,
        actor: str = "agent",
    ) -> dict[str, Any]:
        """Render a contact sheet of each asset's latest attempt at its display sizes on its review
        backgrounds (plus greyscale), and record that those attempts were reviewed."""
        with self.store.tx() as c:
            if gate_id is not None:
                ids = loads(_gate(c, gate_id)["asset_ids"])
            elif pending_review:
                ids = [r["id"] for r in c.execute(
                    "SELECT id FROM assets WHERE status=? AND in_brief=1 ORDER BY ord", (AWAITING_REVIEW,))]
            else:
                ids = list(asset_ids or [])
            if not ids:
                raise PipelineError(E.INVALID_ARGUMENT, "Nothing to put on a sheet.",
                                    hint="Pass asset_ids, pending_review=True, or a gate id.")
            style = _style(c)
            items = []
            for aid in ids:
                r = _asset(c, aid)
                att = _latest_attempt(c, aid)
                if att is None:
                    raise PipelineError(E.INVALID_STATE, f"'{aid}' has no attempts to review.")
                klass = AssetClass.model_validate(loads(r["cls"]))
                checks = loads(att["checks"]) or {}
                mark = "pass" if checks.get("pass") else "FAIL"
                if checks.get("warn"):
                    mark += f", {len(checks['warn'])} warn"
                items.append((aid, att, klass, f"attempt {att['n']} · {mark} · {r['status']}",
                              klass.review_backgrounds or style.backgrounds))
        sheet_items = []
        biggest = lambda k: max(k.display_sizes or [256])  # noqa: E731
        for aid, att, klass, sub, bgs in items:
            src = self.root / (att["processed_path"] or att["source_path"])
            try:
                w, h = klass.master
                scale = max(1.0, 2 * biggest(klass) / max(w, h)) if klass.is_vector else 1.0
                img = load_rgba(src, (round(w * scale), round(h * scale)))
            except RenderError as e:
                raise PipelineError(E.INVALID_STATE, f"'{aid}' attempt {att['n']} can't be rendered: {e}")
            sheet_items.append(SheetItem(
                label=aid, image=img, sizes=klass.display_sizes, backgrounds=bgs, sublabel=sub,
                pixel_art=klass.pixel_art, icon_mask=klass.icon_mask,
            ))
        stamp = self.clock().strftime("%Y%m%d-%H%M%S-%f")
        title = f"Gate {gate_id} review" if gate_id is not None else f"Review · {len(ids)} asset(s)"
        sheets_dir = self.store.state_dir / "sheets"
        pages = build_sheets(sheet_items, sheets_dir, f"sheet-{stamp}", title)
        # One strip per asset as well: small enough to be seen inline without being downscaled.
        strip_dir = sheets_dir / f"sheet-{stamp}"
        strip_dir.mkdir(parents=True, exist_ok=True)
        strips = {}
        for it in sheet_items:
            sp = strip_dir / f"{it.label}.png"
            render_page([it]).save(sp)
            strips[it.label] = str(sp)
        # And a compact grid: many assets per image at their smallest display size (the hard test).
        grid = []
        for k, page in enumerate(render_grid_pages(sheet_items, title), 1):
            gp = strip_dir / f"grid-{k}.png"
            page.save(gp)
            grid.append(str(gp))
        rec = self.record_sheet(pages, ids, gate_id=gate_id, actor=actor)
        rec["pages"] = [str(p) for p in pages]
        rec["strips"] = strips
        rec["grid"] = grid
        rec["next"] = ("Look at every page at display size (and show the user at gates), then "
                       + (f"pass_gate({gate_id}, by='user')." if gate_id is not None else "decide each asset."))
        return rec

    def record_sheet(
        self,
        paths: Path | str | Iterable[Path | str],
        asset_ids: Iterable[str],
        *,
        gate_id: int | None = None,
        actor: str = "agent",
    ) -> dict[str, Any]:
        """Record that contact-sheet pages showing the latest attempt of each asset exist.
        review_sheet renders and calls this; it is public for sheets built elsewhere."""
        now = self._now()
        ids = list(asset_ids)
        paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
        with self.store.tx() as c:
            items = []
            for aid in ids:
                _asset(c, aid)
                att = _latest_attempt(c, aid)
                if att is None:
                    raise PipelineError(E.INVALID_STATE, f"'{aid}' has no attempts to review.")
                items.append([aid, att["n"]])
            cur = c.execute(
                "INSERT INTO sheets(created_at, paths, items) VALUES (?,?,?)",
                (now, dumps([_rel(Path(x), self.root) for x in paths]), dumps(items)),
            )
            sheet_id = cur.lastrowid
            for aid, n in items:
                c.execute("UPDATE attempts SET sheet_id=? WHERE asset_id=? AND n=?", (sheet_id, aid, n))
            if gate_id is not None:
                g = _gate(c, gate_id)
                missing = sorted(set(loads(g["asset_ids"])) - set(ids))
                if missing:
                    raise PipelineError(
                        E.INVALID_ARGUMENT, f"Sheet for gate {gate_id} must include all its assets.",
                        missing=missing,
                    )
                c.execute("UPDATE gates SET sheet_id=? WHERE id=?", (sheet_id, gate_id))
            _event(c, now, actor, "sheet", None, sheet_id=sheet_id, items=items, gate_id=gate_id)
        return {"sheet_id": sheet_id, "paths": [str(x) for x in paths], "items": items, "gate_id": gate_id}

    def decide(
        self,
        asset_id: str,
        decision: str,
        by: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if decision not in ("approve", "reject"):
            raise PipelineError(E.INVALID_ARGUMENT, "decision must be 'approve' or 'reject'.")
        _check_by(by)
        now = self._now()
        with self.store.tx() as c:
            settings = _settings(c)
            r = _asset(c, asset_id)
            if r["status"] != AWAITING_REVIEW:
                raise PipelineError(
                    E.INVALID_STATE, f"'{asset_id}' is {r['status']}, not awaiting review.",
                    hint=_STATE_HINTS.get(r["status"], "Register a passing attempt first."),
                )
            att = _latest_attempt(c, asset_id)
            if att["sheet_id"] is None:
                raise PipelineError(
                    E.NOT_REVIEWED,
                    f"Attempt {att['n']} of '{asset_id}' has not been on a contact sheet.",
                    hint="Build a review_sheet that includes it and look at it at display size first.",
                )
            gate_due = None
            if decision == "reject":
                if not (reason or "").strip():
                    raise PipelineError(E.REASON_REQUIRED, "Rejecting needs a specific reason.",
                                        hint="Say what failed; it is handed to the next attempt.")
                budget = settings.max_attempts + r["extra_attempts"]
                status = FLAGGED if att["n"] >= budget else PENDING
                c.execute(
                    "UPDATE attempts SET decision='rejected', decision_by=?, reason=?, decided_at=? "
                    "WHERE asset_id=? AND n=?", (by, reason, now, asset_id, att["n"]),
                )
            else:
                status = APPROVED
                lock = _current_lock(c)
                c.execute(
                    "UPDATE attempts SET decision='approved', decision_by=?, reason=?, decided_at=?, "
                    "style_lock_version=? WHERE asset_id=? AND n=?",
                    (by, reason, now, lock["version"] if lock else None, asset_id, att["n"]),
                )
            c.execute(
                "UPDATE assets SET status=?, lease_owner=NULL, lease_expires=NULL, updated_at=? WHERE id=?",
                (status, now, asset_id),
            )
            _event(c, now, by, decision, asset_id, n=att["n"], reason=reason)
            if status == FLAGGED:
                _event(c, now, "pipeline", "flag", asset_id, reason="retry budget spent on rejections")
            staged = None
            if status == APPROVED:
                staged = self._stage(c, r, _approved_attempt(c, asset_id), now)
                gate_due = _maybe_open_gate(c, now, settings)
            self._write_manifest(c)
        out: dict[str, Any] = {"asset_id": asset_id, "attempt": att["n"], "status": status}
        if staged:
            out.update(staged)
        if status == PENDING:
            out["next"] = "Back in the queue; the next claim gets this reason in its work packet."
        if status == FLAGGED:
            out["next"] = "Retry budget spent: flagged for the user."
        if gate_due:
            out["gate_due"] = gate_due
        return out

    def decide_batch(self, decisions: list[dict[str, Any]], by: str) -> dict[str, Any]:
        """Several decisions in one call. Each is its own transaction; a refusal is reported for that
        asset and the rest still go through."""
        results, gate_due = [], None
        for d in decisions:
            try:
                out = self.decide(d["asset_id"], d["decision"], by, d.get("reason"))
            except PipelineError as e:
                results.append({"asset_id": d.get("asset_id"), "error": e.code, "message": e.message,
                                "hint": e.hint})
                continue
            gate_due = out.pop("gate_due", None) or gate_due
            out.pop("next", None)
            results.append(out)
        res: dict[str, Any] = {"results": results, "counts": {}}
        for r in results:
            k = r.get("status") or "error"
            res["counts"][k] = res["counts"].get(k, 0) + 1
        if gate_due:
            res["gate_due"] = gate_due
        return res

    def preflight(self, asset_id: str, file: str | Path) -> dict[str, Any]:
        """Run an asset's own processing and checks on a draft without registering an attempt."""
        src = Path(file).expanduser()
        if not src.is_file():
            raise PipelineError(E.SOURCE_NOT_FOUND, f"No file at {src}.")
        with self.store.tx() as c:
            r = _asset(c, asset_id)
            klass = AssetClass.model_validate(loads(r["cls"]))
            lock = _current_lock(c)
            style = _style(c)
            out_dir = self.store.state_dir / "preflight" / asset_id
            ctx = CheckContext(
                palette=loads(lock["palette"]) if lock else style.palette,
                backgrounds=klass.review_backgrounds or style.backgrounds,
                out_dir=out_dir,
                name=Path(loads(r["spec"])["destination"]).stem,
            )
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        result = self.checker(src, klass, ctx)
        d = result.to_dict()
        return {"asset_id": asset_id, "file": str(src), "pass": d.get("pass"), "fail": d.get("fail", []),
                "warn": d.get("warn", []), "metrics": d.get("metrics", {})}

    # ------------------------------------------------------------------ style lock & gates

    def lock_style(
        self,
        by: str,
        style_block: str | None = None,
        *,
        palette: list[str] | None = None,
        hero_ids: list[str] | None = None,
        references: list[str] | None = None,
        notes: str | None = None,
        provisional: bool = False,
    ) -> dict[str, Any]:
        if provisional and by == USER:
            raise PipelineError(E.INVALID_ARGUMENT, "A lock by the user is never provisional.",
                                hint="Call lock_style(by='user') without provisional.")
        if by != USER and not provisional:
            raise PipelineError(
                E.USER_SIGNOFF_REQUIRED, "Only the user can lock the style.",
                hint="Show the user the hero contact sheet; call lock_style(by='user') after they say yes. "
                "If the user is away and asked you to carry on, lock_style(by='agent', provisional=True) "
                "lets work continue: everything approved under it goes back to review when the user locks.",
            )
        _check_by(by)
        now = self._now()
        with self.store.tx() as c:
            prev = _current_lock(c)
            if provisional and prev is not None and not prev["provisional"]:
                raise PipelineError(
                    E.INVALID_STATE, f"The user already locked the style (v{prev['version']}).",
                    hint="Only the user can change a user lock: lock_style(by='user').",
                )
            style = _style(c)
            block = (style_block or style.block or "").strip()
            if not block:
                raise PipelineError(E.INVALID_ARGUMENT, "A style block is required (none in the brief).")
            pal = palette if palette is not None else style.palette
            try:
                Style(palette=pal)
            except ValidationError as e:
                raise PipelineError(E.INVALID_ARGUMENT, f"Invalid palette: {e.errors()[0]['msg']}") from None
            rows = {r["id"]: r for r in c.execute("SELECT * FROM assets WHERE in_brief=1")}
            if hero_ids is None:
                hero_ids = [aid for aid, r in rows.items() if loads(r["spec"]).get("hero")]
            for h in hero_ids:
                if h not in rows:
                    _asset(c, h)
            not_ready = {h: rows[h]["status"] for h in hero_ids if rows[h]["status"] not in (APPROVED, PLACED)}
            if not_ready:
                raise PipelineError(
                    E.HEROES_NOT_APPROVED, "Every hero must be approved before the style is locked.",
                    heroes=not_ready,
                )
            refs = list(style.references) + list(references or [])
            for h in hero_ids:
                att = _approved_attempt(c, h)
                if att is not None:
                    refs.append(att["processed_path"] or att["source_path"])
            version = (prev["version"] + 1) if prev else 1
            c.execute(
                "INSERT INTO style_locks(version, created_at, by, style_block, palette, hero_ids, refs, notes,"
                " provisional) VALUES (?,?,?,?,?,?,?,?,?)",
                (version, now, by, block, dumps(pal), dumps(hero_ids), dumps(refs), notes, int(provisional)),
            )
            lock_dir = self.store.state_dir / "style-lock"
            lock_dir.mkdir(exist_ok=True)
            (lock_dir / f"v{version}.json").write_text(json.dumps({
                "version": version, "created_at": now, "by": by, "provisional": provisional,
                "style_block": block,
                "palette": pal, "heroes": hero_ids, "references": refs, "notes": notes,
            }, indent=2), encoding="utf-8")
            (lock_dir / "palette.txt").write_text("\n".join(pal) + "\n", encoding="utf-8")

            rereview = []
            if prev:
                for aid, r in rows.items():
                    if aid in hero_ids or r["status"] != APPROVED:
                        continue
                    att = _approved_attempt(c, aid)
                    if att is not None and (att["style_lock_version"] or 0) < version:
                        c.execute(
                            "UPDATE attempts SET decision=NULL, decision_by=NULL, decided_at=NULL, "
                            "sheet_id=NULL WHERE asset_id=? AND n=?", (aid, att["n"]),
                        )
                        c.execute("UPDATE assets SET status=?, updated_at=? WHERE id=?",
                                  (AWAITING_REVIEW, now, aid))
                        rereview.append(aid)
            _event(c, now, by, "lock_style", None, version=version, heroes=hero_ids, rereview=rereview,
                   provisional=provisional)
            self._write_manifest(c)
        out: dict[str, Any] = {"version": version, "provisional": provisional, "heroes": hero_ids,
                               "palette": pal, "references": refs}
        if rereview:
            out["rereview"] = rereview
        if provisional:
            out["next"] = ("Provisional lock: non-hero work is open and batch gates are deferred. Nothing "
                           "approved under it is final: when the user locks the style, every non-hero asset "
                           "approved under this lock returns to review. Say so in the hand-back.")
        elif rereview:
            out["next"] = "Assets approved under the previous lock are back in review."
        else:
            out["next"] = "Non-hero assets are now claimable; every work packet carries this lock."
        return out

    def pass_gate(self, gate_id: int, by: str, notes: str | None = None) -> dict[str, Any]:
        if by != USER:
            raise PipelineError(E.USER_SIGNOFF_REQUIRED, "Only the user can pass a review gate.")
        now = self._now()
        with self.store.tx() as c:
            g = _gate(c, gate_id)
            if g["passed_at"]:
                raise PipelineError(E.INVALID_STATE, f"Gate {gate_id} was already passed.")
            if g["sheet_id"] is None:
                raise PipelineError(
                    E.GATE_NOT_REVIEWED, f"Gate {gate_id} has no contact sheet yet.",
                    hint=f"Build review_sheet(gate={gate_id}) and show it to the user first.",
                )
            c.execute("UPDATE gates SET passed_by=?, passed_at=?, notes=? WHERE id=?",
                      (by, now, notes, gate_id))
            _event(c, now, by, "pass_gate", None, gate_id=gate_id, notes=notes)
        return {"gate_id": gate_id, "passed": True, "next": "Claims are open again."}

    # ------------------------------------------------------------------ flags

    def flag(self, asset_id: str, reason: str, by: str) -> dict[str, Any]:
        _check_by(by)
        if not reason.strip():
            raise PipelineError(E.REASON_REQUIRED, "Flagging needs a reason.")
        now = self._now()
        with self.store.tx() as c:
            r = _asset(c, asset_id)
            if r["status"] in (APPROVED, PLACED, WAIVED, FLAGGED):
                raise PipelineError(E.INVALID_STATE, f"'{asset_id}' is {r['status']}; it can't be flagged.")
            c.execute(
                "UPDATE assets SET status=?, lease_owner=NULL, lease_expires=NULL, updated_at=? WHERE id=?",
                (FLAGGED, now, asset_id),
            )
            _event(c, now, by, "flag", asset_id, reason=reason)
            self._write_manifest(c)
        return {"asset_id": asset_id, "status": FLAGGED}

    def unflag(
        self,
        asset_id: str,
        by: str,
        action: str = "retry",
        extra_attempts: int = 1,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if by != USER:
            raise PipelineError(E.USER_SIGNOFF_REQUIRED, "Only the user can unflag an asset.")
        if action not in ("retry", "waive"):
            raise PipelineError(E.INVALID_ARGUMENT, "action must be 'retry' or 'waive'.")
        if extra_attempts < 1:
            raise PipelineError(E.INVALID_ARGUMENT, "extra_attempts must be at least 1.")
        now = self._now()
        with self.store.tx() as c:
            settings = _settings(c)
            r = _asset(c, asset_id)
            if r["status"] != FLAGGED:
                raise PipelineError(E.INVALID_STATE, f"'{asset_id}' is {r['status']}, not flagged.")
            if action == "waive":
                c.execute("UPDATE assets SET status=?, updated_at=? WHERE id=?", (WAIVED, now, asset_id))
                status, left = WAIVED, 0
            else:
                used = _attempt_count(c, asset_id)
                extra = max(r["extra_attempts"], used + extra_attempts - settings.max_attempts)
                c.execute("UPDATE assets SET status=?, extra_attempts=?, updated_at=? WHERE id=?",
                          (PENDING, extra, now, asset_id))
                status, left = PENDING, settings.max_attempts + extra - used
            _event(c, now, by, "unflag", asset_id, action=action, notes=notes)
            self._write_manifest(c)
        return {"asset_id": asset_id, "status": status, "attempts_left": left}

    # ------------------------------------------------------------------ reads

    def status(self, asset_id: str | None = None) -> dict[str, Any]:
        now = self._now()
        with self.store.tx() as c:
            if asset_id:
                r = _asset(c, asset_id)
                settings = _settings(c)
                return {
                    "asset_id": asset_id,
                    "status": r["status"],
                    "in_brief": bool(r["in_brief"]),
                    "lease": _lease_view(r, now),
                    "spec": loads(r["spec"]),
                    "class": loads(r["cls"]),
                    "attempts_left": max(0, settings.max_attempts + r["extra_attempts"]
                                         - _attempt_count(c, asset_id)),
                    "attempts": [_attempt_view(a) for a in _attempts(c, asset_id)],
                }
            meta = _meta(c)
            rows = list(c.execute("SELECT * FROM assets WHERE in_brief=1 ORDER BY ord"))
            lock = _current_lock(c)
            gate = _open_gate(c)
            leases = [{"asset_id": r["id"], **_lease_view(r, now)} for r in rows if r["status"] == IN_PROGRESS]
            return {
                "root": str(self.root),
                "project": meta.get("project"),
                "direction": meta.get("direction"),
                "counts": _counts(rows),
                "style_lock": lock["version"] if lock else None,
                "style_lock_provisional": bool(lock and lock["provisional"]),
                "open_gate": {"gate_id": gate["id"], "asset_ids": loads(gate["asset_ids"]),
                              "has_sheet": gate["sheet_id"] is not None} if gate else None,
                "awaiting_review": [r["id"] for r in rows if r["status"] == AWAITING_REVIEW],
                "flagged": [r["id"] for r in rows if r["status"] == FLAGGED],
                "leases": leases,
            }

    def history(self, asset_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        with self.store.tx() as c:
            if asset_id:
                _asset(c, asset_id)
                q = c.execute("SELECT * FROM events WHERE asset_id=? ORDER BY id DESC LIMIT ?", (asset_id, limit))
            else:
                q = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
            events = [{"ts": e["ts"], "actor": e["actor"], "kind": e["kind"], "asset_id": e["asset_id"],
                       **loads(e["data"])} for e in q]
        return {"events": list(reversed(events))}

    def handback(self, top: int = 5) -> dict[str, Any]:
        """Summary for the user at the end of a run (or any time): what's done, what failed,
        what needs a human, and the assets most likely to need taste revisions."""
        with self.store.tx() as c:
            rows = list(c.execute("SELECT * FROM assets WHERE in_brief=1 ORDER BY ord"))
            lock = _current_lock(c)
            approved, flagged, unfinished, human = [], [], [], []
            for r in rows:
                spec = loads(r["spec"])
                atts = _attempts(c, r["id"])
                if r["status"] in (APPROVED, PLACED):
                    att = _approved_attempt(c, r["id"])
                    warns = (loads(att["checks"]) or {}).get("warn", []) if att else []
                    approved.append({"asset_id": r["id"], "attempts": len(atts), "warnings": warns})
                    if spec.get("needs_human_finish"):
                        human.append(r["id"])
                elif r["status"] == FLAGGED:
                    last = atts[-1] if atts else None
                    flagged.append({"asset_id": r["id"], "attempts": len(atts),
                                    "last_reason": (last["reason"] if last else None)})
                elif r["status"] != WAIVED:
                    unfinished.append({"asset_id": r["id"], "status": r["status"]})
            manifest = self._write_manifest(c)
        candidates = sorted(approved, key=lambda a: (-a["attempts"], -len(a["warnings"])))
        candidates = [a for a in candidates if a["attempts"] > 1 or a["warnings"]][:top]
        out: dict[str, Any] = {
            "counts": _counts(rows),
            "style_lock": lock["version"] if lock else None,
            "style_lock_provisional": bool(lock and lock["provisional"]),
            "manifest": str(manifest),
            "flagged": flagged,
            "unfinished": unfinished,
            "needs_human_finish": human,
            "revision_candidates": [
                {**a, "why": f"{a['attempts']} attempt(s)" + (f", {len(a['warnings'])} warning(s)"
                                                              if a["warnings"] else "")}
                for a in candidates
            ],
        }
        if lock is None:
            out["waiting_for_user"] = ("The style is not locked: show the user the hero sheet and ask them "
                                       "to approve it (lock_style(by='user')).")
        elif lock["provisional"]:
            out["waiting_for_user"] = (
                f"The style lock (v{lock['version']}) is provisional, set by the agent while the user was away. "
                f"{len(approved)} approved asset(s) are not final: show the user the hero sheet; when they lock "
                "the style, the non-hero assets return to review.")
        if approved:
            sheet = self.review_sheet([a["asset_id"] for a in approved], actor="handback")
            out["final_sheet"] = sheet["pages"]
        return out

    def export_manifest(self) -> dict[str, Any]:
        with self.store.tx() as c:
            path = self._write_manifest(c)
        return {"manifest": str(path)}

    # ------------------------------------------------------------------ internals

    def _now(self) -> str:
        return _iso(self.clock())

    def _packet(self, c, r, settings: Settings, lock) -> dict[str, Any]:
        spec = loads(r["spec"])
        klass = loads(r["cls"])
        style = _style(c)
        used = _attempt_count(c, r["id"])
        prev = []
        for a in _attempts(c, r["id"]):
            prov = loads(a["provenance"])
            checks = loads(a["checks"]) or {}
            prev.append({
                "n": a["n"], "route": prov.get("route"), "tool": prov.get("tool"),
                "model": prov.get("model"), "prompt": prov.get("prompt"),
                "decision": a["decision"], "reason": a["reason"],
                "check_failures": checks.get("fail", []),
                "change_from_previous": a["change_from_previous"],
            })
        return {
            "asset_id": r["id"],
            "class": spec["class"],
            "spec": {k: klass[k] for k in ("format", "master", "alpha", "renditions",
                                           "display_sizes", "pixel_art")},
            "subject": spec["subject"],
            "acceptance_criteria": spec["acceptance_criteria"],
            "destination": spec["destination"],
            "hero": spec.get("hero", False),
            "group": spec.get("group"),
            "needs_human_finish": spec.get("needs_human_finish", False),
            "references": spec.get("references", []),
            "style": {
                "lock_version": lock["version"] if lock else None,
                "provisional": bool(lock and lock["provisional"]),
                "block": lock["style_block"] if lock else style.block,
                "palette": loads(lock["palette"]) if lock else style.palette,
                "backgrounds": klass["review_backgrounds"] or style.backgrounds,
                "references": loads(lock["refs"]) if lock else style.references,
            },
            "attempts_used": used,
            "attempts_left": settings.max_attempts + r["extra_attempts"] - used,
            "previous_attempts": prev,
            "next": "Produce the asset with the right tool, then register_attempt(asset_id, file, "
                    "provenance" + (", change_from_previous)" if used else ")"),
        }

    def _stage(self, c, r, att, now: str) -> dict[str, Any] | None:
        """Copy an approved attempt's master and renditions to the asset's destination under the root.
        A file there that the pipeline did not put there is moved to superseded/ first, never overwritten."""
        if att is None:
            return None
        spec = loads(r["spec"])
        src = self.root / (att["processed_path"] or att["source_path"])
        dest = self.root / spec["destination"]
        if dest.suffix.lower() != src.suffix.lower():
            dest = dest.with_suffix(src.suffix)
        pairs = [(src, dest)]
        for rel in (loads(att["renditions"]) or {}).values():
            rsrc = self.root / rel
            pairs.append((rsrc, dest.parent / rsrc.name))
        written, superseded = [], []
        stamp = now.replace(":", "").replace("-", "").split(".")[0]
        for s_, d in pairs:
            if not s_.is_file():
                continue
            rel_d = _rel(d, self.root)
            d.parent.mkdir(parents=True, exist_ok=True)
            if d.exists():
                ours = c.execute("SELECT sha256 FROM staged WHERE path=?", (rel_d,)).fetchone()
                if ours is None or ours["sha256"] != _sha256(d):
                    keep = self.root / "superseded" / stamp / rel_d
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(d), keep)
                    superseded.append({"was": rel_d, "moved_to": _rel(keep, self.root)})
            shutil.copy2(s_, d)
            c.execute("INSERT OR REPLACE INTO staged(path, asset_id, n, sha256, staged_at) VALUES (?,?,?,?,?)",
                      (rel_d, r["id"], att["n"], _sha256(d), now))
            written.append(rel_d)
        _event(c, now, "pipeline", "stage", r["id"], n=att["n"], files=written, superseded=superseded)
        out: dict[str, Any] = {"staged": written}
        if superseded:
            out["superseded"] = superseded
        return out

    def _write_manifest(self, c) -> Path:
        meta = _meta(c)
        lock = _current_lock(c)
        rows = list(c.execute("SELECT * FROM assets WHERE in_brief=1 ORDER BY ord"))
        provisional = {x[0] for x in c.execute("SELECT version FROM style_locks WHERE provisional=1")}
        staged: dict[tuple[str, int], list[str]] = {}
        for x in c.execute("SELECT path, asset_id, n FROM staged ORDER BY path"):
            staged.setdefault((x["asset_id"], x["n"]), []).append(x["path"])
        assets = []
        for r in rows:
            spec = loads(r["spec"])
            att = _approved_attempt(c, r["id"])
            approved = None
            if att is not None:
                prov = loads(att["provenance"])
                checks = loads(att["checks"]) or {}
                files = staged.get((r["id"], att["n"]), [])
                main = next((f for f in files if Path(f).stem == Path(spec["destination"]).stem), None)
                approved = {
                    "attempt": att["n"],
                    "file": main or att["processed_path"] or att["source_path"],
                    "renditions": [f for f in files if f != main] or loads(att["renditions"]),
                    "attempt_file": att["processed_path"] or att["source_path"],
                    **{k: prov.get(k) for k in ("route", "tool", "model", "prompt", "seed", "references", "rights")},
                    "checks": {"pass": checks.get("pass"), "warn": checks.get("warn", [])},
                    "style_lock": att["style_lock_version"],
                    "provisional": att["style_lock_version"] in provisional,
                    "approved_by": att["decision_by"],
                    "approved_at": att["decided_at"],
                }
            assets.append({
                "id": r["id"],
                "class": spec["class"],
                "status": r["status"],
                "destination": spec["destination"],
                "hero": spec.get("hero", False),
                "needs_human_finish": spec.get("needs_human_finish", False),
                "attempts": _attempt_count(c, r["id"]),
                "approved": approved,
            })
        doc = {
            "generated_by": f"artpipeline {__version__}",
            "project": meta.get("project"),
            "direction": meta.get("direction"),
            "brief": meta.get("brief"),
            "style_lock": {"version": lock["version"], "by": lock["by"], "at": lock["created_at"],
                           "provisional": bool(lock["provisional"])} if lock else None,
            "counts": _counts(rows),
            "assets": assets,
        }
        path = self.root / MANIFEST_NAME
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path


# ---------------------------------------------------------------------- helpers


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _rel(p: Path, root: Path) -> str:
    p = Path(p).resolve()
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return str(p)


def _sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _meta(c) -> dict[str, str]:
    return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM meta")}


def _set_meta(c, values: dict[str, str]) -> None:
    for k, v in values.items():
        c.execute("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (k, v))


def _settings(c) -> Settings:
    return Settings.model_validate(loads(_meta(c).get("settings", "{}")))


def _style(c) -> Style:
    return Style.model_validate(loads(_meta(c).get("style", "{}")))


def _event(c, ts: str, actor: str, kind: str, asset_id: str | None, **data: Any) -> None:
    c.execute("INSERT INTO events(ts, actor, kind, asset_id, data) VALUES (?,?,?,?,?)",
              (ts, actor, kind, asset_id, dumps(data)))


def _asset(c, asset_id: str):
    r = c.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    if r is None:
        ids = [x["id"] for x in c.execute("SELECT id FROM assets WHERE in_brief=1 ORDER BY ord LIMIT 60")]
        raise PipelineError(E.ASSET_NOT_FOUND, f"No asset '{asset_id}'.", hint="Check the id with status().",
                            known=ids)
    return r


def _attempts(c, asset_id: str):
    return list(c.execute("SELECT * FROM attempts WHERE asset_id=? ORDER BY n", (asset_id,)))


def _attempt_count(c, asset_id: str) -> int:
    return c.execute("SELECT COUNT(*) FROM attempts WHERE asset_id=?", (asset_id,)).fetchone()[0]


def _latest_attempt(c, asset_id: str):
    return c.execute("SELECT * FROM attempts WHERE asset_id=? ORDER BY n DESC LIMIT 1", (asset_id,)).fetchone()


def _approved_attempt(c, asset_id: str):
    return c.execute("SELECT * FROM attempts WHERE asset_id=? AND decision='approved' ORDER BY n DESC LIMIT 1",
                     (asset_id,)).fetchone()


def _attempt_view(a) -> dict[str, Any]:
    return {
        "n": a["n"], "created_at": a["created_at"], "agent": a["agent"],
        "provenance": loads(a["provenance"]), "change_from_previous": a["change_from_previous"],
        "source": a["source_path"], "processed": a["processed_path"], "renditions": loads(a["renditions"]),
        "checks": loads(a["checks"]), "on_sheet": a["sheet_id"],
        "decision": a["decision"], "decision_by": a["decision_by"], "reason": a["reason"],
        "style_lock": a["style_lock_version"],
    }


def _current_lock(c):
    return c.execute("SELECT * FROM style_locks ORDER BY version DESC LIMIT 1").fetchone()


def _gate(c, gate_id: int):
    g = c.execute("SELECT * FROM gates WHERE id=?", (gate_id,)).fetchone()
    if g is None:
        raise PipelineError(E.GATE_NOT_FOUND, f"No gate {gate_id}.")
    return g


def _open_gate(c):
    return c.execute("SELECT * FROM gates WHERE kind='batch' AND passed_at IS NULL ORDER BY id LIMIT 1").fetchone()


def _maybe_open_gate(c, now: str, settings: Settings) -> dict[str, Any] | None:
    if _open_gate(c):
        return None
    lock = _current_lock(c)
    if lock is not None and lock["provisional"]:
        return None  # deferred: the user's real lock sends all of this work back to review anyway
    marks = [r[0] for r in c.execute(
        "SELECT passed_at FROM gates WHERE kind='batch' AND passed_at IS NOT NULL "
        "UNION ALL SELECT created_at FROM style_locks") if r[0]]
    since = max(marks) if marks else ""
    ids = [r["asset_id"] for r in c.execute(
        "SELECT DISTINCT asset_id FROM attempts WHERE decision='approved' AND decided_at > ? ORDER BY decided_at",
        (since,))]
    if len(ids) < settings.gate_threshold:
        return None
    cur = c.execute("INSERT INTO gates(kind, created_at, asset_ids) VALUES ('batch', ?, ?)", (now, dumps(ids)))
    _event(c, now, "pipeline", "gate_open", None, gate_id=cur.lastrowid, asset_ids=ids)
    return {
        "gate_id": cur.lastrowid,
        "asset_ids": ids,
        "next": f"Claims are paused. Build review_sheet(gate={cur.lastrowid}), show the user, "
                "then pass_gate(by='user').",
    }


def _expired(r, now: str) -> bool:
    return r["lease_expires"] is not None and r["lease_expires"] < now


def _claimable(r, agent: str, now: str, renew: bool) -> bool:
    """Pending assets and expired leases are claimable; an agent's own live lease only when it
    names the asset explicitly (renewal), so a plain claim never hands back work already held."""
    if r["status"] == PENDING:
        return True
    if r["status"] == IN_PROGRESS:
        return _expired(r, now) or (renew and r["lease_owner"] == agent)
    return False


def _leased(r) -> PipelineError:
    return PipelineError(
        E.LEASED_BY_OTHER, f"'{r['id']}' is leased by '{r['lease_owner']}' until {r['lease_expires']}.",
        hint="Work on your own claims; leases expire if their owner stops.",
    )


def _lease_view(r, now: str) -> dict[str, Any]:
    return {"status": r["status"], "owner": r["lease_owner"], "expires": r["lease_expires"],
            "stale": _expired(r, now)}


def _counts(rows) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for r in rows:
        out[r["status"]] += 1
    return {k: v for k, v in out.items() if v}


def _nothing_hint(rows, now: str) -> str:
    counts = _counts(rows)
    if counts.get(AWAITING_REVIEW):
        return "Assets are awaiting review: build a review_sheet and decide them."
    if counts.get(IN_PROGRESS):
        return "Everything left is leased by other agents; wait or work on your own claims."
    if counts.get(FLAGGED):
        return "Only flagged assets remain; they need the user (unflag)."
    return "Everything is done. Call handback / export_manifest."


def _check_by(by: str) -> None:
    if by not in DECIDERS:
        raise PipelineError(E.INVALID_ARGUMENT, "by must be 'user' or 'agent'.")
