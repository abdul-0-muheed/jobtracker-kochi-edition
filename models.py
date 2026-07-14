"""
models.py — SQLAlchemy 2.0 declarative models for all 7 tables.
All timestamps are ISO-8601 TEXT in UTC. FK enforcement via PRAGMA.
"""
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── companies ──────────────────────────────────────────────────────────────────
class Company(db.Model):
    __tablename__ = "companies"

    id                = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name              = db.Column(db.Text, nullable=False, unique=True)
    website           = db.Column(db.Text)
    linkedin_url      = db.Column(db.Text)
    career_page_url   = db.Column(db.Text)
    hr_email          = db.Column(db.Text)
    founder_ceo       = db.Column(db.Text)
    founder_linkedin  = db.Column(db.Text)
    location          = db.Column(db.Text)
    company_size      = db.Column(db.Text)
    company_type      = db.Column(db.Text)   # startup | mnc | unknown
    industry          = db.Column(db.Text)
    tech_stack        = db.Column(db.Text)
    uses_react        = db.Column(db.Boolean, default=False)
    uses_python       = db.Column(db.Boolean, default=False)
    uses_ai           = db.Column(db.Boolean, default=False)
    internship_friendly = db.Column(db.Text)
    freshers_hiring   = db.Column(db.Text)
    match_score       = db.Column(db.Integer)
    notes             = db.Column(db.Text)
    phone_number      = db.Column(db.Text)          # manually entered by user
    call_status       = db.Column(db.Text, default="not_called")
    # call_status enum: not_called | called
    contact_status    = db.Column(db.Text, default="not_contacted")
    # Enum: not_contacted | emailed | replied | interviewing | offered | rejected | cold
    career_page_broken = db.Column(db.Boolean, default=False)
    last_activity_at  = db.Column(db.Text)
    created_at        = db.Column(db.Text, default=_now_iso)
    updated_at        = db.Column(db.Text, default=_now_iso, onupdate=_now_iso)

    # Relationships
    applications   = db.relationship("Application", back_populates="company", cascade="all, delete-orphan")
    contacts       = db.relationship("Contact",     back_populates="company", cascade="all, delete-orphan")
    openings       = db.relationship("Opening",     back_populates="company", cascade="all, delete-orphan")
    linkedin_events= db.relationship("LinkedInEvent", back_populates="company", cascade="all, delete-orphan")
    follow_ups     = db.relationship("FollowUp",    back_populates="company", cascade="all, delete-orphan")
    scraping_jobs  = db.relationship("ScrapingJob", back_populates="company", cascade="all, delete-orphan")

    def touch(self):
        self.last_activity_at = _now_iso()
        self.updated_at = _now_iso()

    def match_score_label(self):
        if self.match_score is None:
            return "unknown"
        if self.match_score >= 80:
            return "high"
        if self.match_score >= 50:
            return "medium"
        return "low"

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ── applications ──────────────────────────────────────────────────────────────
class Application(db.Model):
    __tablename__ = "applications"

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    role_title = db.Column(db.Text, nullable=False)
    source     = db.Column(db.Text)   # career_page | linkedin_jobs | referral | other
    source_url = db.Column(db.Text)
    applied_at = db.Column(db.Text)
    status     = db.Column(db.Text, default="applied")
    # Enum: applied | screening | interview_scheduled | interviewed | offer | rejected | withdrawn
    opening_id = db.Column(db.Integer, db.ForeignKey("openings.id"), nullable=True)
    notes      = db.Column(db.Text)
    created_at = db.Column(db.Text, default=_now_iso)

    company    = db.relationship("Company", back_populates="applications")
    follow_ups = db.relationship("FollowUp", back_populates="application", cascade="all, delete-orphan")
    opening    = db.relationship("Opening", back_populates="applications", foreign_keys=[opening_id])

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ── contacts ──────────────────────────────────────────────────────────────────
class Contact(db.Model):
    __tablename__ = "contacts"

    id                   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id           = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name                 = db.Column(db.Text, nullable=False)
    role_title           = db.Column(db.Text)
    email                = db.Column(db.Text)
    linkedin_profile_url = db.Column(db.Text, unique=True)
    linkedin_headline    = db.Column(db.Text)
    contact_type         = db.Column(db.Text)  # hr | founder | employee | recruiter | referrer
    first_contacted_at   = db.Column(db.Text)
    created_at           = db.Column(db.Text, default=_now_iso)

    company        = db.relationship("Company",      back_populates="contacts")
    linkedin_events= db.relationship("LinkedInEvent", back_populates="contact", cascade="all, delete-orphan")
    follow_ups     = db.relationship("FollowUp",     back_populates="contact",  cascade="all, delete-orphan")

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ── linkedin_events ───────────────────────────────────────────────────────────
class LinkedInEvent(db.Model):
    __tablename__ = "linkedin_events"
    __table_args__ = (
        db.UniqueConstraint("company_id", "contact_id", "event_type", "event_at", name="uq_li_event"),
    )

    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id  = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True)
    contact_id  = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=True)
    event_type  = db.Column(db.Text)
    # Enum: connection_sent | connection_accepted | message_sent | message_received | profile_view_received | post_interaction
    event_at    = db.Column(db.Text)
    raw_payload = db.Column(db.Text)   # JSON blob
    synced_at   = db.Column(db.Text, default=_now_iso)
    notes       = db.Column(db.Text)

    company = db.relationship("Company", back_populates="linkedin_events")
    contact = db.relationship("Contact", back_populates="linkedin_events")

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ── follow_ups ────────────────────────────────────────────────────────────────
class FollowUp(db.Model):
    __tablename__ = "follow_ups"

    id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id     = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), nullable=True)
    contact_id     = db.Column(db.Integer, db.ForeignKey("contacts.id"),     nullable=True)
    due_on         = db.Column(db.Text, nullable=False)   # ISO-8601 date YYYY-MM-DD
    status         = db.Column(db.Text, default="pending")
    # Enum: pending | done | snoozed | cancelled
    snooze_until   = db.Column(db.Text)
    notes          = db.Column(db.Text)
    created_at     = db.Column(db.Text, default=_now_iso)
    completed_at   = db.Column(db.Text)

    company     = db.relationship("Company",     back_populates="follow_ups")
    application = db.relationship("Application", back_populates="follow_ups")
    contact     = db.relationship("Contact",     back_populates="follow_ups")

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ── openings ──────────────────────────────────────────────────────────────────
class Opening(db.Model):
    __tablename__ = "openings"
    __table_args__ = (
        db.UniqueConstraint("company_id", "title", "url", name="uq_opening"),
    )

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id   = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    title        = db.Column(db.Text, nullable=False)
    location     = db.Column(db.Text)
    url          = db.Column(db.Text)
    source       = db.Column(db.Text)   # career_page | linkedin_jobs
    first_seen_at= db.Column(db.Text, default=_now_iso)
    last_seen_at = db.Column(db.Text, default=_now_iso)
    status       = db.Column(db.Text, default="open")  # open | closed | expired
    raw_metadata = db.Column(db.Text)   # JSON blob

    company      = db.relationship("Company",     back_populates="openings")
    applications = db.relationship("Application", back_populates="opening",
                                   foreign_keys="Application.opening_id")

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ── scraping_jobs ─────────────────────────────────────────────────────────────
class ScrapingJob(db.Model):
    __tablename__ = "scraping_jobs"

    id                = db.Column(db.Integer, primary_key=True, autoincrement=True)
    scraper_type      = db.Column(db.Text)
    # Enum: linkedin_sync | career_page_scan | linkedin_jobs_scan
    target_company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True)
    started_at        = db.Column(db.Text, default=_now_iso)
    finished_at       = db.Column(db.Text)
    status            = db.Column(db.Text, default="running")
    # Enum: running | success | failed | aborted
    items_processed   = db.Column(db.Integer, default=0)
    items_new         = db.Column(db.Integer, default=0)
    error_message     = db.Column(db.Text)
    raw_log           = db.Column(db.Text)   # JSON blob

    company = db.relationship("Company", back_populates="scraping_jobs")

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
