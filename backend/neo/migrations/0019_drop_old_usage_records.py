from django.db import migrations

# سجلّا الترحيلين الأولين للاستهلاك (استُبدلا بـ 0018_usage_normalized) لا ملف لهما بعد الآن: يُحذفان من جدول الترحيلات.
OLD = ("0018_usage", "0019_usage_normalized")


def drop(apps, schema_editor):
    schema_editor.execute("DELETE FROM django_migrations WHERE app = 'neo' AND name IN (%s, %s)", OLD)


class Migration(migrations.Migration):
    dependencies = [("neo", "0018_usage_normalized")]
    operations = [migrations.RunPython(drop, migrations.RunPython.noop)]
