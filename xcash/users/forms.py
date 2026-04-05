from django import forms
from django.contrib.auth import forms as admin_forms
from django.utils.translation import gettext_lazy as _
from unfold.widgets import UnfoldAdminPasswordWidget
from unfold.widgets import UnfoldAdminTextInputWidget

from .models import User


class UserAdminChangeForm(admin_forms.UserChangeForm):
    class Meta(admin_forms.UserChangeForm.Meta):  # type: ignore[name-defined]
        model = User
        fields = "__all__"


class UserAdminCreationForm(admin_forms.AdminUserCreationForm):
    """
    Form for User Creation in the Admin Area.
    """

    class Meta(admin_forms.UserCreationForm.Meta):  # type: ignore[name-defined]
        model = User
        fields = ("username",)
        error_messages = {"username": {"unique": _("此用户名已被使用.")}}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["username"].widget = UnfoldAdminTextInputWidget()
        self.fields["password1"].widget = UnfoldAdminPasswordWidget(
            attrs={"autocomplete": "new-password"}
        )
        self.fields["password2"].widget = UnfoldAdminPasswordWidget(
            attrs={"autocomplete": "new-password"}
        )


class LoginForm(forms.Form):
    """
    Form used by the public admin login entrance.
    """

    username = forms.CharField(
        required=True,
        label=_("用户名"),
        widget=UnfoldAdminTextInputWidget(),
    )
    password = forms.CharField(
        required=True,
        label=_("密码"),
        widget=UnfoldAdminPasswordWidget(attrs={"autocomplete": "new-password"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        try:
            user = User.objects.get(username=username)
            if not user.is_active:
                raise forms.ValidationError(_("此账户已被禁用，如有疑问请联系管理员。"))
        except User.DoesNotExist as exc:
            raise forms.ValidationError("此用户名未注册。") from exc

        return cleaned_data


class OTPVerifyForm(forms.Form):
    token = forms.CharField(
        required=True,
        label=_("两步验证码"),
        widget=UnfoldAdminTextInputWidget(attrs={"autocomplete": "one-time-code"}),
    )


class OTPSetupForm(OTPVerifyForm):
    device_name = forms.CharField(
        required=False,
        label=_("设备名称"),
        widget=UnfoldAdminTextInputWidget(),
        initial="后台两步验证",
    )


class AdminUserOTPChangeForm(OTPSetupForm):
    current_password = forms.CharField(
        required=False,
        label=_("当前密码"),
        widget=UnfoldAdminPasswordWidget(attrs={"autocomplete": "current-password"}),
    )
    current_token = forms.CharField(
        required=False,
        label=_("当前两步验证码"),
        widget=UnfoldAdminTextInputWidget(attrs={"autocomplete": "one-time-code"}),
    )

    def __init__(
        self,
        *args,
        require_current_password: bool = False,
        require_existing_token: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        # 自己修改 OTP 时必须先完成一次旧身份确认，避免仅凭已登录会话就直接换绑密钥。
        self.fields["current_password"].required = require_current_password
        self.fields["current_token"].required = require_existing_token
