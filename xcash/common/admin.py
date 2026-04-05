from django.db import models
from unfold.admin import ModelAdmin as UnfoldModelAdmin


class ModelAdmin(UnfoldModelAdmin):
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if isinstance(db_field, models.URLField):
            # 后台表单显式采用 https 作为 URLField 默认 scheme，避免依赖 Django 6.0 过渡设置。
            kwargs.setdefault("assume_scheme", "https")
        return super().formfield_for_dbfield(db_field, request, **kwargs)


class NoDeleteModelAdmin(ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False  # 禁止删除


class ReadOnlyModelAdmin(ModelAdmin):
    def has_change_permission(self, request, obj=None):
        return False  # 禁止编辑

    def has_delete_permission(self, request, obj=None):
        return False  # 禁止删除

    def has_add_permission(self, request):
        return False  # 禁止添加
