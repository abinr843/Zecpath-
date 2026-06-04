
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Employer, Candidate


class CustomUserAdmin(UserAdmin):
    # The fields to display in the user list view
    list_display = ('email', 'username', 'role', 'is_active', 'is_verified','date_joined','updated_at')

    # Add filters on the right sidebar
    list_filter = ('role', 'is_active', 'is_verified')

    # The fields to display when editing an existing user
    fieldsets = UserAdmin.fieldsets + (
        ('Zecpath Custom Fields', {'fields': ('role', 'phone', 'is_verified')}),
    )

    # The fields to display when creating a NEW user from the admin panel
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Zecpath Custom Fields', {'fields': ('email', 'role', 'phone')}),
    )


# Register the models
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(Candidate)
admin.site.register(Employer)

