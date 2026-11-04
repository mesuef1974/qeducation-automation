"""
أدلة كل اقتراح (الخطوة 4): قبل/بعد، والسبب من الخطة، والأثر على الطالب، وهل يبدأ درسه خلال 48 ساعة.
نصوص للعرض فقط؛ لا تلمس المنصة.
"""
from datetime import date, timedelta

from django.utils import timezone

from neo.models import AssignProposal, ContentProposal, DateProposal, PublishProposal
from neo.services.publish_service import policy

SOON = timedelta(hours=48)


def _slot(d: date | None, period: int | None) -> str:
    return f"{d:%Y-%m-%d} ح{period}" if d else "بلا تاريخ"


def _soon(d: date | None) -> bool:
    today = timezone.localdate()
    return d is not None and today <= d <= today + timedelta(days=2)


def _when(dt) -> str:
    return f"{timezone.localtime(dt):%Y-%m-%d %H:%M}"


def of(p) -> dict:
    if isinstance(p, DateProposal):
        pl = p.lesson
        reason = f"الخطة: الأسبوع {p.plan_week_no} · درس {pl.effective_code or '-'}"
        return {"before": _slot(pl.date, pl.period), "after": _slot(p.proposed_date, p.proposed_period),
                "reason": reason + (f" · {p.flags}" if p.flags else ""),
                "impact": f"يظهر الدرس للطالب في {p.proposed_date:%Y-%m-%d} الحصة {p.proposed_period}",
                "lesson_date": p.proposed_date, "soon": _soon(p.proposed_date)}
    if isinstance(p, AssignProposal):
        late = "ويُقبل المتأخر" if p.allow_late else "ولا يُقبل المتأخر"
        return {"before": "مُسند" if p.assessment.given else "غير مُسند",
                "after": f"{_when(p.begin_at)} ← {_when(p.end_at)}",
                "reason": f"تاريخ الدرس في الخطة {p.lesson_date:%Y-%m-%d}" + (f" · {p.flags}" if p.flags else ""),
                "impact": f"يفتح التقييم للطالب {_when(p.begin_at)} ويستحق {_when(p.end_at)} {late}",
                "lesson_date": p.lesson_date, "soon": _soon(p.lesson_date)}
    pl = p.lesson
    if isinstance(p, PublishProposal):
        pol = policy(pl.klass)
        before = ["مخفي" if pl.hidden else "ظاهر", "يمنح النقاط" if pl.awards_points else "بلا نقاط"]
        after = [("ظاهر" if p.show else before[0]), (f"يمنح {pol.points} نقاط" if p.add_points else before[1])]
        impact = []
        if p.show:
            impact.append("يرى الطالب الدرس")
        if p.add_points:
            impact.append(f"ينال الطالب {pol.points} نقاط في «{pol.game}» عند إنجازه")
        return {"before": "، ".join(before), "after": "، ".join(after),
                "reason": "درس مؤرخ مخفي" if p.show else "درس بلا إجراء نقاط عند الإنجاز",
                "impact": "، و".join(impact), "lesson_date": pl.date, "soon": _soon(pl.date)}
    if isinstance(p, ContentProposal):
        label = p.get_kind_display()
        return {"before": f"ينقصه {label}", "after": f"يُضاف {label} (إضافة فقط)",
                "reason": f"تدقيق الجودة · درس الخطة {pl.effective_code or '-'}",
                "impact": "درس أكمل للطالب وفق معايير الجودة (الخطوة 2)", "lesson_date": pl.date, "soon": _soon(pl.date)}
    return {}
