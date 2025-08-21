from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('Gateway.urls')),  # Include the URLs from the Gateway app
]