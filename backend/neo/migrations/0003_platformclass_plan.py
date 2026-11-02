"""ربط الصف بخطة محددة بدل المستوى: يُنقل كل صف قائم إلى أحدث خطة لمستواه."""
import django.db.models.deletion
from django.db import migrations, models


def link_plans(apps, schema_editor):
    Plan = apps.get_model("curriculum", "Plan")
    PlatformClass = apps.get_model("neo", "PlatformClass")
    for k in PlatformClass.objects.all():
        plan = Plan.objects.filter(grade_level=k.grade_level).order_by("-academic_year", "-term_no").first()
        if plan is None:
            raise RuntimeError(f"لا توجد خطة للمستوى {k.grade_level} لربط الصف {k.name}؛ شغّل import_plans أولًا")
        k.plan_id = plan.pk
        k.save(update_fields=["plan"])


def unlink_plans(apps, schema_editor):
    PlatformClass = apps.get_model("neo", "PlatformClass")
    for k in PlatformClass.objects.select_related("plan"):
        k.grade_level = k.plan.grade_level
        k.save(update_fields=["grade_level"])


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0002_plan_identity"),
        ("neo", "0002_alter_syncrun_kind_platformassessment_assignproposal"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformclass",
            name="plan",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="platform_classes", to="curriculum.plan", verbose_name="الخطة"),
        ),
        migrations.AddField(
            model_name="platformclass",
            name="active",
            field=models.BooleanField(default=True, help_text="الصفوف غير المفعّلة تُستثنى من كل المهام",
                                      verbose_name="مفعّل"),
        ),
        migrations.AlterField(
            model_name="platformclass",
            name="grade_level",
            field=models.PositiveSmallIntegerField(null=True, verbose_name="المستوى"),
        ),
        migrations.RunPython(link_plans, unlink_plans),
        migrations.RemoveField(model_name="platformclass", name="grade_level"),
        migrations.AlterField(
            model_name="platformclass",
            name="plan",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="platform_classes",
                                    to="curriculum.plan", verbose_name="الخطة"),
        ),
        migrations.AlterModelOptions(
            name="platformclass",
            options={"ordering": ["-active", "name"], "verbose_name": "صف على المنصة",
                     "verbose_name_plural": "الصفوف على المنصة"},
        ),
    ]
