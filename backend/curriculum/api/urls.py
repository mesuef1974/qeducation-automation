from rest_framework.routers import DefaultRouter

from curriculum.api.views import CalendarViewSet, PlanViewSet

router = DefaultRouter()
router.register(r"plans", PlanViewSet, basename="plan")
router.register(r"calendar", CalendarViewSet, basename="calendar")

urlpatterns = router.urls
