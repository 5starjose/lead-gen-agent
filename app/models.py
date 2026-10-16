import datetime, json
from sqlalchemy import (Column, Integer, String, Float, Boolean, DateTime, Text,
                        ForeignKey, UniqueConstraint, Index)
from sqlalchemy.orm import relationship
from .db import Base

def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)

PIPELINE_STAGES = ["DISCOVERED","NORMALIZED","VERIFIED","RESEARCHED","SCORED","QUALIFIED","READY_FOR_OUTREACH",
                   "INSUFFICIENT_DATA","DUPLICATE","OUT_OF_AREA","INACTIVE","DO_NOT_CONTACT"]
SALES_STATUSES = ["New","Qualified","Ready to contact","Contacted","Follow-up needed","Interested",
                  "Demo scheduled","Proposal sent","Won","Lost","Do not contact"]

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    cities = Column(Text, default="[]")          # JSON list
    states = Column(Text, default="[]")
    zip_codes = Column(Text, default="[]")
    radius_miles = Column(Integer, default=15)
    industries = Column(Text, default="[]")      # JSON list of industry keys
    max_discover_per_day = Column(Integer, default=50)
    max_qualify_per_day = Column(Integer, default=25)
    min_rating = Column(Float, default=0.0)
    min_review_count = Column(Integer, default=0)
    website_status_filter = Column(String(50), default="any")
    min_lead_score = Column(Integer, default=60)
    daily_budget_usd = Column(Float, default=5.0)
    monthly_budget_usd = Column(Float, default=100.0)
    reverification_days = Column(Integer, default=30)
    schedule_time = Column(String(5), default="06:00")  # HH:MM local
    timezone = Column(String(64), default="America/Los_Angeles")
    providers = Column(Text, default='["google_places","yelp"]')
    active = Column(Boolean, default=True)
    paused = Column(Boolean, default=False)
    notify_email = Column(Boolean, default=False)
    notify_telegram = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    def j(self, field, default=None):
        try: return json.loads(getattr(self, field) or "")
        except Exception: return default if default is not None else []

