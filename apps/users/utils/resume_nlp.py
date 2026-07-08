"""
Resume NLP Engine (v4) — Hybrid spaCy + Regex (Bug Fixes)
===========================================================
Production-grade structured data extraction using:
    - Regex-bounded section detection with expanded anchors
    - spaCy NER for context-aware entity recognition (ORG, DATE)
    - Semantic skill mapping for synonym normalization
    - Strict JSON schema output for ML-ready data

Bug fixes in v4:
    - Company Leak: action verb filter + bullet trim + section restriction
    - Location Leak: constrained regex excludes job title words
    - Education Noise: section-first extraction + clean context grabbing
    - Global fallbacks when bounded sections aren't found

Output schema:
    {
        "skills": ["python", "django", ...],
        "experience_years": 3,
        "education": "Bachelor of Computer Application",
        "inferred_role": "Full Stack Developer",
        "details": { ... }
    }
"""

import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to load spaCy — gracefully degrade if unavailable
_nlp = None
try:
    import spacy
    try:
        _nlp = spacy.load("en_core_web_sm")
        logger.info("spaCy model 'en_core_web_sm' loaded successfully.")
    except OSError:
        logger.warning(
            "spaCy model 'en_core_web_sm' not found. "
            "Run: python -m spacy download en_core_web_sm"
        )
except ImportError:
    logger.warning("spaCy not installed. NER features disabled.")


# ═══════════════════════════════════════════════════════════════════════════
# SKILL LIBRARY + SYNONYM NORMALIZATION MAP
# ═══════════════════════════════════════════════════════════════════════════

# Maps every variation → canonical master key
SKILL_SYNONYMS = {
    # React ecosystem
    'react': 'react', 'reactjs': 'react', 'react.js': 'react',
    'react native': 'react native',

    # Vue ecosystem
    'vue': 'vue', 'vuejs': 'vue', 'vue.js': 'vue',

    # Angular
    'angular': 'angular', 'angularjs': 'angular',

    # Node
    'node.js': 'node.js', 'nodejs': 'node.js',

    # Next.js
    'next.js': 'next.js', 'nextjs': 'next.js',

    # Nuxt
    'nuxt': 'nuxt', 'nuxtjs': 'nuxt', 'nuxt.js': 'nuxt',

    # Express
    'express': 'express', 'expressjs': 'express', 'express.js': 'express',

    # Python frameworks
    'django': 'django', 'flask': 'flask', 'fastapi': 'fastapi',

    # Databases
    'postgresql': 'postgresql', 'postgres': 'postgresql',
    'mongodb': 'mongodb', 'mongo': 'mongodb',
    'mysql': 'mysql', 'mariadb': 'mariadb',
    'sqlite': 'sqlite', 'redis': 'redis',
    'elasticsearch': 'elasticsearch',
    'cassandra': 'cassandra', 'dynamodb': 'dynamodb',
    'firebase': 'firebase', 'neo4j': 'neo4j',
    'oracle': 'oracle', 'couchdb': 'couchdb', 'influxdb': 'influxdb',
    'sql': 'sql',

    # Cloud
    'aws': 'aws', 'amazon web services': 'aws',
    'azure': 'azure', 'microsoft azure': 'azure',
    'gcp': 'gcp', 'google cloud': 'gcp', 'google cloud platform': 'gcp',

    # DevOps
    'docker': 'docker', 'kubernetes': 'kubernetes', 'k8s': 'kubernetes',
    'terraform': 'terraform', 'ansible': 'ansible', 'jenkins': 'jenkins',
    'ci/cd': 'ci/cd', 'github actions': 'github actions',
    'gitlab ci': 'gitlab ci', 'circleci': 'circleci',

    # Languages
    'python': 'python', 'java': 'java', 'javascript': 'javascript',
    'typescript': 'typescript', 'c++': 'c++', 'c#': 'c#',
    'ruby': 'ruby', 'go': 'go', 'golang': 'go',
    'rust': 'rust', 'swift': 'swift', 'kotlin': 'kotlin',
    'php': 'php', 'scala': 'scala', 'r': 'r',
    'perl': 'perl', 'matlab': 'matlab', 'dart': 'dart',
    'lua': 'lua', 'shell': 'shell', 'bash': 'bash',
    'powershell': 'powershell', 'objective-c': 'objective-c',
    'haskell': 'haskell', 'elixir': 'elixir', 'clojure': 'clojure',

    # Data Science / ML
    'machine learning': 'machine learning', 'deep learning': 'deep learning',
    'natural language processing': 'nlp', 'nlp': 'nlp',
    'computer vision': 'computer vision',
    'tensorflow': 'tensorflow', 'pytorch': 'pytorch', 'keras': 'keras',
    'scikit-learn': 'scikit-learn', 'sklearn': 'scikit-learn',
    'pandas': 'pandas', 'numpy': 'numpy', 'scipy': 'scipy',
    'matplotlib': 'matplotlib', 'seaborn': 'seaborn',
    'opencv': 'opencv', 'spacy': 'spacy',
    'hugging face': 'hugging face', 'transformers': 'transformers',
    'data science': 'data science', 'data analysis': 'data analysis',
    'data engineering': 'data engineering',
    'artificial intelligence': 'artificial intelligence',

    # Tools
    'git': 'git', 'github': 'github', 'gitlab': 'gitlab',
    'bitbucket': 'bitbucket', 'jira': 'jira', 'confluence': 'confluence',
    'figma': 'figma', 'postman': 'postman', 'swagger': 'swagger',
    'graphql': 'graphql', 'grpc': 'grpc',
    'webpack': 'webpack', 'vite': 'vite', 'babel': 'babel',

    # REST API variants → single key
    'rest api': 'rest api', 'rest apis': 'rest api',
    'restful api': 'rest api', 'restful apis': 'rest api',
    'rest': 'rest api', 'restful': 'rest api',

    # Mobile
    'flutter': 'flutter', 'android': 'android', 'ios': 'ios',
    'swiftui': 'swiftui', 'xamarin': 'xamarin', 'ionic': 'ionic',

    # Testing
    'jest': 'jest', 'mocha': 'mocha', 'cypress': 'cypress',
    'selenium': 'selenium', 'playwright': 'playwright',
    'pytest': 'pytest', 'unittest': 'unittest', 'junit': 'junit',

    # Data / Messaging
    'kafka': 'kafka', 'rabbitmq': 'rabbitmq', 'celery': 'celery',
    'airflow': 'airflow', 'spark': 'spark', 'hadoop': 'hadoop',
    'snowflake': 'snowflake', 'databricks': 'databricks',
    'tableau': 'tableau', 'power bi': 'power bi',

    # Security
    'oauth': 'oauth', 'jwt': 'jwt', 'ssl': 'ssl', 'tls': 'tls',

    # Methodologies
    'agile': 'agile', 'scrum': 'scrum', 'kanban': 'kanban',
    'devops': 'devops', 'microservices': 'microservices',
    'design patterns': 'design patterns', 'oop': 'oop', 'tdd': 'tdd',

    # Frontend
    'html': 'html', 'css': 'css', 'sass': 'sass', 'less': 'less',
    'tailwindcss': 'tailwind css', 'tailwind': 'tailwind css',
    'bootstrap': 'bootstrap', 'material ui': 'material ui',
    'chakra ui': 'chakra ui',

    # Web frameworks
    'spring': 'spring', 'spring boot': 'spring boot',
    'rails': 'ruby on rails', 'ruby on rails': 'ruby on rails',
    'laravel': 'laravel', 'asp.net': 'asp.net', '.net': '.net', 'deno': 'deno',
    'svelte': 'svelte',

    # Servers
    'nginx': 'nginx', 'apache': 'apache', 'linux': 'linux', 'unix': 'unix',
    'heroku': 'heroku', 'vercel': 'vercel', 'netlify': 'netlify',
    'cloudflare': 'cloudflare', 'digitalocean': 'digitalocean',

    # CMS / Other
    'wordpress': 'wordpress', 'shopify': 'shopify',
    'blockchain': 'blockchain', 'solidity': 'solidity', 'web3': 'web3',
    'three.js': 'three.js', 'webgl': 'webgl',
}

