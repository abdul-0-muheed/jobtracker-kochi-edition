"""
blueprints/companies.py — Company CRUD, xlsx upload, email logging, follow-ups.
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from werkzeug.utils import secure_filename

from flask import (
    Blueprint, Response, flash, jsonify, redirect,
    render_template, request, url_for,
)

from config import load_settings
from models import Company, FollowUp, Application, Contact, LinkedInEvent, Opening, db
from services.spreadsheet_parser import parse_xlsx
from services.reminders import due_on_for_email

companies_bp = Blueprint("companies", __name__, url_prefix="/companies")

ALLOWED_EXT = {"xlsx"}


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


# ── List ───────────────────────────────────────────────────────────────────────
@companies_bp.route("/")
def list_companies():
    page      = request.args.get("page", 1, type=int)
    industry  = request.args.get("industry", "")
    status    = request.args.get("status", "")
    min_score = request.args.get("min_score", 0, type=int)
    max_score = request.args.get("max_score", 100, type=int)
    search    = request.args.get("q", "")
    sort      = request.args.get("sort", "match_score_desc")
    has_infopark = request.args.get("has_infopark", "")

    q = Company.query

    if search:
        q = q.filter(Company.name.ilike(f"%{search}%"))
    if industry:
        q = q.filter(Company.industry.ilike(f"%{industry}%"))
    if status:
        q = q.filter(Company.contact_status == status)
    if min_score:
        q = q.filter(Company.match_score >= min_score)
    if max_score < 100:
        q = q.filter(Company.match_score <= max_score)

    sort_map = {
        "match_score_desc": Company.match_score.desc(),
        "match_score_asc":  Company.match_score.asc(),
        "name_asc":         Company.name.asc(),
        "name_desc":        Company.name.desc(),
        "last_activity":    Company.last_activity_at.desc(),
    }
    q = q.order_by(sort_map.get(sort, Company.match_score.desc()))

    # Filter: only companies that have ≥1 Infopark application
    if has_infopark == "1":
        from models import InfoparkApplied
        infopark_cids = db.session.query(InfoparkApplied.matched_company_id).filter(
            InfoparkApplied.matched_company_id.isnot(None)
        ).distinct().subquery()
        q = q.filter(Company.id.in_(infopark_cids))

    pagination = q.paginate(page=page, per_page=25, error_out=False)

    # Get unique industries for filter dropdown
    all_industries = [
        row[0] for row in db.session.query(Company.industry).distinct()
        if row[0]
    ]

    # Infopark applied counts per company_id
    from models import InfoparkApplied
    from sqlalchemy import func as sqlfunc
    infopark_rows = (
        db.session.query(InfoparkApplied.matched_company_id,
                         sqlfunc.count(InfoparkApplied.id).label("cnt"))
        .filter(InfoparkApplied.matched_company_id.isnot(None))
        .group_by(InfoparkApplied.matched_company_id)
        .all()
    )
    infopark_applied_counts = {row.matched_company_id: row.cnt for row in infopark_rows}

    return render_template(
        "companies/list.html",
        companies=pagination.items,
        pagination=pagination,
        industries=sorted(all_industries),
        infopark_applied_counts=infopark_applied_counts,
        current_filters={
            "industry": industry, "status": status, "q": search,
            "min_score": min_score, "max_score": max_score, "sort": sort,
            "has_infopark": has_infopark,
        },
    )


# ── Upload ─────────────────────────────────────────────────────────────────────
@companies_bp.route("/upload", methods=["GET"])
def upload_form():
    return render_template("companies/upload.html")


@companies_bp.route("/upload", methods=["POST"])
def upload_xlsx():
    if "file" not in request.files:
        flash("No file selected.", "danger")
        return redirect(url_for("companies.upload_form"))

    f = request.files["file"]
    if not f.filename or not _allowed(f.filename):
        flash("Please upload a .xlsx file.", "danger")
        return redirect(url_for("companies.upload_form"))

    from config import Config
    upload_dir = Path(Config.UPLOAD_FOLDER)
    fname = secure_filename(f.filename)
    fpath = upload_dir / fname
    f.save(str(fpath))

    try:
        rows, warnings = parse_xlsx(fpath)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("companies.upload_form"))

    # Deduplicate and insert
    inserted = 0
    skipped  = 0
    for row in rows:
        name = row.get("name", "").strip()
        if not name:
            continue
        existing = Company.query.filter(
            db.func.lower(db.func.trim(Company.name)) == name.lower()
        ).first()
        if existing:
            skipped += 1
            continue
        company = Company(**row)
        db.session.add(company)
        inserted += 1

    db.session.commit()

    msg = f"Imported {inserted} companies."
    if skipped:
        msg += f" Skipped {skipped} duplicates."
    if warnings:
        msg += " Warnings: " + "; ".join(warnings)
    flash(msg, "success")
    return redirect(url_for("companies.list_companies"))


# ── Detail ─────────────────────────────────────────────────────────────────────
@companies_bp.route("/<int:cid>")
def detail(cid: int):
    company = Company.query.get_or_404(cid)

    # Build merged timeline
    timeline = []

    for ev in company.linkedin_events:
        timeline.append({
            "type": "linkedin",
            "icon": "linkedin",
            "at":   ev.event_at or ev.synced_at,
            "summary": f"LinkedIn: {ev.event_type.replace('_', ' ').title()}",
            "detail": ev.notes or "",
            "id": ev.id,
        })

    for app in company.applications:
        timeline.append({
            "type": "application",
            "icon": "briefcase",
            "at":   app.applied_at or app.created_at,
            "summary": f"Applied: {app.role_title}",
            "detail": f"Status: {app.status}",
            "id": app.id,
        })

    for fu in company.follow_ups:
        timeline.append({
            "type": "followup",
            "icon": "bell",
            "at":   fu.created_at,
            "summary": f"Follow-up ({fu.status}): due {fu.due_on}",
            "detail": fu.notes or "",
            "id": fu.id,
        })

    for op in company.openings:
        timeline.append({
            "type": "opening",
            "icon": "search",
            "at":   op.first_seen_at,
            "summary": f"Opening detected: {op.title}",
            "detail": f"Location: {op.location or '—'} | Status: {op.status}",
            "id": op.id,
            "url": op.url,
        })

    timeline.sort(key=lambda x: x.get("at") or "", reverse=True)

    open_jobs = [o for o in company.openings if o.status == "open"]
    pending_followups = [f for f in company.follow_ups if f.status == "pending"]

    return render_template(
        "companies/detail.html",
        company=company,
        timeline=timeline,
        open_jobs=open_jobs,
        pending_followups=pending_followups,
    )


# ── Edit ───────────────────────────────────────────────────────────────────────
@companies_bp.route("/<int:cid>", methods=["POST"])
def update_company(cid: int):
    company = Company.query.get_or_404(cid)
    editable = [
        "name", "website", "linkedin_url", "career_page_url", "hr_email",
        "founder_ceo", "founder_linkedin", "location", "company_size",
        "company_type", "industry", "tech_stack", "uses_react", "uses_python",
        "uses_ai", "internship_friendly", "freshers_hiring", "match_score",
        "notes", "contact_status",
    ]
    for field in editable:
        if field in request.form:
            val = request.form[field]
            if field in ("uses_react", "uses_python", "uses_ai"):
                setattr(company, field, val.lower() in ("true", "1", "yes", "on"))
            elif field == "match_score":
                try:
                    setattr(company, field, int(val))
                except (ValueError, TypeError):
                    pass
            else:
                setattr(company, field, val or None)
    company.touch()
    db.session.commit()
    flash("Company updated.", "success")
    return redirect(url_for("companies.detail", cid=cid))


# ── Delete ─────────────────────────────────────────────────────────────────────
@companies_bp.route("/<int:cid>/delete", methods=["POST"])
def delete_company(cid: int):
    company = Company.query.get_or_404(cid)
    db.session.delete(company)
    db.session.commit()
    flash(f"Deleted {company.name}.", "warning")
    return redirect(url_for("companies.list_companies"))


# ── Log HR Email ───────────────────────────────────────────────────────────────
@companies_bp.route("/<int:cid>/log-email", methods=["POST"])
def log_email(cid: int):
    company = Company.query.get_or_404(cid)
    data = request.get_json(force=True, silent=True) or request.form

    recipient_email = data.get("recipient_email", company.hr_email or "")
    recipient_name  = data.get("recipient_name", "")
    subject         = data.get("subject", "")
    body_excerpt    = data.get("body_excerpt", "")[:200]
    sent_at_raw     = data.get("sent_at", date.today().isoformat())

    # Find or create contact
    contact = None
    if recipient_email:
        contact = Contact.query.filter_by(company_id=cid, email=recipient_email).first()
        if not contact:
            contact = Contact(
                company_id=cid,
                name=recipient_name or recipient_email,
                email=recipient_email,
                contact_type="hr",
            )
            db.session.add(contact)
            db.session.flush()

    # Create application record to log the email
    app_rec = Application(
        company_id=cid,
        role_title=f"HR Email — {subject}" if subject else "HR Email outreach",
        source="other",
        applied_at=sent_at_raw,
        status="applied",
        notes=f"To: {recipient_email}\nSubject: {subject}\n\n{body_excerpt}",
    )
    db.session.add(app_rec)
    db.session.flush()

    # Auto-create follow-up
    settings = load_settings()
    cadence  = settings["reminders"]["follow_up_cadence_days"]
    try:
        sent_date = date.fromisoformat(sent_at_raw)
    except ValueError:
        sent_date = date.today()

    due_date = due_on_for_email(sent_date, cadence)
    fu = FollowUp(
        company_id=cid,
        application_id=app_rec.id,
        contact_id=contact.id if contact else None,
        due_on=due_date.isoformat(),
        notes=f"Follow up on HR email to {recipient_email or company.name}",
    )
    db.session.add(fu)

    # Update contact_status
    if company.contact_status == "not_contacted":
        company.contact_status = "emailed"
    company.touch()

    db.session.commit()

    if request.is_json or request.content_type == "application/json":
        return jsonify({"success": True, "follow_up_due": due_date.isoformat()}), 201

    flash(f"Email logged. Follow-up scheduled for {due_date.isoformat()}.", "success")
    return redirect(url_for("companies.detail", cid=cid))


# ── Schedule Follow-up ────────────────────────────────────────────────────────
@companies_bp.route("/<int:cid>/follow-up", methods=["POST"])
def schedule_followup(cid: int):
    company = Company.query.get_or_404(cid)
    data = request.get_json(force=True, silent=True) or request.form

    due_on     = data.get("due_on", date.today().isoformat())
    notes      = data.get("notes", "")
    contact_id = data.get("contact_id")

    fu = FollowUp(
        company_id=cid,
        contact_id=int(contact_id) if contact_id else None,
        due_on=due_on,
        notes=notes,
    )
    db.session.add(fu)
    company.touch()
    db.session.commit()

    if request.is_json:
        return jsonify({"success": True, "id": fu.id}), 201
    flash("Follow-up scheduled.", "success")
    return redirect(url_for("companies.detail", cid=cid))


# ── Update Follow-up ───────────────────────────────────────────────────────────
@companies_bp.route("/follow-ups/<int:fid>", methods=["PATCH", "POST"])
def update_followup(fid: int):
    fu = FollowUp.query.get_or_404(fid)
    data = request.get_json(force=True, silent=True) or request.form

    new_status = data.get("status", fu.status)
    fu.status = new_status
    if new_status == "done":
        fu.completed_at = datetime.now(timezone.utc).isoformat()
    elif new_status == "snoozed":
        fu.snooze_until = data.get("snooze_until", "")

    db.session.commit()

    if request.is_json or request.method == "PATCH":
        return jsonify({"success": True})
    flash("Follow-up updated.", "success")
    return redirect(url_for("companies.detail", cid=fu.company_id))


# ── Toggle Call Status ────────────────────────────────────────────────────────
@companies_bp.route("/<int:cid>/toggle-call", methods=["POST"])
def toggle_call(cid: int):
    """Toggle call_status between 'not_called' and 'called'."""
    company = Company.query.get_or_404(cid)
    if company.call_status == "called":
        company.call_status = "not_called"
        msg = "Marked as not called."
    else:
        company.call_status = "called"
        msg = "Marked as called!"
    company.touch()
    db.session.commit()

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "call_status": company.call_status,
            "message": msg,
        })
    flash(msg, "success")
    return redirect(request.referrer or url_for("companies.list_companies"))


# ── Save Phone Number ─────────────────────────────────────────────────────────
@companies_bp.route("/<int:cid>/save-phone", methods=["POST"])
def save_phone(cid: int):
    """Save or update the phone number for a company."""
    company = Company.query.get_or_404(cid)
    data    = request.get_json(force=True, silent=True) or request.form
    phone   = (data.get("phone_number") or "").strip() or None
    company.phone_number = phone
    company.touch()
    db.session.commit()

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "phone_number": phone})
    flash("Phone number saved.", "success")
    return redirect(url_for("companies.detail", cid=cid))


# ── Export CSV ────────────────────────────────────────────────────────────────
@companies_bp.route("/export/csv")
def export_csv():
    companies = Company.query.order_by(Company.name).all()
    output = io.StringIO()
    fields = [
        "id", "name", "website", "linkedin_url", "career_page_url", "hr_email",
        "industry", "tech_stack", "match_score", "contact_status", "last_activity_at",
        "uses_react", "uses_python", "uses_ai", "location", "company_size",
        "company_type", "phone_number", "call_status", "notes",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for c in companies:
        writer.writerow({f: getattr(c, f) for f in fields})

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=companies_export.csv"},
    )


@companies_bp.route("/export/json")
def export_json():
    companies = Company.query.order_by(Company.name).all()
    data = [c.to_dict() for c in companies]
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=companies_export.json"},
    )
