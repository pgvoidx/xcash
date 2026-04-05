import json
from functools import wraps
from hashlib import sha256

from django.core.cache import cache


def singleton_task(timeout, *, use_params=False):
    def task_decorator(task_func):
        @wraps(task_func)
        def wrapper(*args, **kwargs):
            if use_params:
                params_hash = _generate_func_key(task_func, *args, **kwargs)
                lock_id = f"{task_func.__name__}-locked-{params_hash}"
            else:
                lock_id = f"{task_func.__name__}-locked"

            def acquire_lock():
                return cache.add(lock_id, "true", timeout)

            def release_lock():
                return cache.delete(lock_id)

            if acquire_lock():
                try:
                    return task_func(*args, **kwargs)
                finally:
                    release_lock()

            return None

        return wrapper

    return task_decorator


def cache_func(timeout, *, use_params=True):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if use_params:
                cache_key = _generate_func_key(func, *args, **kwargs)
            else:
                cache_key = _generate_func_key(func)

            result = cache.get(cache_key)
            if result is not None:
                return result

            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout)
            return result

        return wrapper

    return decorator


def _generate_func_key(func, *args, **kwargs):
    """
    根据函数名和参数生成唯一的哈希 key
    """

    try:
        # 使用 json 序列化确保顺序一致
        kwargs_str = json.dumps(kwargs, sort_keys=True, default=str)
    except Exception:  # noqa
        kwargs_str = str(kwargs)

    key = f"{func.__module__}.{func.__name__}:{args}:{kwargs_str}"
    return sha256(key.encode("utf-8")).hexdigest()