# Build lookup structures from the synonym map
_ALL_SKILL_KEYS = set(SKILL_SYNONYMS.keys())
_MULTI_WORD_SKILLS = sorted(
    [s for s in _ALL_SKILL_KEYS if len(s.split()) > 1 or '.' in s or '/' in s],
    key=len, reverse=True,
)
_SINGLE_WORD_SKILLS = {
    s for s in _ALL_SKILL_KEYS
    if len(s.split()) == 1 and '.' not in s and '/' not in s
}
_AMBIGUOUS_SKILLS = {'r', 'go'}  # require extra context
_SKILL_MIN_LENGTH = 2


# ═══════════════════════════════════════════════════════════════════════════
# ROLES LIBRARY
# ═══════════════════════════════════════════════════════════════════════════

ROLES_LIBRARY = sorted([
    'software engineer', 'software developer', 'web developer',
    'frontend developer', 'front-end developer', 'front end developer',
    'backend developer', 'back-end developer', 'back end developer',
    'full stack developer', 'full-stack developer', 'fullstack developer',
    'mobile developer', 'ios developer', 'android developer',
    'devops engineer', 'site reliability engineer',
    'cloud engineer', 'platform engineer', 'infrastructure engineer',
    'qa engineer', 'quality assurance engineer', 'test engineer',
    'automation engineer', 'systems engineer',
    'data scientist', 'data analyst', 'data engineer',
    'machine learning engineer', 'ml engineer', 'ai engineer',
    'business analyst', 'business intelligence analyst',
    'ui designer', 'ux designer', 'ui/ux designer', 'product designer',
    'graphic designer', 'visual designer',
    'engineering manager', 'technical lead', 'tech lead',
    'team lead', 'project manager', 'product manager',
    'program manager', 'scrum master', 'cto', 'ceo',
    'vp of engineering', 'director of engineering',
    'head of engineering', 'head of product',
    'consultant', 'freelancer', 'intern',
    'research scientist', 'research engineer',
    'solution architect', 'technical architect', 'enterprise architect',
    'database administrator', 'network engineer',
    'security engineer', 'cybersecurity analyst',
    'python developer', 'java developer', 'django developer',
    'react developer', 'node.js developer',
    'junior developer', 'senior developer', 'lead developer',
    'junior software engineer', 'senior software engineer',
    'junior python developer', 'senior python developer',
], key=len, reverse=True)

