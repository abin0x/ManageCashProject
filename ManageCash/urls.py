from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile, name='profile'),
    path('transactions/', views.transactions, name='transactions'),
    path('transactions/export/pdf/', views.transactions_export_pdf, name='transactions_export_pdf'),
    path('transactions/<str:kind>/add/', views.transaction_create, name='transaction_create'),
    path('transactions/<str:kind>/<int:pk>/edit/', views.transaction_edit, name='transaction_edit'),
    path('transactions/<str:kind>/<int:pk>/delete/', views.transaction_delete, name='transaction_delete'),
]
