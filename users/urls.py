from django.urls import path
from users.views import RegisterView, LoginView, CustomTokenRefreshView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='user-register'),
    path('login/', LoginView.as_view(), name='user-login'),
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token-refresh'),
]
