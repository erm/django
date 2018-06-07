from django.urls import path

from asgiapp.views import TestView, TestAsyncView

urlpatterns = [path("test/", TestAsyncView.as_view())]