# Synonym normalization for roles
ROLE_SYNONYMS = {
    'front-end developer': 'frontend developer',
    'front end developer': 'frontend developer',
    'back-end developer': 'backend developer',
    'back end developer': 'backend developer',
    'full-stack developer': 'full stack developer',
    'fullstack developer': 'full stack developer',
}


# ═══════════════════════════════════════════════════════════════════════════
# SECTION DETECTION (v2 — expanded anchors + regex bounding)
# ═══════════════════════════════════════════════════════════════════════════

# Expanded anchor patterns for each section type
_SECTION_ANCHORS = {
    'experience': re.compile(
        r'(?:^|\n)\s*'
        r'(?:EXPERIENCE|WORK\s*HISTORY|EMPLOYMENT(?:\s*HISTORY)?|'
        r'PROFESSIONAL\s*EXPERIENCE|CAREER(?:\s*HISTORY)?|'
        r'WORK\s*EXPERIENCE|JOB\s*HISTORY|INTERNSHIP[S]?)'
        r'\s*\n',
        re.IGNORECASE,
    ),
    'education': re.compile(
        r'(?:^|\n)\s*'
        r'(?:EDUCATION|ACADEMIC(?:\s*BACKGROUND)?|QUALIFICATIONS|'
        r'DEGREES?|SCHOLASTIC|EDUCATIONAL\s*BACKGROUND|'
        r'ACADEMIC\s*QUALIFICATIONS|ACADEMIC\s*DETAILS)'
        r'\s*\n',
        re.IGNORECASE,
    ),
    'skills': re.compile(
        r'(?:^|\n)\s*'
        r'(?:SKILLS|TECHNICAL\s*SKILLS|CORE\s*COMPETENCIES|'
        r'TECHNOLOGIES|PROFICIENCIES|TECH\s*STACK|'
        r'KEY\s*SKILLS|AREAS\s*OF\s*EXPERTISE)'
        r'\s*\n',
        re.IGNORECASE,
    ),
    'summary': re.compile(
        r'(?:^|\n)\s*'
        r'(?:SUMMARY|PROFILE|ABOUT\s*ME|OBJECTIVE|'
        r'PROFESSIONAL\s*SUMMARY|CAREER\s*SUMMARY|'
        r'CAREER\s*OBJECTIVE|PERSONAL\s*STATEMENT)'
        r'\s*\n',
        re.IGNORECASE,
    ),
    'projects': re.compile(
        r'(?:^|\n)\s*'
        r'(?:PROJECTS|PERSONAL\s*PROJECTS|KEY\s*PROJECTS|'
        r'ACADEMIC\s*PROJECTS|NOTABLE\s*PROJECTS)'
        r'\s*\n',
        re.IGNORECASE,
    ),
    'certifications': re.compile(
        r'(?:^|\n)\s*'
        r'(?:CERTIFICATIONS?|LICENSES?|CREDENTIALS?|'
        r'COURSES?|TRAINING|AWARDS?(?:\s*&\s*ACHIEVEMENTS?)?)'
        r'\s*\n',
        re.IGNORECASE,
    ),
}

# Combined pattern to find ANY section header (used to find boundaries)
_ANY_SECTION_HEADER = re.compile(
    r'(?:^|\n)\s*(?:'
    r'EXPERIENCE|WORK\s*HISTORY|EMPLOYMENT(?:\s*HISTORY)?|'
    r'PROFESSIONAL\s*EXPERIENCE|CAREER(?:\s*HISTORY)?|'
    r'WORK\s*EXPERIENCE|JOB\s*HISTORY|INTERNSHIP[S]?|'
    r'EDUCATION|ACADEMIC(?:\s*BACKGROUND)?|QUALIFICATIONS|'
    r'DEGREES?|SCHOLASTIC|EDUCATIONAL\s*BACKGROUND|'
    r'ACADEMIC\s*QUALIFICATIONS|ACADEMIC\s*DETAILS|'
    r'SKILLS|TECHNICAL\s*SKILLS|CORE\s*COMPETENCIES|'
    r'TECHNOLOGIES|PROFICIENCIES|TECH\s*STACK|'
    r'KEY\s*SKILLS|AREAS\s*OF\s*EXPERTISE|'
    r'SUMMARY|PROFILE|ABOUT\s*ME|OBJECTIVE|'
    r'PROFESSIONAL\s*SUMMARY|CAREER\s*SUMMARY|'
    r'CAREER\s*OBJECTIVE|PERSONAL\s*STATEMENT|'
    r'PROJECTS|PERSONAL\s*PROJECTS|KEY\s*PROJECTS|'
    r'ACADEMIC\s*PROJECTS|NOTABLE\s*PROJECTS|'
    r'CERTIFICATIONS?|LICENSES?|CREDENTIALS?|'
    r'COURSES?|TRAINING|AWARDS?(?:\s*&\s*ACHIEVEMENTS?)?|'
    r'REFERENCES?|HOBBIES|INTERESTS|LANGUAGES|'
    r'PUBLICATIONS?|VOLUNTEER'
    r')\s*\n',
    re.IGNORECASE,
)


