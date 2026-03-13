from pydantic import BaseModel
from typing import Optional


class ExperienceItem(BaseModel):
    job_title: str
    company: str
    location: Optional[str] = None
    start_date: str
    end_date: str  # "Present" or date string
    bullets: list[str]


class EducationItem(BaseModel):
    degree: str
    institution: str
    location: Optional[str] = None
    graduation_date: str
    details: Optional[list[str]] = None


class CertificationItem(BaseModel):
    name: str
    issuer: Optional[str] = None
    date: Optional[str] = None


class ResumeData(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    location: Optional[str] = None
    summary: Optional[str] = None
    skills: list[str] = []
    experience: list[ExperienceItem] = []
    education: list[EducationItem] = []
    certifications: list[CertificationItem] = []
    ats_score: Optional[int] = None          # 0-100
    matched_keywords: list[str] = []


class GenerateRequest(BaseModel):
    resume_text: str
    jd_text: str


class ScrapeRequest(BaseModel):
    url: str


class TextResponse(BaseModel):
    text: str
