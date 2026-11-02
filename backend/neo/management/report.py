"""طباعة عمليات SyncRun في الطرفية بصيغة واحدة لكل أوامر neo_*."""
import json

from neo.models import SyncRun

# العمليات التي تُطبع ملخصاتها في سطر واحد
COMPACT = {SyncRun.Kind.FETCH, SyncRun.Kind.APPLY, SyncRun.Kind.ASSIGN_APPLY, SyncRun.Kind.PUBLISH_APPLY}


def write_runs(stdout, style, runs: list[SyncRun]) -> None:
    for r in runs:
        head = f"[{r.get_kind_display()} #{r.pk}] {r.klass}"
        if r.kind == SyncRun.Kind.VERIFY:
            head += f" - {'سليم' if r.ok else 'دروس ماضية لا يراها الطالب'}"
        if r.kind in COMPACT:
            stdout.write((style.SUCCESS if r.ok else style.ERROR)(f"{head}: {json.dumps(r.summary, ensure_ascii=False)}"))
            continue
        stdout.write((style.SUCCESS if r.ok else style.ERROR)(head))
        stdout.write(json.dumps(r.summary, ensure_ascii=False, indent=1))
