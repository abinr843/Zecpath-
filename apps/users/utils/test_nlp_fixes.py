"""Quick test of the NLP fixes against a representative resume."""
import sys
import os
import json

# Add Django project to path
sys.path.insert(0, r'c:\Users\abinr\PycharmProjects\PythonProject1\zecpath\jobplatform')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jobplatform.settings')

from apps.users.utils.resume_nlp import parse_resume_to_json

# Simulate the user's resume text
sample_resume = """
Abin R Philip
Junior Python Django Developer
Adoor, Kerala | +91 8075906338 | abinrphilip34@gmail.com

SUMMARY
Junior Python Django Developer with hands-on experience building backend APIs and full-stack web
applications. Developed real-world projects with features like payment integration, real-time processing, and
secure authentication. Strong foundation in Django, REST APIs, and database design, with experience working
in Agile teams and contributing to production-ready applications.

SKILLS
Python, Django, JavaScript, HTML, CSS, MySQL, PostgreSQL, MongoDB, Docker, GitHub, REST API, Celery, Agile

EXPERIENCE
Python Developer Intern -- SLBS Marklance
2022 - 2025
* Built a payment integration module using Razorpay and Stripe
* Collaborated with senior developers on microservice architecture
* Optimized database queries for better performance
* Developed REST APIs for mobile and web clients
* Worked with Celery for background task processing

PROJECTS
E-Commerce Platform
* Built a full-stack e-commerce platform with Django and React
* Integrated payment gateway with Stripe API
* Implemented real-time order tracking using WebSockets

EDUCATION
Bachelor of Computer Application (BCA)
University of Kerala, 2019 - 2022
"""

result = parse_resume_to_json(sample_resume)

print("=" * 60)
print("TOP-LEVEL SCHEMA:")
print("  Skills:", result['skills'])
print("  Experience Years:", result['experience_years'])
print("  Education:", result['education'])
print("  Inferred Role:", result['inferred_role'])

print()
print("=" * 60)
print("DETAILS:")
details = result['details']
print("  Companies:", details['companies'])
print("  All Roles:", details['all_roles'])
print("  Contact:", details['contact_info'])
print("  Summary:", details['summary'][:80] + "...")
print("  spaCy:", details['spacy_available'])

print()
print("=" * 60)
print("BUG CHECK:")

# Company leak check
companies = details['companies']
print("  Companies found:", companies)
bad_companies = [c for c in companies if c.lower() in ('celery', 'built', 'collaborated', 'optimized', 'developed', 'worked')]
if bad_companies:
    print("  FAIL: COMPANY LEAK:", bad_companies)
else:
    print("  PASS: No company leak")

# Location leak check
location = details['contact_info'].get('location', '')
print("  Location: '" + location + "'")
if 'developer' in location.lower() or 'python' in location.lower() or 'django' in location.lower() or 'docker' in location.lower():
    print("  FAIL: LOCATION LEAK")
else:
    print("  PASS: No location leak")

# Education noise check
education = result['education']
print("  Education: '" + education + "'")
if 'developer' in education.lower() or '@' in education or 'intern' in education.lower():
    print("  FAIL: EDUCATION NOISE")
else:
    print("  PASS: No education noise")
