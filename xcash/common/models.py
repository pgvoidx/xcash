from django.db import models
from django.db.models import ProtectedError


class UndeletableModel(models.Model):
    """
    禁止删除的抽象基类模型
    所有继承此类的模型都将禁止删除操作
    """

    class Meta:
        abstract = True  # 设置为抽象基类

    def delete(self, *args, **kwargs):
        raise ProtectedError("禁止删除.", {self})

    # 确保批量删除也被阻止,覆盖 delete 方法
    @classmethod
    def delete_queryset(cls, queryset):
        raise ProtectedError("禁止删除.", queryset)
