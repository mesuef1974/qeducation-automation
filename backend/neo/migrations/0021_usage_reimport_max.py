from django.db import migrations


def reset(apps, schema_editor):
    # الاستيراد صار يأخذ أكبر أرقام أسطر الرسالة المكررة: كل ملف يُقرأ من أوله مرة، فتُصحَّح الخطوات المحفوظة
    apps.get_model("neo", "UsageFile").objects.update(size=0, mtime=0, offset=0)


class Migration(migrations.Migration):
    dependencies = [("neo", "0020_usage_verify_job")]
    operations = [migrations.RunPython(reset, migrations.RunPython.noop)]
