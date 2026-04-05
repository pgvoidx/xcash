from celery import shared_task

from users.models import User


@shared_task(ignore_result=True)
def deactivate_user(pk):
    # 停用任务只修改单字段，不依赖 save() 信号，直接 update 可减少一次对象回写。
    User.objects.filter(pk=pk).update(is_active=False)