def _detect_sections(text: str) -> dict:
    """
    Detect and extract resume sections using regex bounding.

    Strategy:
      1. Find all section header positions using _ANY_SECTION_HEADER.
      2. For each known section type, find its start anchor.
      3. The section content runs from after the header to the next header.
      4. Store results in a dict: { section_name: "text content..." }
      5. '_header' contains text before any recognized section.
      6. '_full' contains the entire text.
    """
    sections = {'_full': text}

    # Find ALL header positions in the text
    header_positions = []
    for match in _ANY_SECTION_HEADER.finditer(text):
        header_positions.append(match.end())
    header_positions.append(len(text))  # sentinel for the last section

    # For each known section type, find its bounded content
    for section_name, pattern in _SECTION_ANCHORS.items():
        match = pattern.search(text)
        if match:
            section_start = match.end()

            # Find the NEXT header after this section starts
            section_end = len(text)
            for pos in sorted(header_positions):
                if pos > section_start + 5:  # must be meaningfully after
                    section_end = pos
                    # Back up to the start of the header line
                    header_line_start = text.rfind('\n', 0, section_end)
                    if header_line_start > section_start:
                        section_end = header_line_start
                    break

            content = text[section_start:section_end].strip()
            if content:
                sections[section_name] = content

    # Extract the header/top portion (before any section)
    first_header_pos = len(text)
    for match in _ANY_SECTION_HEADER.finditer(text):
        first_header_pos = match.start()
        break
    sections['_header'] = text[:first_header_pos].strip()

    return sections


# ═══════════════════════════════════════════════════════════════════════════
# TOKENIZATION
# ═══════════════════════════════════════════════════════════════════════════

def tokenize(text: str) -> list:
    """Lowercase word tokens, keeping special chars for skills like C#."""
    return re.findall(r'[a-zA-Z0-9#+./-]+', text.lower())


# ═══════════════════════════════════════════════════════════════════════════
# SKILL EXTRACTION (with synonym normalization)
# ═══════════════════════════════════════════════════════════════════════════

def extract_skills(text: str, sections: dict = None) -> list:
    """
    Extract and normalize skills using the synonym map.
    Returns a deduplicated list of canonical skill names.
    """
    search_text = text.lower()
    raw_matches = set()

    # Pass 1: Multi-word / dotted skills (longest first, greedy)
    for skill in _MULTI_WORD_SKILLS:
        escaped = re.escape(skill)
        if re.search(r'(?:^|[\s,;|•·\-(])' + escaped + r'(?:[\s,;|•·\-)]|$)', search_text):
            raw_matches.add(skill)

    # Pass 2: Single-word skills via word-boundary token matching
    tokens = set(tokenize(text))
    for skill in _SINGLE_WORD_SKILLS:
        if len(skill) < _SKILL_MIN_LENGTH:
            continue
        if skill in _AMBIGUOUS_SKILLS:
            # Require standalone uppercase appearance
            if not re.search(r'(?:^|[\s,;|•])' + re.escape(skill.upper()) + r'(?:[\s,;|•]|$)', text):
                continue
        if skill in tokens:
            raw_matches.add(skill)

    # Normalize through synonym map → canonical keys
    canonical = set()
    for match in raw_matches:
        master = SKILL_SYNONYMS.get(match, match)
        canonical.add(master)

    return sorted(canonical)


# ═══════════════════════════════════════════════════════════════════════════
# spaCy NER HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _extract_spacy_entities(text: str) -> dict:
    """
    Run spaCy NER on the text and group entities by label.
    Returns: { 'ORG': [...], 'DATE': [...], 'PERSON': [...], ... }
    """
    if _nlp is None:
        return {}

    max_len = 100000
    doc = _nlp(text[:max_len])

    entities = {}
    for ent in doc.ents:
        label = ent.label_
        entities.setdefault(label, []).append({
            'text': ent.text.strip(),
            'start': ent.start_char,
            'end': ent.end_char,
        })

    return entities


# ═══════════════════════════════════════════════════════════════════════════
# COMPANY LEAK FIX — Filters for spaCy ORG entities
# ═══════════════════════════════════════════════════════════════════════════

# Action verbs commonly starting bullet points — these are NOT company names
_ACTION_VERBS = {
    'built', 'developed', 'created', 'designed', 'implemented', 'managed',
    'led', 'architected', 'deployed', 'optimized', 'maintained', 'wrote',
    'collaborated', 'integrated', 'automated', 'established', 'refactored',
    'configured', 'delivered', 'launched', 'improved', 'reduced', 'increased',
    'achieved', 'analyzed', 'coordinated', 'facilitated', 'generated',
    'handled', 'initiated', 'monitored', 'organized', 'performed',
    'prepared', 'processed', 'provided', 'resolved', 'reviewed',
    'streamlined', 'supervised', 'supported', 'tested', 'trained',
    'updated', 'utilized', 'worked', 'assisted', 'contributed',
    'conducted', 'executed', 'formulated', 'mentored', 'negotiated',
    'spearheaded', 'transformed', 'ensured', 'fostered',
}