class Business(Base):
    __tablename__ = "businesses"
    id = Column(Integer, primary_key=True)
    name = Column(String(300), nullable=False)
    industry = Column(String(50), index=True)
    subcategory = Column(String(120), default="")
    address = Column(String(400), default="")
    city = Column(String(120), index=True, default="")
    state = Column(String(20), default="")
    zip_code = Column(String(20), default="")
    phone = Column(String(50), default="")
    phone_normalized = Column(String(30), index=True, default="")
    website = Column(String(500), default="")
    domain = Column(String(200), index=True, default="")
    email = Column(String(200), default="")  # public business email only, never fabricated
    listing_url = Column(String(500), default="")
    social_urls = Column(Text, default="{}")
    hours = Column(Text, default="{}")
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    pipeline_stage = Column(String(40), default="DISCOVERED", index=True)
    sales_status = Column(String(40), default="New", index=True)
    lead_score = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)  # 0-1, separate from score
    score_tier = Column(String(40), default="")
    recommended_offer = Column(String(120), default="")
    sales_brief = Column(Text, default="")
    opening_line = Column(String(600), default="")
    do_not_contact = Column(Boolean, default=False, index=True)
    is_test = Column(Boolean, default=False, index=True)  # synthetic records, env-separated
    environment = Column(String(20), default="production")
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    discovered_at = Column(DateTime(timezone=True), default=utcnow)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    follow_up_date = Column(String(20), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    sources = relationship("SourceRecord", back_populates="business", cascade="all, delete-orphan")
    evidence = relationship("Evidence", back_populates="business", cascade="all, delete-orphan")
    audits = relationship("WebsiteAudit", back_populates="business", cascade="all, delete-orphan")
    scores = relationship("LeadScore", back_populates="business", cascade="all, delete-orphan")
    pipeline_events = relationship("PipelineEvent", back_populates="business", cascade="all, delete-orphan")

class SourceRecord(Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("provider","provider_id", name="uq_provider_record"),)
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    provider = Column(String(80), index=True)
    provider_id = Column(String(200), index=True, default="")
    source_url = Column(String(600), default="")
    retrieved_at = Column(DateTime(timezone=True), default=utcnow)
    fields_json = Column(Text, default="{}")
    verification_status = Column(String(40), default="retrieved")
    business = relationship("Business", back_populates="sources")

class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    kind = Column(String(80))  # opportunity|contact|reputation|digital_gap|industry_indicator
    text = Column(Text)
    source_url = Column(String(600), default="")
    strength = Column(String(20), default="potential")  # strong|potential|weak
    created_at = Column(DateTime(timezone=True), default=utcnow)
    business = relationship("Business", back_populates="evidence")

class WebsiteAudit(Base):
    __tablename__ = "website_audits"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    url = Column(String(500), default="")
    status = Column(String(30), default="not_checked")  # not_found|not_checked|accessible|inaccessible|error
    https = Column(Boolean, nullable=True)  # None = unknown/not checked
    has_contact = Column(Boolean, nullable=True)
    has_quote_form = Column(Boolean, nullable=True)
    has_booking = Column(Boolean, nullable=True)
    has_chat = Column(Boolean, nullable=True)
    has_service_info = Column(Boolean, nullable=True)
    mobile_hint = Column(String(100), default="unknown")
    issues = Column(Text, default="[]")
    checked_at = Column(DateTime(timezone=True), default=utcnow)
    business = relationship("Business", back_populates="audits")

class LeadScore(Base):
    __tablename__ = "lead_scores"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    total = Column(Integer)
    confidence = Column(Float)
    breakdown_json = Column(Text, default="{}")  # component -> points/max/explanation
    weights_json = Column(Text, default="{}")
    tier = Column(String(40), default="")
    explanation = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    business = relationship("Business", back_populates="scores")

class ResearchRun(Base):
    __tablename__ = "research_runs"
    __table_args__ = (UniqueConstraint("campaign_id","run_key", name="uq_campaign_runkey"),)
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    run_key = Column(String(80))  # e.g. scheduled-2026-10-16 or manual-<uuid> ; scheduled is idempotent per day
    job_id = Column(String(80), unique=True)
    trigger = Column(String(20), default="manual")  # scheduled|manual
    status = Column(String(20), default="running")  # running|completed|failed|partial
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    discovered = Column(Integer, default=0); new_saved = Column(Integer, default=0)
    duplicates = Column(Integer, default=0); researched = Column(Integer, default=0)
    qualified = Column(Integer, default=0); high_priority = Column(Integer, default=0)
    error_summary = Column(Text, default="")
    api_cost_usd = Column(Float, default=0.0)
    attempts = Column(Integer, default=1)

class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    from_status = Column(String(60), default=""); to_status = Column(String(60), default="")
    kind = Column(String(30), default="stage")  # stage|sales_status|note|contact
    note = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    business = relationship("Business", back_populates="pipeline_events")

class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True)
    title = Column(String(300)); due_date = Column(String(20), default="")
    done = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

class NotificationHistory(Base):
    __tablename__ = "notification_history"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("research_runs.id"), nullable=True)
    channel = Column(String(30)); recipient = Column(String(200), default="")
    status = Column(String(30), default="skipped")  # sent|skipped_not_configured|failed
    detail = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)

class ApiUsage(Base):
    __tablename__ = "api_usage"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("research_runs.id"), nullable=True)
    provider = Column(String(80)); endpoint = Column(String(200), default="")
    requests = Column(Integer, default=0); estimated_cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_usage_created", "created_at"),)

class DailyReport(Base):
    __tablename__ = "daily_reports"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("research_runs.id"), nullable=True)
    campaign_id = Column(Integer, nullable=True)
    report_json = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), default=utcnow)

class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    kind = Column(String(30), default="call")  # call|email|note
    summary = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)
