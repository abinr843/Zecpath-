"""
ATS Scoring & Matching Engine
================================
Calculates a 0-100 suitability score for a candidate against a job posting.

Scoring Weights:
    - Skills Match:      50%  (Jaccard overlap with synonym normalization)
    - Experience Match:  30%  (years vs required level)
    - Location Fit:      20%  (remote/onsite/hybrid + willingness to relocate)

Returns both the integer score and a detailed breakdown dict.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ─── Experience Level → Minimum Years Mapping ─────────────────────
EXPERIENCE_LEVEL_YEARS = {
    'entry': 0,
    'mid': 3,
    'senior': 5,
    'executive': 8,
}

# ─── Scoring Weights (must sum to 100) ────────────────────────────
WEIGHT_SKILLS = 50
WEIGHT_EXPERIENCE = 30
WEIGHT_LOCATION = 20


def _normalize_skills(raw_skills: str) -> set:
    """
    Normalize a comma-separated skills string into a set of canonical keys.
    Uses the NLP engine's SKILL_SYNONYMS for deduplication.
    """
    if not raw_skills:
        return set()

    try:
        from apps.users.utils.resume_nlp import SKILL_SYNONYMS
    except ImportError:
        SKILL_SYNONYMS = {}

    skills = set()
    for s in raw_skills.split(','):
        cleaned = s.strip().lower()
        if cleaned:
            # Map through synonyms if available, otherwise use raw
            canonical = SKILL_SYNONYMS.get(cleaned, cleaned)
            skills.add(canonical)
    return skills


def _score_skills(candidate_skills: set, job_skills: set) -> dict:
    """
    Calculate the skills overlap score.
    Returns a dict with the raw score (0-100), matched/missing lists.
    """
    if not job_skills:
        # If the job doesn't list required skills, give full marks
        return {
            'score': 100,
            'matched': sorted(candidate_skills),
            'missing': [],
            'total_required': 0,
            'total_matched': len(candidate_skills),
        }

    matched = candidate_skills & job_skills
    missing = job_skills - candidate_skills

    overlap_pct = (len(matched) / len(job_skills)) * 100 if job_skills else 0

    return {
        'score': round(overlap_pct),
        'matched': sorted(matched),
        'missing': sorted(missing),
        'total_required': len(job_skills),
        'total_matched': len(matched),
    }


def _score_experience(candidate_years: float, job_level: str) -> dict:
    """
    Score candidate's experience years against the job's required level.
    Full marks if they meet/exceed. Partial for close. 0 for way under.
    """
    required_years = EXPERIENCE_LEVEL_YEARS.get(job_level, 0)

    if required_years == 0:
        # Entry level or unknown — anyone qualifies
        score = 100
    elif candidate_years >= required_years:
        # Meets or exceeds — full score
        score = 100
    elif candidate_years >= required_years - 1:
        # Within 1 year — partial credit (75%)
        score = 75
    elif candidate_years >= required_years - 2:
        # Within 2 years — lower partial (50%)
        score = 50
    else:
        # Significantly under-qualified
        score = max(0, int((candidate_years / required_years) * 100))

    return {
        'score': score,
        'candidate_years': candidate_years,
        'required_level': job_level,
        'required_years': required_years,
    }


def _score_location(candidate, job) -> dict:
    """
    Score location compatibility.
    - Remote jobs: always 100%
    - Onsite/hybrid: check location match or willingness to relocate
    """
    job_location_type = getattr(job, 'location_type', 'onsite')
    job_location = (getattr(job, 'location', '') or '').strip().lower()
    candidate_location = (getattr(candidate, 'location', '') or '').strip().lower()
    willing_to_relocate = getattr(candidate, 'willing_to_relocate', False)

    if job_location_type == 'remote':
        return {'score': 100, 'reason': 'Remote job — location not a factor'}

    if not job_location:
        return {'score': 100, 'reason': 'Job has no location specified'}

    if not candidate_location:
        if willing_to_relocate:
            return {'score': 80, 'reason': 'Candidate location unknown but willing to relocate'}
        return {'score': 40, 'reason': 'Candidate location unknown'}

    # Check for partial match (e.g., "Adoor, Kerala" matches "Kerala")
    location_match = False
    job_parts = [p.strip() for p in re.split(r'[,|;]', job_location)]
    candidate_parts = [p.strip() for p in re.split(r'[,|;]', candidate_location)]

    for jp in job_parts:
        for cp in candidate_parts:
            if jp and cp and (jp in cp or cp in jp):
                location_match = True
                break

    if location_match:
        return {'score': 100, 'reason': 'Location match'}

    if willing_to_relocate:
        return {'score': 70, 'reason': 'Different location but willing to relocate'}

    if job_location_type == 'hybrid':
        return {'score': 50, 'reason': 'Hybrid role — partial location flexibility'}

    return {'score': 20, 'reason': 'Location mismatch, not willing to relocate'}


def calculate_ats_score(candidate, job) -> tuple:
    """
    Main ATS scoring function.

    Args:
        candidate: Candidate model instance
        job: Job model instance

    Returns:
        tuple: (overall_score: int, details: dict)
    """
    # Normalize skills for comparison
    candidate_skills = _normalize_skills(getattr(candidate, 'skills', ''))
    job_skills = _normalize_skills(getattr(job, 'skills_required', ''))
    candidate_years = getattr(candidate, 'experience_years', 0) or 0

    # Calculate each component
    skills_result = _score_skills(candidate_skills, job_skills)
    experience_result = _score_experience(candidate_years, job.experience_level)
    location_result = _score_location(candidate, job)

    # Weighted aggregate
    weighted_skills = (skills_result['score'] / 100) * WEIGHT_SKILLS
    weighted_experience = (experience_result['score'] / 100) * WEIGHT_EXPERIENCE
    weighted_location = (location_result['score'] / 100) * WEIGHT_LOCATION

    overall_score = round(weighted_skills + weighted_experience + weighted_location)
    overall_score = max(0, min(100, overall_score))  # clamp

    details = {
        'overall_score': overall_score,
        'weights': {
            'skills': WEIGHT_SKILLS,
            'experience': WEIGHT_EXPERIENCE,
            'location': WEIGHT_LOCATION,
        },
        'skills': skills_result,
        'experience': experience_result,
        'location': location_result,
    }

    logger.info(
        "ATS Score: %s vs '%s' => %d%% (skills=%d, exp=%d, loc=%d)",
        candidate.user.email, job.title, overall_score,
        skills_result['score'], experience_result['score'], location_result['score'],
    )

    return overall_score, details
