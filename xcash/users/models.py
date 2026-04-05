from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from sequences import get_next_value

from users.managers import UserManager


class User(AbstractUser):
    # 认证主标识从邮箱切换为用户名，避免业务账号体系继续强依赖邮件能力。
    username = models.CharField(
        _("用户名"),
        max_length=150,
        unique=True,
        error_messages={
            "unique": _("此用户名已被使用."),
        },
    )
    first_name = None
    last_name = None
    # 后台账号体系不再保留邮箱字段；这里显式置空，避免继续继承 AbstractUser.email。
    email = None

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []
    objects = UserManager()  # 使用自定义管理器

    def get_full_name(self):
        # 修复：admin 侧边栏会调用 get_full_name；当前模型已移除 first_name/last_name，需稳定回退到 username。
        return self.username or ""

    def get_short_name(self):
        # 修复：与 get_full_name 保持同一回退策略，避免头像首字母和用户名称展示继续读到无效字段。
        return self.username or ""


class Customer(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        verbose_name=_("项目"),
    )
    uid = models.CharField(
        db_index=True,
        verbose_name=_("客户UID"),
    )
    # address_index 对应 BIP44 的 address_index 层级，在项目内唯一；不同项目都从 0 开始分配。
    address_index = models.BigIntegerField(
        editable=False,
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="加入时间")

    class Meta:
        # 统一采用具名 UniqueConstraint，便于数据库约束报错定位和后续约束扩展。
        constraints = [
            models.UniqueConstraint(
                fields=("uid", "project"),
                name="uniq_customer_uid_project",
            ),
            models.UniqueConstraint(
                fields=("address_index", "project"),
                name="uniq_customer_address_index_project",
            ),
        ]
        verbose_name = _("客户")
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.uid

    def save(self, *args, **kwargs):
        if self.pk is None and self.address_index is None:
            sequence_name = self.get_project_sequence_name()
            # get_next_value 会为这个动态名称的序列获取下一个值
            # initial_value=0 确保序列的第一个值是 0
            self.address_index = get_next_value(sequence_name, initial_value=0)

        super().save(*args, **kwargs)

    def get_project_sequence_name(self):
        # 为每个 project 生成一个动态且唯一的序列名称
        # 序列名在数据库层唯一标识项目的 address_index 自增器，不可随意更改。
        return f"customer_address_index_project_{self.project_id}"


class AdminAccessLog(models.Model):
    class Action(models.TextChoices):
        PASSWORD_LOGIN = "password_login", _("密码登录")
        OTP_VERIFY = "otp_verify", _("两步验证校验")
        OTP_SETUP = "otp_setup", _("两步验证绑定")
        OTP_ROTATE = "otp_rotate", _("两步验证修改")
        LOGOUT = "logout", _("退出登录")

    class Result(models.TextChoices):
        SUCCEEDED = "succeeded", _("成功")
        FAILED = "failed", _("失败")

    user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_access_logs",
        verbose_name=_("用户"),
    )
    username_snapshot = models.CharField(
        _("用户名快照"), max_length=150, blank=True, default=""
    )
    ip = models.GenericIPAddressField(_("IP"), null=True, blank=True)
    user_agent = models.TextField(_("User-Agent"), blank=True, default="")
    action = models.CharField(_("动作"), choices=Action.choices, max_length=32)
    result = models.CharField(_("结果"), choices=Result.choices, max_length=16)
    reason = models.TextField(_("原因"), blank=True, default="")
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = _("后台访问日志")
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.username_snapshot}:{self.action}:{self.result}"