# Extended blacklist: tech stack terms that spaCy often flags as ORG
_ORG_BLACKLIST = {
    # Programming languages / frameworks
    'python', 'java', 'javascript', 'django', 'react', 'html', 'css',
    'sql', 'rest', 'api', 'git', 'github', 'gitlab', 'docker',
    'aws', 'gcp', 'azure', 'linux', 'windows', 'agile', 'scrum',
    'celery', 'redis', 'mongodb', 'postgresql', 'mysql', 'sqlite',
    'flask', 'fastapi', 'express', 'angular', 'vue', 'node.js',
    'typescript', 'kubernetes', 'terraform', 'jenkins', 'nginx',
    'kafka', 'rabbitmq', 'elasticsearch', 'graphql', 'bootstrap',
    'tailwind', 'sass', 'webpack', 'vite', 'pytest', 'selenium',
    'postman', 'swagger', 'figma', 'jira', 'confluence', 'heroku',
    'vercel', 'netlify', 'firebase', 'stripe', 'razorpay', 'paypal',
    'jquery', 'next.js', 'nuxt', 'spring', 'laravel',
    # Education terms
    'bachelor', 'master', 'phd', 'bca', 'btech', 'mca', 'mba',
    # Generic
    'intern', 'internship', 'project', 'team', 'production',
}

# Bullet point prefixes to strip before analysis
_BULLET_CHARS = re.compile(r'^[\s•\-*▪▸►◆→]+')


def _is_valid_company(org_text: str) -> bool:
    """
    Determine if a spaCy ORG entity is actually a company name.
    Returns False for action verbs, tech stack terms, and other noise.
    """
    cleaned = _BULLET_CHARS.sub('', org_text).strip()
    if not cleaned or len(cleaned) < 2:
        return False

    lower = cleaned.lower()

    # Check against blacklist
    if lower in _ORG_BLACKLIST:
        return False

    # Check if it starts with an action verb (bullet point leak)
    first_word = lower.split()[0] if lower.split() else ''
    if first_word in _ACTION_VERBS:
        return False

    # Reject if it looks like a sentence fragment (> 6 words)
    if len(lower.split()) > 6:
        return False

    # Reject if it contains common non-company patterns
    if re.search(r'@|\.com$|\.org$|\.net$|\.edu$', lower):
        return False

    # Reject if it's a single common English word (not a proper noun)
    _COMMON_WORDS = {
        'the', 'and', 'for', 'with', 'from', 'this', 'that', 'have',
        'been', 'will', 'more', 'also', 'such', 'real', 'time', 'based',
        'using', 'used', 'experience', 'strong', 'foundation', 'secure',
        'payment', 'processing', 'performance', 'database', 'application',
        'applications', 'systems', 'services', 'features',
    }
    if lower in _COMMON_WORDS:
        return False

    return True


# ═══════════════════════════════════════════════════════════════════════════
# EXPERIENCE EXTRACTION (Regex + spaCy hybrid)
# ═══════════════════════════════════════════════════════════════════════════

