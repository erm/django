from django.urls import path

from asgiapp.views import TestView

urlpatterns = [path("test/", TestView.as_view())]
