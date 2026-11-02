from django.urls import path
from rest_framework.routers import DefaultRouter

from neo.api.views import ClassViewSet, JobViewSet, LessonViewSet, ProposalViewSet, RunViewSet, scorecard, session, weekly

router = DefaultRouter()
router.register(r"classes", ClassViewSet, basename="neo-class")
router.register(r"lessons", LessonViewSet, basename="neo-lesson")
router.register(r"runs", RunViewSet, basename="neo-run")
router.register(r"proposals/(?P<kind>[a-z]+)", ProposalViewSet, basename="neo-proposal")
router.register(r"jobs", JobViewSet, basename="neo-job")

urlpatterns = [path("session/", session, name="neo-session"), path("scorecard/", scorecard, name="neo-scorecard"),
               path("weekly/", weekly, name="neo-weekly"), *router.urls]