def extract_experience(text: str, sections: dict = None) -> dict:
    """
    Hybrid experience extraction.
    - Regex: explicit mentions ("5 years experience") and date ranges.
    - spaCy: ORG entities for company names (restricted to experience section).
    """
    search_text = text.lower()
    result = {
        'explicit_mentions': [],
        'date_ranges': [],
        'companies': [],
        'estimated_total': 0,
    }

    # ─── Regex: explicit year mentions ────────────────────────────
    explicit_patterns = [
        r'(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s*(?:and\s*)?(\d{1,2})\s*(?:months?|mos?))?[\s\w]*(?:of\s+)?(?:experience|exp)',
        r'(?:experience|exp)\s*(?:of\s+)?(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s*(?:and\s*)?(\d{1,2})\s*(?:months?|mos?))?',
        r'(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s*(?:and\s*)?(\d{1,2})\s*(?:months?|mos?))?\s+(?:in|of|as)',
    ]

    seen_years = set()
    for pattern in explicit_patterns:
        for match in re.finditer(pattern, search_text):
            try:
                base_years = float(match.group(1))
                months = int(match.group(2)) if match.group(2) else 0
                total_years = round(base_years + (months / 12.0), 1)
            except ValueError:
                continue
                
            if 0 < total_years <= 50 and total_years not in seen_years:
                seen_years.add(total_years)
                start = max(0, match.start() - 40)
                end = min(len(text), match.end() + 40)
                result['explicit_mentions'].append({
                    'years': total_years,
                    'context': text[start:end].strip(),
                })

    # ─── Regex: date ranges (prefer experience section) ─────────────
    # FIX: Search within experience section first to avoid counting
    # education dates (e.g., "2019 - 2022" for university) as work exp.
    date_search_text = search_text
    if sections and 'experience' in sections:
        date_search_text = sections['experience'].lower()
    date_range_pattern = (
        r'(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+)?'
        r'(\d{4})'
        r'\s*[-–—to]+\s*'
        r'(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+)?'
        r'(\d{4}|present|current|now|ongoing)'
    )

    current_year = datetime.now().year
    seen_ranges = set()

    for match in re.finditer(date_range_pattern, date_search_text):
        start_year = int(match.group(1))
        end_str = match.group(2)
        end_year = current_year if end_str in ('present', 'current', 'now', 'ongoing') else int(end_str)

        if 1970 <= start_year <= current_year and start_year <= end_year <= current_year + 1:
            diff = float(end_year - start_year)
            key = (start_year, end_year)
            if diff > 0 and key not in seen_ranges:
                seen_ranges.add(key)
                result['date_ranges'].append({
                    'start': start_year,
                    'end': end_str if end_str in ('present', 'current', 'now', 'ongoing') else end_year,
                    'years': diff,
                })

    # ─── spaCy: ORG entities (RESTRICTED to experience section) ───
    # FIX: Only run NER on the experience section to prevent leaking
    # bullet points and tech stack words from other sections.
    experience_text = text  # default to full text
    if sections and 'experience' in sections:
        experience_text = sections['experience']
    # If no bounded experience section, also try _header + _full (fallback)

    spacy_ents = _extract_spacy_entities(experience_text)

    if 'ORG' in spacy_ents:
        seen_orgs = set()
        for ent in spacy_ents['ORG']:
            org_name = ent['text']
            org_lower = org_name.lower().strip()

            # Apply the full validation pipeline
            if not _is_valid_company(org_name):
                continue

            if org_lower not in seen_orgs:
                seen_orgs.add(org_lower)
                result['companies'].append(org_name)

    # ─── Estimate total years ─────────────────────────────────────
    if result['explicit_mentions']:
        result['estimated_total'] = max(m['years'] for m in result['explicit_mentions'])
    elif result['date_ranges']:
        all_starts = [r['start'] for r in result['date_ranges']]
        all_ends = [
            r['end'] if isinstance(r['end'], int) else current_year
            for r in result['date_ranges']
        ]
        if all_starts and all_ends:
            result['estimated_total'] = float(max(all_ends) - min(all_starts))

    return result


# ═══════════════════════════════════════════════════════════════════════════
# EDUCATION EXTRACTION (strict matching, v2 — fixed noise)
# ═══════════════════════════════════════════════════════════════════════════

# Full-form degree patterns (case-insensitive, always safe)
_FULL_DEGREE_PATTERNS = [
    r"doctor\s+of\s+philosophy",
    r"master(?:'?s?)?\s+(?:of\s+)?(?:science|arts|engineering|business\s+administration|computer\s+science|technology|information\s+technology|commerce)",
    r"bachelor(?:'?s?)?\s+(?:of\s+)?(?:science|arts|engineering|technology|computer\s+science|business\s+administration|information\s+technology|commerce|computer\s+application[s]?)",
    r"associate(?:'?s?)?\s+(?:of\s+)?(?:science|arts)",
    r"diploma\s+in\s+\w[\w\s]{2,30}",
    r"high\s+school\s+diploma",
    r"certificate\s+in\s+\w[\w\s]{2,30}",
]

# Abbreviated patterns — STRICT: require dots OR uppercase
_ABBREV_DEGREE_PATTERNS = [
    r"Ph\.?\s*D\.?",
    r"M\.S\.?", r"M\.A\.?", r"M\.B\.A\.?", r"M\.Tech\.?", r"M\.E\.?", r"M\.C\.A\.?", r"M\.Sc\.?",
    r"MS(?=\s+in\s)", r"MA(?=\s+in\s)", r"MBA",
    r"B\.S\.?", r"B\.A\.?", r"B\.E\.?", r"B\.Tech\.?", r"B\.C\.A\.?", r"B\.B\.A\.?", r"B\.Sc\.?", r"B\.Com\.?",
    r"BS(?=\s+in\s)", r"BA(?=\s+in\s)", r"BCA", r"BBA", r"BTech",
]

# Degree ranking for "pick the highest"
_DEGREE_RANK = {
    'phd': 5, 'doctor': 5,
    'master': 4, 'mba': 4, 'ms': 4, 'ma': 4, 'mtech': 4, 'mca': 4, 'msc': 4, 'me': 4,
    'bachelor': 3, 'bs': 3, 'ba': 3, 'be': 3, 'btech': 3, 'bca': 3, 'bba': 3, 'bsc': 3, 'bcom': 3,
    'associate': 2,
    'diploma': 1, 'certificate': 1,
    'high school': 0,
}

# Noise words that should NOT appear in education context
_EDUCATION_NOISE_PATTERNS = re.compile(
    r'@|developer|engineer|manager|designer|analyst|architect|'
    r'intern\b|freelancer|consultant|lead\b|senior|junior|'
    r'\+\d{1,3}\s?\d|\.com\b|\.org\b|gmail|yahoo|hotmail|'
    r'linkedin\.com|github\.com',
    re.IGNORECASE,
)


