"""Server-rendered HTML for the U7.3 Approval Workbench.

All operator input is HTML-escaped via :func:`html.escape`. There is no
JavaScript, no external CDN, no third-party script, and no automatic polling or
submission. Every mutating form is POST-only and carries the page-scoped CSRF
token as a hidden field rendered by the router.

Lifecycle presentation is truthful: pages show one of ``pending``,
``rejected``, ``approved-ungranted``, or ``granted`` derived strictly from
stored evidence tuples. The terms ``active``, ``currently authorized``,
``safe``, ``ready``, ``executable``, or ``valid now`` are never rendered unless
a persisted evaluation at an explicit evaluation time is being displayed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from html import escape

from orbitmind.api.authority_schemas import AUTHORITY_API_SCHEMA_VERSION
from orbitmind.authority.contracts import (
    ApprovalDecision,
    ApprovalDecisionOutcome,
    ApprovalRequest,
    AuthorityEvaluationDecision,
    AuthorityReasonCode,
    CapabilityGrant,
    RevocationRecord,
)
from orbitmind.core.page_csrf import AUTHORITY_WORKBENCH_CSRF_FORM_FIELD

PAGE_CSS = """
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --panel-soft: #eef4f8;
      --ink: #17202a;
      --muted: #536172;
      --line: #d8e0e8;
      --accent: #22577a;
      --accent-strong: #163c55;
      --good-bg: #e8f7ef;
      --good-ink: #17613a;
      --warn-bg: #fff5dc;
      --warn-ink: #765312;
      --info-bg: #e7f0f8;
      --info-ink: #22577a;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--ink); line-height: 1.55; }
    main { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 40px 0 56px; }
    .hero { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
            padding: 28px; margin-bottom: 20px; }
    .eyebrow { margin: 0 0 8px; color: var(--accent); font-size: 0.84rem; font-weight: 700;
               letter-spacing: 0.08em; text-transform: uppercase; }
    h1, h2, h3 { margin: 0; line-height: 1.2; }
    h1 { font-size: 2.0rem; }
    h2 { font-size: 1.15rem; margin-bottom: 14px; }
    h3 { font-size: 1rem; margin-bottom: 8px; }
    p { color: var(--muted); margin: 10px 0 0; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    .grid > * { min-width: 0; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
            padding: 20px; }
    .card.soft { background: var(--panel-soft); }
    .stack { display: grid; gap: 16px; }
    .button { appearance: none; border: 0; border-radius: 8px; background: var(--accent);
              color: white; cursor: pointer; font: inherit; font-weight: 700;
              padding: 12px 18px; }
    .button:hover { background: var(--accent-strong); }
    .button.secondary { background: var(--panel); border: 1px solid var(--accent);
                        color: var(--accent); }
    .button.danger { background: #8a2d24; }
    .button.danger:hover { background: #682018; }
    label { color: var(--muted); display: grid; font-weight: 700; gap: 6px; }
    input, textarea, select { border: 1px solid var(--line); border-radius: 8px;
                              color: var(--ink); font: inherit; padding: 10px 12px; width: 100%; }
    input:focus-visible, textarea:focus-visible, select:focus-visible,
    button:focus-visible, a:focus-visible {
      outline: 3px solid #80b7d4; outline-offset: 2px;
    }
    textarea { min-height: 70px; resize: vertical; }
    fieldset { border: 1px solid var(--line); border-radius: 8px; margin: 0; min-width: 0;
               padding: 20px; }
    legend { font-weight: 800; padding: 0 8px; }
    dl { display: grid; grid-template-columns: minmax(170px, 0.42fr) minmax(0, 1fr);
         gap: 10px 16px; margin: 0; }
    dt { color: var(--muted); font-weight: 700; }
    dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
    code { background: #edf2f6; border: 1px solid var(--line); border-radius: 6px;
           padding: 2px 5px; overflow-wrap: anywhere; }
    table { border-collapse: collapse; width: 100%; table-layout: fixed; }
    th, td { border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left;
             vertical-align: top; overflow-wrap: anywhere; }
    th { color: var(--muted); font-size: 0.86rem; }
    a { color: var(--accent); font-weight: 700; }
    .badges { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
    .badge { border-radius: 999px; display: inline-flex; align-items: center;
             background: var(--info-bg); color: var(--info-ink); font-size: 0.86rem;
             font-weight: 700; padding: 5px 10px; }
    .badge.warn { background: var(--warn-bg); color: var(--warn-ink); }
    .badge.good { background: var(--good-bg); color: var(--good-ink); }
    .stage-pending { border-left: 4px solid var(--warn-ink); }
    .stage-rejected { border-left: 4px solid #8a2d24; }
    .stage-approved-ungranted { border-left: 4px solid var(--accent); }
    .stage-granted { border-left: 4px solid var(--good-ink); }
    .error { border-left: 4px solid #b42318; }
    .error h2 { color: #8a1f14; }
    .safety { border-left: 4px solid var(--accent); }
    .safety ul { margin: 0; padding-left: 20px; }
    .safety li + li { margin-top: 6px; }
    .actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
    .footer-link { margin-top: 18px; }
    .hint { color: var(--muted); font-size: 0.86rem; }
    .table-wrap { overflow-x: auto; }
    .window-table { min-width: 720px; }
    @media (max-width: 700px) {
      main { width: calc(100% - 20px); padding: 20px 0 36px; }
      .hero, .card { padding: 18px; }
      h1 { font-size: 1.6rem; }
      .grid { grid-template-columns: minmax(0, 1fr); }
      dl { grid-template-columns: 1fr; gap: 4px; }
      dd + dt { margin-top: 10px; }
    }
"""

SAFETY_BOUNDARY_ITEMS = (
    "request is not approval; approval is not grant; grant is not execution",
    "evaluation is evidence only; an allowed evaluation is not runtime enforcement",
    "Workbench access is not authority; no automatic approval, grant, revocation, or evaluation",
    "no tool invocation, operation admission, execution receipt, or runtime enforcement exists",
    "trusted local operator boundary; no production authentication in this slice",
    "append-only evidence: every record is durable and immutable",
)


class AuthorityStage(StrEnum):
    """Truthful evidence-derived lifecycle stage for one request."""

    PENDING = "pending"
    REJECTED = "rejected"
    APPROVED_UNGRANTED = "approved-ungranted"
    GRANTED = "granted"


def _format_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def render_authority_page(title: str, body: str) -> str:
    """Render one complete Approval Workbench HTML page (escaped title)."""

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)}</title>
    <style>{PAGE_CSS}</style>
  </head>
  <body>
    <main>
      {body}
    </main>
  </body>
</html>
"""


def render_safety_panel() -> str:
    items = "\n".join(f"<li>{escape(item)}</li>" for item in SAFETY_BOUNDARY_ITEMS)
    return f"""<section class="card safety" aria-labelledby="safety-heading">
      <h2 id="safety-heading">Authority boundary</h2>
      <ul>{items}</ul>
    </section>"""


def render_overview(
    *,
    owner_id: str,
    requests: tuple[ApprovalRequest, ...],
    grants: tuple[CapabilityGrant, ...],
    page_size: int,
    requests_truncated: bool,
    grants_truncated: bool,
) -> str:
    """Render the Workbench overview: bounded owner-scoped evidence summaries."""

    request_rows = "\n".join(_request_summary_row(request) for request in requests)
    if not request_rows:
        request_rows = (
            '<tr><td colspan="4">No approval requests have been recorded for this owner.</td></tr>'
        )
    grant_rows = "\n".join(_grant_summary_row(grant) for grant in grants)
    if not grant_rows:
        grant_rows = '<tr><td colspan="3">No capability grants have been issued.</td></tr>'
    request_truncation_note = (
        f'<p class="hint">Showing the first {page_size} approval requests. '
        "Older approval-request evidence exists.</p>"
        if requests_truncated
        else ""
    )
    grant_truncation_note = (
        f'<p class="hint">Showing the first {page_size} capability grants. '
        "Older capability-grant evidence exists.</p>"
        if grants_truncated
        else ""
    )
    body = f"""
      <section class="hero">
        <p class="eyebrow">Approval Workbench</p>
        <h1>Authority operator overview</h1>
        <p>A read-only deterministic projection of stored authority evidence for one
        trusted local operator. This page does not authorize, execute, or enforce
        anything.</p>
        <div class="badges">
          <span class="badge">owner: {escape(owner_id)}</span>
          <span class="badge warn">evidence only</span>
          <span class="badge">no execution</span>
        </div>
      </section>
      <section class="card" aria-labelledby="requests-heading">
        <h2 id="requests-heading">Recent approval requests</h2>
        <div class="table-wrap">
          <table class="window-table">
            <thead>
              <tr>
                <th>Request</th><th>Capability</th><th>Evidence</th><th>Inspect</th>
              </tr>
            </thead>
            <tbody>{request_rows}</tbody>
          </table>
        </div>
        {request_truncation_note}
      </section>
      <section class="card" aria-labelledby="grants-heading">
        <h2 id="grants-heading">Recent capability grants</h2>
        <div class="table-wrap">
          <table class="window-table">
            <thead>
              <tr><th>Grant</th><th>Capability</th><th>Inspect</th></tr>
            </thead>
            <tbody>{grant_rows}</tbody>
          </table>
        </div>
        {grant_truncation_note}
      </section>
      <section class="grid">
        <div class="card">
          <h2>Start a request</h2>
          <p>Compose an explicit, non-authoritative approval request for review.</p>
          <p><a class="button secondary" href="/authority/workbench/requests/new">Open the
            new-request form</a></p>
        </div>
      </section>
      {render_safety_panel()}
      <p class="footer-link"><a href="/review">Back to reviewer sandbox</a></p>
    """
    return render_authority_page("Approval Workbench", body)


def _request_summary_row(request: ApprovalRequest) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(request.request_id)}</code></td>"
        f"<td>{escape(request.capability)}</td>"
        "<td>request recorded; inspect for lifecycle evidence</td>"
        f'<td><a href="/authority/workbench/requests/{escape(request.request_id)}">Inspect</a></td>'
        "</tr>"
    )


def _grant_summary_row(grant: CapabilityGrant) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(grant.grant_id)}</code></td>"
        f"<td>{escape(grant.capability)}</td>"
        f'<td><a href="/authority/workbench/grants/{escape(grant.grant_id)}">Inspect</a></td>'
        "</tr>"
    )


def render_new_request_form(*, csrf_token: str, owner_id: str) -> str:
    """Render the new-approval-request form (POST-only)."""

    body = f"""
      <section class="hero">
        <p class="eyebrow">Non-authoritative request</p>
        <h1>Create approval request</h1>
        <p>This records one explicit, non-authoritative approval request. Creating it
        grants nothing and approves nothing.</p>
        <div class="badges">
          <span class="badge warn">request is not approval</span>
          <span class="badge">owner: {escape(owner_id)}</span>
        </div>
      </section>
      <form method="post" action="/authority/workbench/requests" class="card stack">
        <input type="hidden" name="{AUTHORITY_WORKBENCH_CSRF_FORM_FIELD}"
          value="{escape(csrf_token)}">
        <fieldset>
          <legend>Request identity and policy</legend>
          <div class="grid">
            <label>Request id (lowercase, 8-64 chars)
              <input name="request_id" maxlength="64" autocomplete="off" required>
            </label>
            <label>Policy version
              <input name="policy_version" maxlength="64" autocomplete="off" required>
            </label>
            <label>Idempotency key
              <input name="idempotency_key" maxlength="200" autocomplete="off" required>
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Subject and capability</legend>
          <div class="grid">
            <label>Subject type
              <select name="subject_type">
                <option value="operator">operator</option>
                <option value="agent">agent</option>
                <option value="laboratory">laboratory</option>
                <option value="tool">tool</option>
                <option value="adapter">adapter</option>
              </select>
            </label>
            <label>Subject id
              <input name="subject_id" maxlength="64" autocomplete="off" required>
            </label>
            <label>Capability
              <input name="capability" maxlength="64" autocomplete="off" required>
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Scope</legend>
          <div class="grid">
            <label>Resource type
              <input name="scope_resource_type" maxlength="64" autocomplete="off" required>
            </label>
            <label>Resource id
              <input name="scope_resource_id" maxlength="128" autocomplete="off" required>
            </label>
          </div>
          <p class="hint">Scope constraints are not edited here. Add them through the JSON
          API after the request exists if your workflow requires them.</p>
        </fieldset>
        <fieldset>
          <legend>Purpose and validity</legend>
          <label>Purpose (max 300 chars)
            <textarea name="purpose" maxlength="300" required></textarea>
          </label>
          <div class="grid">
            <label>Requested at (UTC ISO 8601, e.g. 2026-07-19T12:00:00Z)
              <input name="requested_at" maxlength="40" autocomplete="off" required>
            </label>
            <label>Valid from (UTC ISO 8601)
              <input name="valid_from" maxlength="40" autocomplete="off" required>
            </label>
            <label>Expires at (UTC ISO 8601)
              <input name="expires_at" maxlength="40" autocomplete="off" required>
            </label>
          </div>
        </fieldset>
        <label><input type="checkbox" name="confirm" value="yes" required>
          I confirm this creates an approval request only.</label>
        <div class="actions">
          <button class="button" type="submit">Create approval request</button>
          <a class="button secondary" href="/authority/workbench">Cancel</a>
        </div>
      </form>
      {render_safety_panel()}
      <p class="footer-link"><a href="/authority/workbench">Back to overview</a></p>
    """
    return render_authority_page("Create approval request", body)


def render_request_detail(
    *,
    owner_id: str,
    request: ApprovalRequest,
    decisions: tuple[ApprovalDecision, ...],
    grants: tuple[CapabilityGrant, ...],
    revocations: tuple[RevocationRecord, ...],
    evaluations: tuple[AuthorityEvaluationDecision, ...],
    csrf_token: str,
) -> str:
    """Render one request's complete evidence chain with explicit action forms."""

    stage = _derive_stage(decisions, grants)
    stage_badge_class = {
        AuthorityStage.PENDING: "warn",
        AuthorityStage.REJECTED: "warn",
        AuthorityStage.APPROVED_UNGRANTED: "",
        AuthorityStage.GRANTED: "good",
    }[stage]
    decision_rows = "\n".join(_decision_row(decision) for decision in decisions) or (
        '<tr><td colspan="4">No terminal decision recorded.</td></tr>'
    )
    grant_rows = "\n".join(
        _grant_chain_row(grant, revocations, evaluations) for grant in grants
    ) or ('<tr><td colspan="4">No grant has been issued for this request.</td></tr>')
    action_panel = _render_request_actions(request, decisions, stage, csrf_token)
    body = f"""
      <section class="hero">
        <p class="eyebrow">Approval request evidence</p>
        <h1>Request <code>{escape(request.request_id)}</code></h1>
        <p>This page shows the stored evidence chain for one approval request. The stage
        badge is derived strictly from stored evidence tuples, never from a system clock.</p>
        <div class="badges">
          <span class="badge {stage_badge_class}">stage: {escape(stage.value)}</span>
          <span class="badge">owner: {escape(owner_id)}</span>
          <span class="badge warn">evidence only</span>
        </div>
      </section>
      <section class="card stage-{escape(stage.value)}">
        <h2>Request</h2>
        <dl>
          <dt>request id</dt><dd><code>{escape(request.request_id)}</code></dd>
          <dt>requested by</dt><dd><code>{escape(request.requested_by)}</code></dd>
          <dt>subject</dt>
          <dd>{escape(request.subject.subject_type.value)}:
            <code>{escape(request.subject.subject_id)}</code></dd>
          <dt>capability</dt><dd><code>{escape(request.capability)}</code></dd>
          <dt>resource</dt>
          <dd><code>{escape(request.scope.resource_type)}</code> /
            <code>{escape(request.scope.resource_id)}</code></dd>
          <dt>purpose</dt><dd>{escape(request.purpose)}</dd>
          <dt>policy version</dt><dd><code>{escape(request.policy_version)}</code></dd>
          <dt>requested at</dt><dd>{escape(_format_utc(request.requested_at))}</dd>
          <dt>valid from</dt><dd>{escape(_format_utc(request.validity.valid_from))}</dd>
          <dt>expires at</dt><dd>{escape(_format_utc(request.validity.expires_at))}</dd>
        </dl>
      </section>
      {action_panel}
      <section class="card" aria-labelledby="decisions-heading">
        <h2 id="decisions-heading">Terminal decisions</h2>
        <div class="table-wrap">
          <table class="window-table">
            <thead>
              <tr>
                <th>Decision</th><th>Outcome</th><th>Decided at</th><th>Reason</th>
              </tr>
            </thead>
            <tbody>{decision_rows}</tbody>
          </table>
        </div>
      </section>
      <section class="card" aria-labelledby="grants-heading">
        <h2 id="grants-heading">Capability grants and evaluations</h2>
        <div class="table-wrap">
          <table class="window-table">
            <thead>
              <tr>
                <th>Grant</th><th>Issued at</th><th>Revocations</th><th>Evaluations</th>
              </tr>
            </thead>
            <tbody>{grant_rows}</tbody>
          </table>
        </div>
      </section>
      {render_safety_panel()}
      <p class="footer-link"><a href="/authority/workbench">Back to overview</a></p>
    """
    return render_authority_page(f"Request {request.request_id}", body)


def _decision_row(decision: ApprovalDecision) -> str:
    outcome_label = (
        "approved" if decision.outcome is ApprovalDecisionOutcome.APPROVED else "rejected"
    )
    return (
        "<tr>"
        f"<td><code>{escape(decision.decision_id)}</code></td>"
        f"<td>{escape(outcome_label)}</td>"
        f"<td>{escape(_format_utc(decision.decided_at))}</td>"
        f"<td>{escape(decision.reason)}</td>"
        "</tr>"
    )


def _grant_chain_row(
    grant: CapabilityGrant,
    revocations: tuple[RevocationRecord, ...],
    evaluations: tuple[AuthorityEvaluationDecision, ...],
) -> str:
    relevant_revoke = [r for r in revocations if r.grant_id == grant.grant_id]
    relevant_eval = [e for e in evaluations if e.grant_id == grant.grant_id]
    return (
        "<tr>"
        f'<td><a href="/authority/workbench/grants/{escape(grant.grant_id)}">'
        f"<code>{escape(grant.grant_id)}</code></a></td>"
        f"<td>{escape(_format_utc(grant.issued_at))}</td>"
        f"<td>{len(relevant_revoke)}</td>"
        f"<td>{len(relevant_eval)}</td>"
        "</tr>"
    )


def _render_request_actions(
    request: ApprovalRequest,
    decisions: tuple[ApprovalDecision, ...],
    stage: AuthorityStage,
    csrf_token: str,
) -> str:
    """Render only the explicit POST forms valid for the current evidence stage."""

    if decisions and stage is not AuthorityStage.APPROVED_UNGRANTED:
        # A request that already carries a terminal decision accepts no second
        # decision. An APPROVED_UNGRANTED request, however, still has one valid
        # forward action — issuing the grant — so it falls through to its own
        # branch below rather than to this immutable-decision notice.
        return """
          <section class="card soft">
            <h2>Further action</h2>
            <p>This request already has a terminal decision. A second terminal decision
            would be rejected as an immutable-evidence conflict.</p>
          </section>
        """
    if stage is AuthorityStage.PENDING:
        return f"""
          <section class="card stack" aria-labelledby="actions-heading">
            <h2 id="actions-heading">Explicit actions</h2>
            <p>Each action records one piece of durable evidence. None of them execute
            anything, and none of them take effect automatically.</p>
            <div class="actions">
              <a class="button"
                href="/authority/workbench/requests/{escape(request.request_id)}/decide">
                Record decision
              </a>
            </div>
            <p class="hint">Grant issuance becomes available only after an approved
            decision is recorded.</p>
            <input type="hidden" name="{AUTHORITY_WORKBENCH_CSRF_FORM_FIELD}"
              value="{escape(csrf_token)}" form="noop-authority-form">
          </section>
        """
    if stage is AuthorityStage.APPROVED_UNGRANTED:
        return f"""
          <section class="card stack" aria-labelledby="actions-heading">
            <h2 id="actions-heading">Explicit actions</h2>
            <p>This request has an approved terminal decision but no grant yet. Issuing a
            grant is a separate explicit step.</p>
            <div class="actions">
              <a class="button"
                href="/authority/workbench/requests/{escape(request.request_id)}/issue-grant">
                Issue grant
              </a>
            </div>
            <input type="hidden" name="{AUTHORITY_WORKBENCH_CSRF_FORM_FIELD}"
              value="{escape(csrf_token)}" form="noop-authority-form">
          </section>
        """
    return ""


def render_decision_form(
    *,
    request: ApprovalRequest,
    csrf_token: str,
) -> str:
    body = f"""
      <section class="hero">
        <p class="eyebrow">Terminal decision</p>
        <h1>Record decision for request <code>{escape(request.request_id)}</code></h1>
        <p>Recording a decision appends one terminal evidence record. An approval does not
        issue a grant; a rejection creates no grant and no evaluation.</p>
      </section>
      <section class="card stage-pending">
        <h2>Request being decided</h2>
        <dl>
          <dt>subject</dt>
          <dd>{escape(request.subject.subject_type.value)}:
            <code>{escape(request.subject.subject_id)}</code></dd>
          <dt>capability</dt><dd><code>{escape(request.capability)}</code></dd>
          <dt>resource</dt>
          <dd><code>{escape(request.scope.resource_type)}</code> /
            <code>{escape(request.scope.resource_id)}</code></dd>
          <dt>purpose</dt><dd>{escape(request.purpose)}</dd>
          <dt>policy version</dt><dd><code>{escape(request.policy_version)}</code></dd>
          <dt>valid from</dt><dd>{escape(_format_utc(request.validity.valid_from))}</dd>
          <dt>expires at</dt><dd>{escape(_format_utc(request.validity.expires_at))}</dd>
        </dl>
      </section>
      <form method="post"
        action="/authority/workbench/requests/{escape(request.request_id)}/decide"
        class="card stack">
        <input type="hidden" name="{AUTHORITY_WORKBENCH_CSRF_FORM_FIELD}"
          value="{escape(csrf_token)}">
        <fieldset>
          <legend>Decision</legend>
          <div class="grid">
            <label>Decision id
              <input name="decision_id" maxlength="64" autocomplete="off" required>
            </label>
            <label>Outcome
              <select name="outcome">
                <option value="approved">approved</option>
                <option value="rejected">rejected</option>
              </select>
            </label>
            <label>Decided at (UTC ISO 8601)
              <input name="decided_at" maxlength="40" autocomplete="off" required>
            </label>
            <label>Policy version (must match the request)
              <input name="policy_version" value="{escape(request.policy_version)}"
                maxlength="64" autocomplete="off" required>
            </label>
            <label>Idempotency key
              <input name="idempotency_key" maxlength="200" autocomplete="off" required>
            </label>
          </div>
          <label>Reason (max 300 chars)
            <textarea name="reason" maxlength="300" required></textarea>
          </label>
        </fieldset>
        <label><input type="checkbox" name="confirm" value="yes" required>
          I confirm this is a terminal decision.</label>
        <div class="actions">
          <button class="button" type="submit">Record decision</button>
          <a class="button secondary"
            href="/authority/workbench/requests/{escape(request.request_id)}">Cancel</a>
        </div>
      </form>
      {render_safety_panel()}
      <p class="footer-link">
        <a href="/authority/workbench/requests/{escape(request.request_id)}">Back to request</a>
      </p>
    """
    return render_authority_page("Record decision", body)


def render_issue_grant_form(
    *,
    request: ApprovalRequest,
    decision: ApprovalDecision,
    csrf_token: str,
) -> str:
    body = f"""
      <section class="hero">
        <p class="eyebrow">Explicit grant issuance</p>
        <h1>Issue grant for request <code>{escape(request.request_id)}</code></h1>
        <p>The grant will inherit subject, capability, scope, purpose, policy version and
        validity exactly from the approved decision. Issuing a grant is not execution.</p>
      </section>
      <section class="card stage-approved-ungranted">
        <h2>Stored approval truth</h2>
        <dl>
          <dt>decision</dt><dd><code>{escape(decision.decision_id)}</code></dd>
          <dt>subject</dt>
          <dd>{escape(request.subject.subject_type.value)}:
            <code>{escape(request.subject.subject_id)}</code></dd>
          <dt>capability</dt><dd><code>{escape(request.capability)}</code></dd>
          <dt>valid from</dt><dd>{escape(_format_utc(request.validity.valid_from))}</dd>
          <dt>expires at</dt><dd>{escape(_format_utc(request.validity.expires_at))}</dd>
        </dl>
      </section>
      <form method="post"
        action="/authority/workbench/requests/{escape(request.request_id)}/issue-grant"
        class="card stack">
        <input type="hidden" name="{AUTHORITY_WORKBENCH_CSRF_FORM_FIELD}"
          value="{escape(csrf_token)}">
        <input type="hidden" name="decision_id" value="{escape(decision.decision_id)}">
        <fieldset>
          <legend>Grant identity</legend>
          <div class="grid">
            <label>Grant id
              <input name="grant_id" maxlength="64" autocomplete="off" required>
            </label>
            <label>Issued at (UTC ISO 8601)
              <input name="issued_at" maxlength="40" autocomplete="off" required>
            </label>
            <label>Policy version (must match the approval)
              <input name="policy_version" value="{escape(request.policy_version)}"
                maxlength="64" autocomplete="off" required>
            </label>
            <label>Idempotency key
              <input name="idempotency_key" maxlength="200" autocomplete="off" required>
            </label>
          </div>
        </fieldset>
        <label><input type="checkbox" name="confirm" value="yes" required>
          I confirm this explicitly issues a capability grant.</label>
        <div class="actions">
          <button class="button" type="submit">Issue grant</button>
          <a class="button secondary"
            href="/authority/workbench/requests/{escape(request.request_id)}">Cancel</a>
        </div>
      </form>
      {render_safety_panel()}
      <p class="footer-link">
        <a href="/authority/workbench/requests/{escape(request.request_id)}">Back to request</a>
      </p>
    """
    return render_authority_page("Issue grant", body)


def render_grant_detail(
    *,
    owner_id: str,
    grant: CapabilityGrant,
    revocations: tuple[RevocationRecord, ...],
    evaluations: tuple[AuthorityEvaluationDecision, ...],
    revocations_truncated: bool,
    evaluations_truncated: bool,
    csrf_token: str,
) -> str:
    revoke_rows = "\n".join(_revocation_row(r) for r in revocations) or (
        '<tr><td colspan="3">No revocation recorded.</td></tr>'
    )
    eval_rows = "\n".join(_evaluation_row(e) for e in evaluations) or (
        '<tr><td colspan="3">No persisted evaluation.</td></tr>'
    )
    revocation_truncation_note = (
        f'<p class="hint">Showing the first {len(revocations)} revocation records. '
        "Older revocation evidence exists.</p>"
        if revocations_truncated
        else ""
    )
    evaluation_truncation_note = (
        f'<p class="hint">Showing the first {len(evaluations)} persisted evaluations. '
        "Older evaluation evidence exists.</p>"
        if evaluations_truncated
        else ""
    )
    body = f"""
      <section class="hero">
        <p class="eyebrow">Capability grant evidence</p>
        <h1>Grant <code>{escape(grant.grant_id)}</code></h1>
        <p>A grant is evidence of an approved capability. Possession of a grant is not
        execution authority; an allowed evaluation is evidence only.</p>
        <div class="badges">
          <span class="badge">owner: {escape(owner_id)}</span>
          <span class="badge warn">no runtime enforcement</span>
        </div>
      </section>
      <section class="card">
        <h2>Grant</h2>
        <dl>
          <dt>grant id</dt><dd><code>{escape(grant.grant_id)}</code></dd>
          <dt>request</dt><dd><code>{escape(grant.request_id)}</code></dd>
          <dt>decision</dt><dd><code>{escape(grant.decision_id)}</code></dd>
          <dt>issued by</dt><dd><code>{escape(grant.issued_by.subject_id)}</code></dd>
          <dt>issued at</dt><dd>{escape(_format_utc(grant.issued_at))}</dd>
          <dt>subject</dt>
          <dd>{escape(grant.subject.subject_type.value)}:
            <code>{escape(grant.subject.subject_id)}</code></dd>
          <dt>capability</dt><dd><code>{escape(grant.capability)}</code></dd>
          <dt>valid from</dt><dd>{escape(_format_utc(grant.validity.valid_from))}</dd>
          <dt>expires at</dt><dd>{escape(_format_utc(grant.validity.expires_at))}</dd>
          <dt>delegation</dt><dd><code>{escape(grant.delegation.value)}</code></dd>
        </dl>
        <div class="actions">
          <a class="button"
            href="/authority/workbench/grants/{escape(grant.grant_id)}/revoke">Revoke grant</a>
          <a class="button secondary"
            href="/authority/workbench/grants/{escape(grant.grant_id)}/evaluate">
            Record evaluation
          </a>
        </div>
      </section>
      <section class="card" aria-labelledby="revocations-heading">
        <h2 id="revocations-heading">Revocations</h2>
        <div class="table-wrap">
          <table class="window-table">
            <thead><tr><th>Revocation</th><th>Effective at</th><th>Reason</th></tr></thead>
            <tbody>{revoke_rows}</tbody>
          </table>
        </div>
        {revocation_truncation_note}
      </section>
      <section class="card" aria-labelledby="evaluations-heading">
        <h2 id="evaluations-heading">Persisted evaluations (evidence only)</h2>
        <div class="table-wrap">
          <table class="window-table">
            <thead>
              <tr><th>Evaluation</th><th>Result</th><th>At (explicit)</th></tr>
            </thead>
            <tbody>{eval_rows}</tbody>
          </table>
        </div>
        {evaluation_truncation_note}
      </section>
      {render_safety_panel()}
      <p class="footer-link"><a href="/authority/workbench">Back to overview</a></p>
    """
    # csrf_token is rendered on the linked forms, not on this read-only page; keep
    # the parameter so callers always pass the active session token explicitly.
    del csrf_token
    return render_authority_page(f"Grant {grant.grant_id}", body)


def _revocation_row(revocation: RevocationRecord) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(revocation.revocation_id)}</code></td>"
        f"<td>{escape(_format_utc(revocation.effective_at))}</td>"
        f"<td>{escape(revocation.reason)}</td>"
        "</tr>"
    )


def _evaluation_row(evaluation: AuthorityEvaluationDecision) -> str:
    result_label = "allowed" if evaluation.authorized else f"denied: {evaluation.reason_code.value}"
    return (
        "<tr>"
        f"<td><code>{escape(evaluation.evaluation_id)}</code></td>"
        f"<td>{escape(result_label)}</td>"
        f"<td>{escape(_format_utc(evaluation.evaluation_time))}</td>"
        "</tr>"
    )


def render_revoke_form(*, grant: CapabilityGrant, csrf_token: str) -> str:
    body = f"""
      <section class="hero">
        <p class="eyebrow">Append-only revocation</p>
        <h1>Revoke grant <code>{escape(grant.grant_id)}</code></h1>
        <p>A revocation appends one durable evidence record; it does not mutate the grant
        and does not automatically evaluate.</p>
      </section>
      <form method="post"
        action="/authority/workbench/grants/{escape(grant.grant_id)}/revoke"
        class="card stack">
        <input type="hidden" name="{AUTHORITY_WORKBENCH_CSRF_FORM_FIELD}"
          value="{escape(csrf_token)}">
        <fieldset>
          <legend>Revocation</legend>
          <div class="grid">
            <label>Revocation id
              <input name="revocation_id" maxlength="64" autocomplete="off" required>
            </label>
            <label>Effective at (UTC ISO 8601)
              <input name="effective_at" maxlength="40" autocomplete="off" required>
            </label>
            <label>Recorded at (UTC ISO 8601)
              <input name="recorded_at" maxlength="40" autocomplete="off" required>
            </label>
            <label>Policy version (must match the grant)
              <input name="policy_version" value="{escape(grant.policy_version)}"
                maxlength="64" autocomplete="off" required>
            </label>
            <label>Idempotency key
              <input name="idempotency_key" maxlength="200" autocomplete="off" required>
            </label>
          </div>
          <label>Reason (max 300 chars)
            <textarea name="reason" maxlength="300" required></textarea>
          </label>
        </fieldset>
        <label><input type="checkbox" name="confirm" value="yes" required>
          I confirm this appends a revocation record.</label>
        <div class="actions">
          <button class="button danger" type="submit">Revoke grant</button>
          <a class="button secondary"
            href="/authority/workbench/grants/{escape(grant.grant_id)}">Cancel</a>
        </div>
      </form>
      {render_safety_panel()}
      <p class="footer-link">
        <a href="/authority/workbench/grants/{escape(grant.grant_id)}">Back to grant</a>
      </p>
    """
    return render_authority_page("Revoke grant", body)


def render_evaluate_form(*, grant: CapabilityGrant, csrf_token: str) -> str:
    body = f"""
      <section class="hero">
        <p class="eyebrow">Persisted evaluation</p>
        <h1>Evaluate grant <code>{escape(grant.grant_id)}</code></h1>
        <p>An evaluation is one persisted question about the stored authority chain at one
        explicit evaluation time. An allowed result is evidence only and is never runtime
        enforcement.</p>
      </section>
      <form method="post"
        action="/authority/workbench/grants/{escape(grant.grant_id)}/evaluate"
        class="card stack">
        <input type="hidden" name="{AUTHORITY_WORKBENCH_CSRF_FORM_FIELD}"
          value="{escape(csrf_token)}">
        <fieldset>
          <legend>Evaluation</legend>
          <div class="grid">
            <label>Evaluation id
              <input name="evaluation_id" maxlength="64" autocomplete="off" required>
            </label>
            <label>Evaluation time (UTC ISO 8601)
              <input name="evaluation_time" maxlength="40" autocomplete="off" required>
            </label>
            <label>Policy version (must match the grant)
              <input name="policy_version" value="{escape(grant.policy_version)}"
                maxlength="64" autocomplete="off" required>
            </label>
            <label>Idempotency key
              <input name="idempotency_key" maxlength="200" autocomplete="off" required>
            </label>
            <label>Delegation requested
              <select name="delegation_requested">
                <option value="false">false</option>
                <option value="true">true</option>
              </select>
            </label>
          </div>
        </fieldset>
        <label><input type="checkbox" name="confirm" value="yes" required>
          I confirm this records evidence only and executes nothing.</label>
        <div class="actions">
          <button class="button" type="submit">Record evaluation</button>
          <a class="button secondary"
            href="/authority/workbench/grants/{escape(grant.grant_id)}">Cancel</a>
        </div>
      </form>
      {render_safety_panel()}
      <p class="footer-link">
        <a href="/authority/workbench/grants/{escape(grant.grant_id)}">Back to grant</a>
      </p>
    """
    return render_authority_page("Record evaluation", body)


def render_error_page(*, title: str, message: str) -> str:
    body = f"""
      <section class="hero">
        <p class="eyebrow">Rejected</p>
        <h1>{escape(title)}</h1>
      </section>
      <section class="grid">
        <div class="card error">
          <h2>Request not accepted</h2>
          <p>{escape(message)}</p>
          <p><a href="/authority/workbench">Back to Approval Workbench overview</a></p>
        </div>
      </section>
      {render_safety_panel()}
    """
    return render_authority_page(title, body)


def _derive_stage(
    decisions: tuple[ApprovalDecision, ...],
    grants: tuple[CapabilityGrant, ...],
) -> AuthorityStage:
    """Derive the truthful lifecycle stage strictly from stored evidence tuples."""

    if not decisions:
        return AuthorityStage.PENDING
    decision = decisions[0]
    if decision.outcome is ApprovalDecisionOutcome.REJECTED:
        return AuthorityStage.REJECTED
    if grants:
        return AuthorityStage.GRANTED
    return AuthorityStage.APPROVED_UNGRANTED


__all__ = [
    "AUTHORITY_API_SCHEMA_VERSION",
    "PAGE_CSS",
    "SAFETY_BOUNDARY_ITEMS",
    "AuthorityStage",
    "render_authority_page",
    "render_decision_form",
    "render_error_page",
    "render_evaluate_form",
    "render_grant_detail",
    "render_issue_grant_form",
    "render_new_request_form",
    "render_overview",
    "render_request_detail",
    "render_revoke_form",
    "render_safety_panel",
]


# Reason-code constant import is exposed for templates that need the canonical
# reason-code vocabulary when displaying evaluations.
_REASON_CODE_VALUES = tuple(reason_code.value for reason_code in AuthorityReasonCode)
