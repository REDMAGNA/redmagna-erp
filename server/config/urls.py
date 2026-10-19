from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.views.generic import TemplateView
from .views import ApiSessionListView, ApiSessionRevokeView, CurrentUserView, LogoutView, health_check, serve_frontend_script, serve_license, serve_source_bundle
from django.urls import include, path, reverse_lazy
from sales.views import accept_quote_public, public_quote_request
from .auth import TokenLoginView


urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="home"),
    path("healthz/", health_check, name="health-check"),
    path("app.js", serve_frontend_script, name="frontend-script"),
    path("license.txt", serve_license, name="license-text"),
    path("source.zip", serve_source_bundle, name="source-bundle"),
    path("cotizaciones/aceptar/<str:token>/", accept_quote_public, name="quote-accept"),
    path("solicitar-cotizacion/", public_quote_request, name="public-quote-request"),
    path("accounts/password-reset/", auth_views.PasswordResetView.as_view(
        template_name="registration/password_reset_form.html",
        email_template_name="registration/password_reset_email.html",
        subject_template_name="registration/password_reset_subject.txt",
        success_url=reverse_lazy("password_reset_done"),
    ), name="password_reset"),
    path("accounts/password-reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html",
    ), name="password_reset_done"),
    path("accounts/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_reset_confirm.html",
        success_url=reverse_lazy("password_reset_complete"),
    ), name="password_reset_confirm"),
    path("accounts/reset/complete/", auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_reset_complete.html",
    ), name="password_reset_complete"),
    path("admin/", admin.site.urls),
    path("api/auth/token/", TokenLoginView.as_view(), name="api-token-auth"),
    path("api/auth/me/", CurrentUserView.as_view(), name="api-current-user"),
    path("api/auth/logout/", LogoutView.as_view(), name="api-logout"),
    path("api/auth/sessions/", ApiSessionListView.as_view(), name="api-session-list"),
    path("api/auth/sessions/<uuid:session_id>/revoke/", ApiSessionRevokeView.as_view(), name="api-session-revoke"),
    path("api/", include("sales.urls")),
    path("api/inventory/", include("inventory.urls")),
    path("api/accounting/", include("accounting.urls")),
    path("api/billing/", include("billing.urls")),
    path("api/purchasing/", include("purchasing.urls")),
    path("api/support/", include("support.urls")),
    path("api/repairs/", include("repairs.urls")),
    path("api/expenses/", include("expenses.urls")),
]