def extract_education(text: str, sections: dict = None) -> list:
    """
    Extract education entries with strict matching.

    Strategy:
      1. Search ONLY within the Education section if found.
      2. If no Education section, fall back to global text with strict validation.
      3. Context lines are filtered to exclude noise (header/title/contact info).
    """
    results = []
    seen_degrees = set()
    used_fallback = False

    # Prefer bounded education section
    search_text = None
    if sections and 'education' in sections and sections['education'].strip():
        search_text = sections['education']
    else:
        # Fallback to global text
        search_text = text
        used_fallback = True

    # Pass 1: Full-form degree patterns
    for pattern in _FULL_DEGREE_PATTERNS:
        for match in re.finditer(pattern, search_text, re.IGNORECASE):
            degree = match.group(0).strip()
            degree_key = degree.lower()
            if degree_key not in seen_degrees:
                seen_degrees.add(degree_key)
                context = _get_clean_context(
                    search_text, match.start(), match.end(), strict=used_fallback
                )
                results.append({'degree': degree, 'context': context})

    # Pass 2: Abbreviated patterns (case-SENSITIVE)
    for pattern in _ABBREV_DEGREE_PATTERNS:
        full_pattern = r'(?:^|(?<=[\s,;(]))' + pattern + r'(?=[\s,;).\-]|$)'
        for match in re.finditer(full_pattern, search_text, re.MULTILINE):
            degree = match.group(0).strip()
            degree_key = degree.lower().replace('.', '').replace(' ', '')
            if degree_key in seen_degrees or len(degree_key) < 2:
                continue
            seen_degrees.add(degree_key)
            context = _get_clean_context(
                search_text, match.start(), match.end(), strict=used_fallback
            )
            results.append({'degree': degree, 'context': context})

    return results


def _get_best_education(education_list: list) -> str:
    """Pick the highest-ranked degree as a single string."""
    if not education_list:
        return ''

    best = education_list[0]
    best_rank = -1

    for edu in education_list:
        degree_lower = edu['degree'].lower().replace('.', '').replace(' ', '')
        rank = 0
        for key, value in _DEGREE_RANK.items():
            if key in degree_lower:
                rank = max(rank, value)
        if rank > best_rank:
            best_rank = rank
            best = edu

    return best.get('context', best['degree'])


def _get_clean_context(
    text: str, match_start: int, match_end: int, strict: bool = False
) -> str:
    """
    Get the full line containing the match.
    FIX: Applies noise filtering to prevent header/title/contact info leaks.

    Args:
        text: the text being searched (could be a section or full text)
        match_start: character offset of the match start
        match_end: character offset of the match end
        strict: if True (fallback mode), apply extra noise filtering
    """
    line_start = text.rfind('\n', 0, match_start) + 1
    line_end = text.find('\n', match_end)
    if line_end == -1:
        line_end = len(text)

    context = text[line_start:line_end].strip()

    # If context is very short, CAUTIOUSLY grab the next line
    if len(context) < 40 and line_end < len(text):
        next_line_end = text.find('\n', line_end + 1)
        if next_line_end == -1:
            next_line_end = len(text)
        next_line = text[line_end + 1:next_line_end].strip()

        # Only add next line if it doesn't contain noise
        if next_line and not _EDUCATION_NOISE_PATTERNS.search(next_line):
            context = context + ' — ' + next_line

    # In strict/fallback mode, validate the entire context line
    if strict and _EDUCATION_NOISE_PATTERNS.search(context):
        # Strip the noisy parts — just return the degree match itself
        # with minimal clean surrounding text
        safe_context = text[match_start:match_end].strip()
        # Try to grab a few words after the degree for subject info
        after = text[match_end:match_end + 60]
        after_clean = after.split('\n')[0].strip()
        if after_clean and not _EDUCATION_NOISE_PATTERNS.search(after_clean):
            safe_context = safe_context + ' ' + after_clean
        return safe_context

    return context


# ═══════════════════════════════════════════════════════════════════════════
# ROLE DETECTION (with synonym normalization)
# ═══════════════════════════════════════════════════════════════════════════

def extract_roles(text: str, sections: dict = None) -> list:
    """Detect and normalize job roles/titles."""
    text_lower = text.lower()
    found = set()

    for role in ROLES_LIBRARY:
        escaped = re.escape(role)
        if re.search(r'(?:^|[\s,;|•·\-(])' + escaped + r'(?:[\s,;|•·\-)]|$)', text_lower):
            # Normalize through synonym map
            canonical = ROLE_SYNONYMS.get(role, role)
            found.add(canonical)

    # Remove substrings
    final = set()
    for role in found:
        is_sub = any(role != other and role in other for other in found)
        if not is_sub:
            final.add(role)

    return sorted(final)


def _get_best_role(roles: list) -> str:
    """Pick the most senior / specific role as a single string."""
    if not roles:
        return ''
    best = max(roles, key=len)
    return best.title()


# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

def extract_summary(text: str, sections: dict = None) -> str:
    """Extract a professional summary."""
    if sections and 'summary' in sections:
        summary_text = sections['summary'].strip()
        if summary_text:
            paras = [p.strip() for p in summary_text.split('\n\n') if p.strip()]
            if paras:
                return ' '.join(paras[0].split('\n')).strip()

    # Fallback: first substantial paragraph
    lines = text.split('\n')
    buffer = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buffer:
                candidate = ' '.join(buffer)
                if len(candidate) > 80 and not candidate.isupper():
                    return candidate
                buffer = []
            continue
        if stripped.isupper() and len(stripped) < 50:
            if buffer:
                candidate = ' '.join(buffer)
                if len(candidate) > 80:
                    return candidate
                buffer = []
            continue
        buffer.append(stripped)

    if buffer:
        candidate = ' '.join(buffer)
        if len(candidate) > 80:
            return candidate

    return ''


# ═══════════════════════════════════════════════════════════════════════════
# CONTACT INFO EXTRACTION (v2 — Location Leak Fix)
# ═══════════════════════════════════════════════════════════════════════════

# Job title words that should NEVER appear in a location string
_TITLE_WORDS = {
    'developer', 'engineer', 'manager', 'designer', 'analyst', 'architect',
    'scientist', 'administrator', 'consultant', 'freelancer', 'intern',
    'lead', 'senior', 'junior', 'principal', 'staff', 'director', 'head',
    'python', 'java', 'django', 'react', 'full', 'stack', 'frontend',
    'backend', 'software', 'web', 'mobile', 'data', 'cloud', 'devops',
    'qa', 'test', 'security', 'network', 'database', 'machine', 'learning',
}


def extract_contact_info(text: str) -> dict:
    """
    Extract email, phone, LinkedIn, GitHub, and location.
    FIX: Location regex is now constrained to prevent job title absorption.
    """
    info = {}

    # Email
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
    if email_match:
        info['email'] = email_match.group(0)

    # Phone
    phone_match = re.search(
        r'(?:\+?\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}', text
    )
    if phone_match:
        info['phone'] = phone_match.group(0).strip()

    # LinkedIn
    linkedin_match = re.search(r'(?:linkedin\.com/in/|linkedin:\s*)([\w-]+)', text, re.IGNORECASE)
    if linkedin_match:
        info['linkedin'] = f"https://linkedin.com/in/{linkedin_match.group(1)}"

    # GitHub
    github_match = re.search(r'(?:github\.com/|github:\s*)([\w-]+)', text, re.IGNORECASE)
    if github_match:
        info['github'] = f"https://github.com/{github_match.group(1)}"

    # Location — FIXED: constrained regex + filter against title words AND skills
    # Use literal space ' ' (NOT \s) to prevent matching across newlines
    loc_pattern = r'([A-Z][a-z]+(?: [A-Z][a-z]+){0,2}), *([A-Z][a-z]+(?: [A-Z][a-z]+){0,2})'
    for loc_match in re.finditer(loc_pattern, text):
        candidate = loc_match.group(0)
        words = candidate.replace(',', ' ').split()

        # Check against title words
        has_title_word = any(w.lower() in _TITLE_WORDS for w in words)
        if has_title_word:
            continue

        # Check against the skills library (catches "Docker, GitHub", etc.)
        has_skill_word = any(w.lower() in _ALL_SKILL_KEYS for w in words)
        if has_skill_word:
            continue

        # Reject if it appears inside a comma-separated list (skills section)
        # Heuristic: if there are 3+ commas on the same line, it's likely a list
        line_start = text.rfind('\n', 0, loc_match.start()) + 1
        line_end = text.find('\n', loc_match.end())
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end]
        if line.count(',') >= 3:
            continue

        info['location'] = candidate
        break  # take the first clean match

    return info


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════

def parse_resume_to_json(cleaned_text: str) -> dict:
    """
    Orchestrate all extractors and produce structured output.

    Returns BOTH:
      - Top-level simple schema (skills, experience_years, education, inferred_role)
      - A 'details' key with the full rich data for the frontend
    """
    sections = _detect_sections(cleaned_text)
    tokens = tokenize(cleaned_text)

    skills = extract_skills(cleaned_text, sections)
    experience = extract_experience(cleaned_text, sections)
    education_list = extract_education(cleaned_text, sections)
    roles = extract_roles(cleaned_text, sections)
    summary = extract_summary(cleaned_text, sections)
    contact_info = extract_contact_info(cleaned_text)

    return {
        # ── Strict simple schema ──
        'skills': skills,
        'experience_years': experience['estimated_total'],
        'education': _get_best_education(education_list),
        'inferred_role': _get_best_role(roles),

        # ── Rich details for frontend display ──
        'details': {
            'all_education': education_list,
            'all_roles': roles,
            'experience': experience,
            'summary': summary,
            'contact_info': contact_info,
            'companies': experience.get('companies', []),
            'token_count': len(tokens),
            'spacy_available': _nlp is not None,
        },
    }
