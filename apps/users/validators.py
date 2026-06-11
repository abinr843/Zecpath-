import os.path

from django.core.exceptions import ValidationError
from django.conf import settings



def validate_resume_ext(value):
    ext = os.path.splitext(value.name)[1].lower()
    valid_ext= ['.pdf','.doc','.docx']
    if ext not in valid_ext:
        raise ValidationError('Invalid file extension')


def validate_resume_size(value):
    limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
    if value.size > limit:
        raise ValidationError('Invalid file size')
