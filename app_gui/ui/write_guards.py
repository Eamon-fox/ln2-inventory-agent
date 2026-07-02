"""迁移模式写入守卫装饰器。

将散落在各 operations_panel_*.py 中的样板收敛为统一装饰器：

    if bool(getattr(self, "_guard_write_action_by_migration_mode", lambda: False)()):
        return

被装饰函数的第一个位置参数必须是持有守卫方法的面板对象（``self``）。
"""

import functools

_GUARD_ATTR = "_guard_write_action_by_migration_mode"


def guard_write_action(func):
    """写入动作守卫装饰器。

    - 守卫方法返回真值时，直接返回 ``None``，不执行被装饰函数体。
    - 面板对象没有守卫方法时（容错），照常执行被装饰函数。
    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        guard = getattr(self, _GUARD_ATTR, None)
        if guard is not None and bool(guard()):
            return None
        return func(self, *args, **kwargs)

    return wrapper
